from fastapi import FastAPI
from fastapi.testclient import TestClient

from software_developer_agent.api.routes import jobs as jobs_routes
from software_developer_agent.artifacts.project_generator import ProjectArtifactGenerator
from software_developer_agent.config.settings import Settings
from software_developer_agent.models.job_state import JobRequest, JobState, JobTask, WorkerKind
from software_developer_agent.orchestration.redis_queue import InMemoryJobQueue
from software_developer_agent.persistence.job_store import InMemoryJobStore


def test_artifact_routes_list_preview_and_download(tmp_path, monkeypatch) -> None:
    settings = Settings(
        app_env="test",
        artifacts_dir=tmp_path / "artifacts",
        generated_projects_dir=tmp_path / "generated",
    )
    store = InMemoryJobStore()
    queue = InMemoryJobQueue()
    job = JobState(
        request=JobRequest(
            prompt="Build a SaaS analytics dashboard with roles and billing",
            project_id="demo-app",
        )
    )
    job.tasks = [
        JobTask(
            worker_kind=WorkerKind.BACKEND,
            title="Backend",
            instructions="Build backend",
        ),
        JobTask(
            worker_kind=WorkerKind.FRONTEND,
            title="Frontend",
            instructions="Build frontend",
        ),
    ]
    for artifact in ProjectArtifactGenerator(settings).generate(job):
        job.add_artifact(artifact)
    store.save(job)

    monkeypatch.setattr(jobs_routes, "get_job_store", lambda: store)
    monkeypatch.setattr(jobs_routes, "get_job_queue", lambda: queue)
    monkeypatch.setattr(jobs_routes, "get_settings", lambda: settings)

    app = FastAPI()
    app.include_router(jobs_routes.router, prefix="/api")
    client = TestClient(app)

    files_response = client.get(f"/api/jobs/{job.job_id}/files")
    assert files_response.status_code == 200
    assert any(file["path"] == "README.md" for file in files_response.json()["files"])

    preview_response = client.get(
        f"/api/jobs/{job.job_id}/files/content", params={"path": "README.md"}
    )
    assert preview_response.status_code == 200
    assert "# Demo App" in preview_response.text

    download_response = client.get(f"/api/jobs/{job.job_id}/download")
    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/zip"
