import hashlib
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from software_developer_agent.api.routes import jobs as jobs_routes
from software_developer_agent.api.routes import workspace as workspace_routes
from software_developer_agent.artifacts.project_generator import ProjectArtifactGenerator
from software_developer_agent.capabilities.registry import resolve_project_spec
from software_developer_agent.config.settings import Settings
from software_developer_agent.models.job_state import (
    JobArtifact,
    JobRequest,
    JobState,
    JobTask,
    WorkerKind,
)
from software_developer_agent.orchestration.redis_queue import InMemoryJobQueue
from software_developer_agent.persistence.job_store import InMemoryJobStore
from software_developer_agent.workspace.revisions import RevisionStore


def test_workspace_edit_creates_revision_and_refreshes_zip(tmp_path, monkeypatch) -> None:
    settings = Settings(
        app_env="test",
        artifacts_dir=tmp_path / "artifacts",
        generated_projects_dir=tmp_path / "generated",
        preview_cache_dir=tmp_path / "previews",
    )
    store = InMemoryJobStore()
    queue = InMemoryJobQueue()
    spec = resolve_project_spec("Build a standalone React Vite frontend")
    job = JobState(
        request=JobRequest(
            prompt="Build a standalone React Vite frontend",
            project_id="editable-app",
            metadata={"capability_id": "react-vite"},
        ),
        project_spec=spec.to_dict(),
    )
    job.tasks = [
        JobTask(
            worker_kind=WorkerKind.FRONTEND,
            capability_id="react-vite",
            title="Frontend",
            instructions="Build frontend",
        )
    ]
    for artifact in ProjectArtifactGenerator(settings).generate(job):
        job.add_artifact(artifact)
    store.save(job)

    monkeypatch.setattr(jobs_routes, "get_job_store", lambda: store)
    monkeypatch.setattr(jobs_routes, "get_job_queue", lambda: queue)
    monkeypatch.setattr(jobs_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(workspace_routes, "get_job_store", lambda: store)
    monkeypatch.setattr(workspace_routes, "get_job_queue", lambda: queue)
    monkeypatch.setattr(workspace_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(
        workspace_routes,
        "get_revision_store",
        lambda: RevisionStore(settings.preview_cache_dir),
    )

    app = FastAPI()
    app.include_router(jobs_routes.router, prefix="/api")
    app.include_router(workspace_routes.router, prefix="/api")
    client = TestClient(app)
    path = "frontend/src/project.ts"
    current = client.get(f"/api/jobs/{job.job_id}/files/content", params={"path": path}).text
    expected_sha = hashlib.sha256(current.encode()).hexdigest()
    updated = current + "export const edited = true;\n"
    response = client.put(
        f"/api/jobs/{job.job_id}/files/content",
        params={"path": path},
        json={"content": updated, "expected_sha256": expected_sha},
    )
    assert response.status_code == 200
    assert response.json()["revision"]["path"] == path
    assert client.get(f"/api/jobs/{job.job_id}/revisions", params={"path": path}).json()

    zip_artifact = next(artifact for artifact in job.artifacts if artifact.kind == "zip")
    with zipfile.ZipFile(zip_artifact.path) as archive:
        assert archive.read(path).decode() == updated


def test_design_token_route_discovers_generated_css(tmp_path, monkeypatch) -> None:
    settings = Settings(
        app_env="test",
        artifacts_dir=tmp_path / "artifacts",
        generated_projects_dir=tmp_path / "generated",
        preview_cache_dir=tmp_path / "previews",
    )
    root = settings.generated_projects_dir / "demo"
    css = root / "frontend" / "src" / "styles.css"
    css.parent.mkdir(parents=True)
    css.write_text(":root { --accent: #64c7ff; }\n", encoding="utf-8")
    zip_path = settings.artifacts_dir / "demo.zip"
    zip_path.parent.mkdir(parents=True)
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(css, css.relative_to(root))
    job = JobState(request=JobRequest(prompt="Build a React frontend"))
    job.add_artifact(JobArtifact("folder", "folder", "demo", str(root), ""))
    job.add_artifact(JobArtifact("zip", "zip", "demo.zip", str(zip_path), ""))
    store = InMemoryJobStore()
    queue = InMemoryJobQueue()
    store.save(job)
    monkeypatch.setattr(jobs_routes, "get_job_store", lambda: store)
    monkeypatch.setattr(jobs_routes, "get_job_queue", lambda: queue)
    monkeypatch.setattr(jobs_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(workspace_routes, "get_job_store", lambda: store)
    monkeypatch.setattr(workspace_routes, "get_job_queue", lambda: queue)
    monkeypatch.setattr(workspace_routes, "get_settings", lambda: settings)

    app = FastAPI()
    app.include_router(workspace_routes.router, prefix="/api")
    response = TestClient(app).get(f"/api/jobs/{job.job_id}/design-tokens")
    assert response.status_code == 200
    assert response.json()["files"][0]["tokens"] == {"accent": "#64c7ff"}
