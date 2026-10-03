import json
from pathlib import Path

from software_developer_agent.artifacts.project_generator import (
    ProjectArtifactGenerator,
    _docker_compose,
    _github_actions_ci,
)
from software_developer_agent.artifacts.validation import ProjectValidationReport
from software_developer_agent.capabilities.registry import resolve_project_spec
from software_developer_agent.config.settings import Settings
from software_developer_agent.models.job_state import (
    GuardrailFinding,
    GuardrailReport,
    JobRequest,
    JobState,
    JobTask,
    TaskStatus,
    WorkerKind,
    WorkerResult,
)


def test_project_generator_creates_folder_and_zip(tmp_path) -> None:
    settings = Settings(
        app_env="test",
        artifacts_dir=tmp_path / "artifacts",
        generated_projects_dir=tmp_path / "generated",
    )
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

    artifacts = ProjectArtifactGenerator(settings).generate(job)

    folder = next(artifact for artifact in artifacts if artifact.kind == "folder")
    archive = next(artifact for artifact in artifacts if artifact.kind == "zip")

    assert (tmp_path / "generated").exists()
    assert folder.metadata["file_count"] > 10
    assert archive.path.endswith(".zip")
    generated = Path(folder.path)
    assert (generated / "backend/.python-version").read_text(encoding="utf-8") == "3.11\n"
    readme = (generated / "README.md").read_text(encoding="utf-8")
    assert "uv sync --locked" in readme
    assert "pip install" not in readme


def test_generated_python_automation_uses_uv() -> None:
    files = {
        "backend/pyproject.toml": (
            '[project]\nname="demo"\nversion="0.1.0"\nrequires-python=">=3.11"\n'
            "[dependency-groups]\ntest=[\"pytest==8.3.5\"]\n"
        ),
        "backend/src/app/main.py": "app = object()\n",
    }
    spec = resolve_project_spec("Build a FastAPI API with Docker and GitHub CI")

    compose = _docker_compose(files, {}, spec)
    workflow = _github_actions_ci(files, spec)

    assert "ghcr.io/astral-sh/uv:0.12.18-debian-slim" in compose
    assert "uv sync --locked --group test --no-editable" in compose
    assert "astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4" in workflow
    assert "uv run --locked --no-sync python -m pytest" in workflow
    assert "pip install" not in compose + workflow


def test_project_generator_writes_worker_manifest_files(tmp_path) -> None:
    settings = Settings(
        app_env="test",
        artifacts_dir=tmp_path / "artifacts",
        generated_projects_dir=tmp_path / "generated",
    )
    job = JobState(request=JobRequest(prompt="Build a todo webapp", project_id="todo"))
    task = JobTask(worker_kind=WorkerKind.BACKEND, title="Backend", instructions="Build API")
    task.status = TaskStatus.SUCCEEDED
    job.tasks = [task]
    job.add_worker_result(
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.BACKEND,
            status=TaskStatus.SUCCEEDED,
            summary="backend worker completed",
            output=(
                '{"summary":"Generated backend.",'
                '"files":[{"path":"backend/src/app/main.py","content":"from fastapi import FastAPI\\n"}],'
                '"validation_commands":["cd backend && pytest"]}'
            ),
        )
    )

    artifacts = ProjectArtifactGenerator(settings).generate(job)
    folder = next(artifact for artifact in artifacts if artifact.kind == "folder")

    assert folder.metadata["source"] == "worker_manifests"
    assert (tmp_path / "generated" / folder.name / "backend/src/app/main.py").exists()
    assert (tmp_path / "generated" / folder.name / "README.md").exists()


def test_project_generator_materializes_selected_media_and_records_provenance(
    tmp_path,
) -> None:
    class PassingValidator:
        def validate(self, root, job):
            return ProjectValidationReport(passed=True, release_ready=True)

    cache_path = tmp_path / "media-cache" / "frontend-task" / "image" / "asset.png"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(b"\x89PNG\r\n\x1a\nasset")
    web_path = "/assets/media/xpulse.png"
    project_path = "frontend/public/assets/media/xpulse.png"
    settings = Settings(
        app_env="test",
        artifacts_dir=tmp_path / "artifacts",
        generated_projects_dir=tmp_path / "generated",
        media_cache_dir=tmp_path / "media-cache",
    )
    task = JobTask(
        worker_kind=WorkerKind.FRONTEND,
        title="Frontend",
        instructions="Add an image",
        task_id="frontend-task",
        status=TaskStatus.SUCCEEDED,
    )
    job = JobState(request=JobRequest(prompt="Add an Xpulse image"), tasks=[task])
    job.add_worker_result(
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.FRONTEND,
            status=TaskStatus.SUCCEEDED,
            summary="frontend worker completed",
            output=json.dumps(
                {
                    "summary": "Generated frontend.",
                    "operation": "replace",
                    "files": [
                        {
                            "path": "frontend/src/App.tsx",
                            "content": f'export default () => <img src="{web_path}" />;\n',
                        },
                        {
                            "path": "frontend/package.json",
                            "content": '{"scripts":{"test":"vitest"}}',
                        },
                    ],
                }
            ),
            tool_calls=[
                {
                    "tool": "media_asset_acquisition",
                    "status": "succeeded",
                    "metadata": {
                        "assets": [
                            {
                                "kind": "image",
                                "title": "Xpulse",
                                "source": "Example",
                                "source_url": "https://example.com/xpulse",
                                "remote_url": "https://cdn.example.com/xpulse.png",
                                "rights_status": "verify-source-terms-before-publication",
                                "download": {
                                    "cache_path": str(cache_path),
                                    "project_path": project_path,
                                    "web_path": web_path,
                                    "sha256": "demo",
                                },
                            }
                        ]
                    },
                }
            ],
        )
    )

    artifacts = ProjectArtifactGenerator(settings, validator=PassingValidator()).generate(job)
    folder = next(artifact for artifact in artifacts if artifact.kind == "folder")
    generated = Path(folder.path)

    assert (generated / project_path).read_bytes().startswith(b"\x89PNG")
    media_manifest = json.loads(
        (generated / "artifacts/media-assets.json").read_text(encoding="utf-8")
    )
    assert media_manifest["assets"][0]["strategy"] == "download"
    blueprint = json.loads((generated / "artifacts/blueprint.json").read_text(encoding="utf-8"))
    assert project_path in blueprint["files"]
    assert folder.metadata["media_assets"][0]["selected_url"] == web_path


def test_project_generator_does_not_inject_excluded_infrastructure(tmp_path) -> None:
    settings = Settings(
        app_env="test",
        artifacts_dir=tmp_path / "artifacts",
        generated_projects_dir=tmp_path / "generated",
    )
    job = JobState(
        request=JobRequest(
            prompt="Build a local API. No database, Docker, GitHub, cloud, or deployment.",
            project_id="local-api",
        ),
        request_policy={
            "requested_capabilities": [],
            "excluded_capabilities": [
                "cloud",
                "database",
                "deployment",
                "docker",
                "github",
                "persistence",
            ],
        },
    )
    task = JobTask(worker_kind=WorkerKind.BACKEND, title="Backend", instructions="Build API")
    task.status = TaskStatus.SUCCEEDED
    job.tasks = [task]
    job.add_worker_result(
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.BACKEND,
            status=TaskStatus.SUCCEEDED,
            summary="backend worker completed",
            output=json.dumps(
                {
                    "summary": "Generated backend.",
                    "files": [
                        {
                            "path": "backend/pyproject.toml",
                            "content": "[project]\nname='local-api'\nversion='0.1.0'\n",
                        },
                        {
                            "path": "backend/src/app/main.py",
                            "content": "from fastapi import FastAPI\napp = FastAPI()\n",
                        },
                    ],
                }
            ),
        )
    )

    artifacts = ProjectArtifactGenerator(settings).generate(job)
    folder = next(artifact for artifact in artifacts if artifact.kind == "folder")
    generated = Path(folder.path)

    assert not (generated / "docker-compose.yml").exists()
    assert not (generated / ".env.example").exists()
    assert not (generated / "docs/credentials.md").exists()
    assert "docker compose" not in (generated / "README.md").read_text().lower()


def test_project_generator_documents_python_alembic_migration(tmp_path) -> None:
    settings = Settings(
        app_env="test",
        artifacts_dir=tmp_path / "artifacts",
        generated_projects_dir=tmp_path / "generated",
    )
    job = JobState(
        request=JobRequest(
            prompt="Build a FastAPI application with PostgreSQL persistence",
            project_id="alembic-app",
        )
    )
    task = JobTask(worker_kind=WorkerKind.DATABASE, title="Database", instructions="Build schema")
    task.status = TaskStatus.SUCCEEDED
    job.tasks = [task]
    job.add_worker_result(
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.DATABASE,
            status=TaskStatus.SUCCEEDED,
            summary="database worker completed",
            output=json.dumps(
                {
                    "operation": "replace",
                    "files": [
                        {"path": "database/alembic.ini", "content": "[alembic]\n"},
                        {
                            "path": "database/alembic/versions/001_initial.py",
                            "content": "def upgrade(): pass\n",
                        },
                    ],
                }
            ),
        )
    )

    artifacts = ProjectArtifactGenerator(settings).generate(job)
    folder = next(artifact for artifact in artifacts if artifact.kind == "folder")
    readme = Path(folder.path, "README.md").read_text(encoding="utf-8")

    assert "cd database\npython -m alembic upgrade head" in readme
    assert "database/migrations/001_initial.sql" not in readme


def test_project_generator_publishes_failed_validation_as_provisional(tmp_path) -> None:
    class FailingValidator:
        def validate(self, root, job):
            return ProjectValidationReport(
                passed=False,
                retry_targets=[WorkerKind.BACKEND],
                failure_reason="backend tests failed",
            )

    settings = Settings(
        app_env="test",
        artifacts_dir=tmp_path / "artifacts",
        generated_projects_dir=tmp_path / "generated",
    )
    job = JobState(request=JobRequest(prompt="Build API", project_id="invalid"))
    task = JobTask(worker_kind=WorkerKind.BACKEND, title="Backend", instructions="Build API")
    task.status = TaskStatus.SUCCEEDED
    job.tasks = [task]
    job.add_worker_result(
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.BACKEND,
            status=TaskStatus.SUCCEEDED,
            summary="backend worker completed",
            output=json.dumps(
                {
                    "summary": "Generated backend.",
                    "files": [
                        {
                            "path": "backend/src/app/main.py",
                            "content": "app = object()\n",
                        }
                    ],
                }
            ),
        )
    )

    artifacts = ProjectArtifactGenerator(settings, validator=FailingValidator()).generate(job)
    folder = next(artifact for artifact in artifacts if artifact.kind == "folder")
    archive = next(artifact for artifact in artifacts if artifact.kind == "zip")

    assert folder.metadata["release_status"] == "provisional"
    assert folder.metadata["publish_allowed"] is False
    assert Path(folder.path, "artifacts/risk-report.json").exists()
    assert Path(archive.path).exists()


def test_project_generator_preserves_blocked_output_as_quarantined(tmp_path) -> None:
    class PassingValidator:
        def validate(self, root, job):
            return ProjectValidationReport(passed=True, checks=["runtime:passed"])

    settings = Settings(
        app_env="test",
        artifacts_dir=tmp_path / "artifacts",
        generated_projects_dir=tmp_path / "generated",
    )
    job = JobState(request=JobRequest(prompt="Build API", project_id="quarantined"))
    job.tasks = [
        JobTask(
            worker_kind=WorkerKind.BACKEND,
            title="Backend",
            instructions="Build API",
        )
    ]
    job.add_guardrail_report(
        GuardrailReport(
            name="api_key_detection",
            passed=False,
            findings=[
                GuardrailFinding(
                    name="api_key_openai",
                    passed=False,
                    severity="critical",
                    message="Potential OpenAI secret detected in output.",
                    metadata={"blocking": True},
                )
            ],
        )
    )

    artifacts = ProjectArtifactGenerator(settings, validator=PassingValidator()).generate(job)
    folder = next(artifact for artifact in artifacts if artifact.kind == "folder")
    archive = next(artifact for artifact in artifacts if artifact.kind == "zip")
    risk_report = json.loads(
        Path(folder.path, "artifacts/risk-report.json").read_text(encoding="utf-8")
    )

    assert folder.metadata["release_status"] == "quarantined"
    assert folder.metadata["publish_allowed"] is False
    assert risk_report["preview_isolation_required"] is True
    assert risk_report["findings"][0]["blocking"] is True
    assert Path(archive.path).exists()


def test_validator_crash_is_classified_internal_not_infrastructure(tmp_path, monkeypatch) -> None:
    """A crash inside the validator proves nothing and must not pass as a warning."""

    monkeypatch.setattr(
        "software_developer_agent.artifacts.validation.ProjectValidator.validate",
        lambda self, root, job: (_ for _ in ()).throw(ValueError("boom")),
    )
    settings = Settings(
        app_env="development",
        enable_artifact_validation=False,
        artifacts_dir=tmp_path / "artifacts",
        generated_projects_dir=tmp_path / "generated",
    )
    job = JobState(request=JobRequest(prompt="Build a dashboard", project_id="crash-demo"))
    job.tasks = [
        JobTask(worker_kind=WorkerKind.BACKEND, title="Backend", instructions="Build backend"),
        JobTask(worker_kind=WorkerKind.FRONTEND, title="Frontend", instructions="Build frontend"),
    ]

    artifacts = ProjectArtifactGenerator(settings).generate(job)

    validation = next(a for a in artifacts if a.kind == "folder").metadata["validation"]
    assert validation["passed"] is False
    assert validation["failure_kind"] == "internal"
    assert validation["release_ready"] is False
