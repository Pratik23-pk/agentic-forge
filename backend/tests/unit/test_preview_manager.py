from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from software_developer_agent.capabilities.registry import resolve_project_spec
from software_developer_agent.config.settings import Settings
from software_developer_agent.models.job_state import JobRequest, JobState, ReleaseStatus
from software_developer_agent.sandbox.preview_manager import (
    PreviewManager,
    PreviewRecord,
    _preview_failure_marker,
)


def test_preview_service_uses_stack_native_nextjs_command(tmp_path: Path, monkeypatch) -> None:
    generated = tmp_path / "generated"
    frontend = generated / "demo" / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "package.json").write_text("{}", encoding="utf-8")
    settings = Settings(
        app_env="test",
        generated_projects_dir=generated,
        preview_cache_dir=tmp_path / "previews",
        preview_port_start=45_100,
        preview_port_end=45_110,
    )
    spec = resolve_project_spec("Build a Next.js application")
    job = JobState(
        request=JobRequest(prompt="Build a Next.js application"),
        project_spec=spec.to_dict(),
    )
    manager = PreviewManager(settings)
    monkeypatch.setattr(manager, "_available_port", lambda preferred, reserved=None: preferred)
    definitions = manager._service_definitions(
        job.job_id,
        frontend.parent,
        spec,
    )
    service, _, command, _ = definitions[0]
    assert service.name == "frontend"
    assert "--hostname" in command
    assert service.port == 3000


def test_frontend_capability_does_not_start_stray_backend(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "generated" / "demo"
    (project / "backend").mkdir(parents=True)
    (project / "frontend").mkdir()
    (project / "backend" / "pyproject.toml").write_text("", encoding="utf-8")
    (project / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    settings = Settings(
        app_env="test",
        generated_projects_dir=tmp_path / "generated",
        preview_cache_dir=tmp_path / "previews",
    )
    spec = resolve_project_spec("Build a React frontend", {"capability_id": "react-vite"})
    manager = PreviewManager(settings)
    monkeypatch.setattr(manager, "_available_port", lambda preferred, reserved=None: preferred)

    definitions = manager._service_definitions("job-12345678", project, spec)

    assert [service.name for service, *_ in definitions] == ["frontend"]


def test_fullstack_preview_injects_allocated_frontend_cors_origin(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "generated" / "demo"
    (project / "backend").mkdir(parents=True)
    (project / "frontend").mkdir()
    (project / "backend" / "requirements.txt").write_text("fastapi==1", encoding="utf-8")
    (project / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    settings = Settings(
        app_env="test",
        generated_projects_dir=tmp_path / "generated",
        preview_cache_dir=tmp_path / "previews",
        preview_host="127.0.0.1",
    )
    spec = resolve_project_spec("Build a React and FastAPI application")
    manager = PreviewManager(settings)
    monkeypatch.setattr(manager, "_available_port", lambda preferred, reserved=None: preferred)

    definitions = manager._service_definitions("job-12345678", project, spec)

    backend_environment = definitions[0][3]
    assert backend_environment["CORS_ORIGINS"] == ("http://127.0.0.1:5173,http://localhost:5173")
    frontend_environment = definitions[1][3]
    assert frontend_environment["VITE_API_BASE_URL"] == "http://127.0.0.1:5173"


def test_preview_failure_marker_detects_rendered_api_failure() -> None:
    assert _preview_failure_marker("Connection interrupted\nFailed to fetch") == ("failed to fetch")
    assert _preview_failure_marker("Commerce dashboard ready") is None


def test_preview_environment_does_not_inherit_credentials(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    manager = PreviewManager(Settings(app_env="test", preview_cache_dir=tmp_path))
    assert "OPENAI_API_KEY" not in manager._safe_environment()


def test_production_rejects_unisolated_local_preview(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    project = generated / "demo"
    project.mkdir(parents=True)
    settings = Settings(
        app_env="production",
        generated_projects_dir=generated,
        preview_cache_dir=tmp_path / "previews",
        preview_sandbox_mode="local",
    )
    job = JobState(request=JobRequest(prompt="Build a React application"))
    with pytest.raises(RuntimeError, match="require PREVIEW_SANDBOX_MODE=docker"):
        PreviewManager(settings).start(job, project)


def test_quarantined_build_rejects_local_preview(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    project = generated / "demo"
    project.mkdir(parents=True)
    settings = Settings(
        app_env="development",
        generated_projects_dir=generated,
        preview_cache_dir=tmp_path / "previews",
        preview_sandbox_mode="local",
    )
    job = JobState(
        request=JobRequest(prompt="Build an app"),
        release_status=ReleaseStatus.QUARANTINED,
    )

    with pytest.raises(RuntimeError, match="require Docker preview isolation"):
        PreviewManager(settings).start(job, project)


def test_quarantined_build_rejects_second_preview(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    project = generated / "demo"
    project.mkdir(parents=True)
    settings = Settings(
        app_env="development",
        generated_projects_dir=generated,
        preview_cache_dir=tmp_path / "previews",
        preview_sandbox_mode="docker",
    )
    job = JobState(
        request=JobRequest(prompt="Build an app"),
        release_status=ReleaseStatus.QUARANTINED,
        quarantine_preview_consumed=True,
    )

    with pytest.raises(RuntimeError, match="previewed only once"):
        PreviewManager(settings).start(job, project)


def test_docker_preview_command_uses_internal_network_and_hardening(tmp_path: Path) -> None:
    manager = PreviewManager(
        Settings(
            app_env="test",
            preview_cache_dir=tmp_path,
            preview_sandbox_mode="docker",
            preview_docker_network="test-quarantine",
        )
    )
    service = manager._service("job-12345678", "frontend", "frontend", 4100, ["npm"])

    command = manager._docker_command(
        "job-12345678",
        service,
        ["npm", "run", "dev"],
        {"PORT": "4100"},
        "test-image",
        is_node=True,
    )

    assert command[command.index("--network") + 1] == "test-quarantine"
    assert ["--cap-drop", "ALL"] == command[
        command.index("--cap-drop") : command.index("--cap-drop") + 2
    ]
    assert "no-new-privileges" in command
    assert "-v" not in command


def test_preview_proxy_builds_config_image_without_host_bind(tmp_path: Path, monkeypatch) -> None:
    manager = PreviewManager(
        Settings(
            app_env="test",
            preview_cache_dir=tmp_path,
            preview_sandbox_mode="docker",
            preview_docker_network="test-quarantine",
        )
    )
    service = manager._service("job-12345678", "frontend", "frontend", 4100, ["npm"])
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("software_developer_agent.sandbox.preview_manager.subprocess.run", fake_run)

    _, proxy_image = manager._start_preview_proxy("job-12345678", service, "generated-frontend")

    create_command = next(command for command in commands if command[:2] == ["docker", "create"])
    assert "-v" not in create_command
    assert any(command[:2] == ["docker", "build"] for command in commands)
    assert proxy_image in create_command
    dockerfile = tmp_path / "job-12345678" / "frontend-proxy-image" / "Dockerfile"
    assert "COPY default.conf" in dockerfile.read_text(encoding="utf-8")


def test_frontend_preview_proxy_routes_api_and_websockets_to_backend(tmp_path: Path) -> None:
    manager = PreviewManager(
        Settings(app_env="test", preview_cache_dir=tmp_path, preview_sandbox_mode="docker")
    )
    frontend = manager._service("job-12345678", "frontend", "frontend", 4100, ["npm"])
    backend = manager._service("job-12345678", "backend", "backend", 4101, ["python"])

    config = manager._preview_proxy_config(
        "job-12345678",
        frontend,
        "generated-frontend",
        backend_service=backend,
    )

    assert "location ^~ /api/" in config
    assert "location ^~ /ws/" in config
    assert "location ^~ /socket.io/" in config
    assert "proxy_pass http://agentic-forge-job-1234-backend:4101;" in config
    assert "proxy_pass http://generated-frontend:4100;" in config


def test_failed_runtime_check_downgrades_verified_release(tmp_path: Path) -> None:
    manager = PreviewManager(Settings(app_env="test", preview_cache_dir=tmp_path))
    job = JobState(
        request=JobRequest(prompt="Build an app"),
        release_status=ReleaseStatus.VERIFIED,
    )
    record = PreviewRecord(
        job_id=job.job_id,
        status="running",
        services=[],
        started_at=0,
        release_status=ReleaseStatus.VERIFIED.value,
        checks=[
            SimpleNamespace(name="browser_smoke", passed=False, message="Failed to fetch")
        ],
    )

    manager._apply_runtime_gate(job, record)

    assert job.release_status == ReleaseStatus.PROVISIONAL
    assert record.release_status == ReleaseStatus.PROVISIONAL.value
    assert "browser_smoke" in job.warnings[-1]


def test_node_preview_image_repairs_lock_without_running_generated_build(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = PreviewManager(
        Settings(
            app_env="test",
            preview_cache_dir=tmp_path / "cache",
            preview_sandbox_mode="docker",
        )
    )
    component = tmp_path / "frontend"
    component.mkdir()
    (component / "package.json").write_text("{}", encoding="utf-8")
    service = manager._service("job-12345678", "frontend", "frontend", 4100, ["npm"])
    monkeypatch.setattr(
        "software_developer_agent.sandbox.preview_manager.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        "software_developer_agent.sandbox.preview_manager.PreviewManager._ensure_docker_network",
        lambda self: None,
    )

    manager._build_docker_image("job-12345678", service, component)

    dockerfile = tmp_path / "cache" / "job-12345678" / "frontend-image" / "Dockerfile"
    content = dockerfile.read_text(encoding="utf-8")
    assert "npm install --package-lock-only --ignore-scripts" in content
    assert "npm ci --ignore-scripts" in content
    assert "npm run build" not in content


def test_preview_waits_for_http_not_just_the_docker_proxy_port(tmp_path, monkeypatch) -> None:
    manager = PreviewManager(Settings(app_env="test", preview_cache_dir=tmp_path))
    service = manager._service("readiness-test", "frontend", "frontend", 4100, ["npm"])
    record = PreviewRecord(
        job_id="readiness-test", status="starting", services=[service], started_at=0
    )
    process = SimpleNamespace(service=service, process=SimpleNamespace(poll=lambda: None))
    response = MagicMock()
    response.__enter__.return_value.status = 200
    response.__enter__.return_value.read.return_value = b"<"
    open_url = MagicMock(side_effect=[ConnectionResetError("proxy still starting"), response])
    monkeypatch.setattr(
        "software_developer_agent.sandbox.preview_manager.urllib.request.urlopen", open_url
    )
    monkeypatch.setattr(
        "software_developer_agent.sandbox.preview_manager.time.sleep", lambda _: None
    )

    manager._wait_until_ready(record, [process])

    assert open_url.call_count == 2
    assert record.status == "running"
    assert service.status == "running"
