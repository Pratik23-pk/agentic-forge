from __future__ import annotations

import atexit
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from software_developer_agent.capabilities.models import ProjectSpec
from software_developer_agent.capabilities.registry import resolve_project_spec
from software_developer_agent.config.settings import Settings, get_settings
from software_developer_agent.models.job_state import JobState, ReleaseStatus

ENVIRONMENT_REFERENCE_PATTERNS = (
    re.compile(r"os\.getenv\(\s*[\"']([A-Z][A-Z0-9_]*)[\"']"),
    re.compile(r"os\.environ(?:\.get)?\(\s*[\"']([A-Z][A-Z0-9_]*)[\"']"),
    re.compile(r"os\.environ\[\s*[\"']([A-Z][A-Z0-9_]*)[\"']\s*\]"),
    re.compile(r"import\.meta\.env\.([A-Z][A-Z0-9_]*)"),
    re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)"),
)


@dataclass(slots=True)
class RuntimeCheck:
    name: str
    passed: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PreviewService:
    name: str
    component: str
    port: int
    url: str
    status: str = "starting"
    pid: int | None = None
    log_path: str = ""
    command: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("command", None)
        return payload


@dataclass(slots=True)
class PreviewRecord:
    job_id: str
    status: str
    services: list[PreviewService]
    started_at: float
    stopped_at: float | None = None
    error: str | None = None
    sandbox_mode: str = "local"
    release_status: str = ReleaseStatus.PENDING.value
    quarantined: bool = False
    checks: list[RuntimeCheck] = field(default_factory=list)
    screenshot_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "services": [service.to_dict() for service in self.services],
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "error": self.error,
            "sandbox_mode": self.sandbox_mode,
            "release_status": self.release_status,
            "quarantined": self.quarantined,
            "checks": [check.to_dict() for check in self.checks],
            "screenshot_path": self.screenshot_path,
        }


@dataclass(slots=True)
class _ManagedProcess:
    service: PreviewService
    process: subprocess.Popen[bytes]
    resources: ExitStack
    docker_images: list[str] = field(default_factory=list)
    docker_containers: list[str] = field(default_factory=list)


class PreviewManager:
    """Starts validated projects with fixed commands and no inherited secrets."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._records: dict[str, PreviewRecord] = {}
        self._processes: dict[str, list[_ManagedProcess]] = {}
        self._lock = threading.RLock()

    def start(self, job: JobState, root: Path) -> PreviewRecord:
        if not self._settings.enable_live_preview:
            raise RuntimeError("Live previews are disabled by configuration.")
        if (
            self._settings.app_env == "production"
            and self._settings.preview_sandbox_mode == "local"
        ):
            raise RuntimeError("Production previews require PREVIEW_SANDBOX_MODE=docker.")
        if (
            job.release_status == ReleaseStatus.QUARANTINED
            and self._settings.preview_sandbox_mode != "docker"
        ):
            raise RuntimeError("Quarantined builds require Docker preview isolation.")
        root = root.resolve()
        generated_root = self._settings.generated_projects_dir.resolve()
        if generated_root not in root.parents:
            raise ValueError("Preview root must be a generated project directory.")

        with self._lock:
            existing = self._records.get(job.job_id)
            if job.release_status == ReleaseStatus.QUARANTINED and job.quarantine_preview_consumed:
                if existing is not None and existing.status == "running":
                    return existing
                raise RuntimeError("A quarantined build may be previewed only once.")
            self.stop(job.job_id)
            spec = (
                ProjectSpec.from_dict(job.project_spec)
                if job.project_spec
                else resolve_project_spec(job.request.prompt, job.request.metadata)
            )
            definitions = self._service_definitions(job.job_id, root, spec)
            if not definitions:
                raise RuntimeError("This generated project has no previewable web service.")

            record = PreviewRecord(
                job_id=job.job_id,
                status="starting",
                services=[definition[0] for definition in definitions],
                started_at=time.time(),
                sandbox_mode=self._settings.preview_sandbox_mode,
                release_status=job.release_status.value,
                quarantined=job.release_status == ReleaseStatus.QUARANTINED,
            )
            self._records[job.job_id] = record
            managed: list[_ManagedProcess] = []
            self._processes[job.job_id] = managed
            try:
                for service, component_root, command, environment in definitions:
                    docker_image = self._prepare_component(
                        job.job_id,
                        service,
                        component_root,
                    )
                    try:
                        process = self._spawn(
                            job.job_id,
                            service,
                            component_root,
                            command,
                            environment,
                            docker_image=docker_image,
                            backend_service=next(
                                (
                                    item.service
                                    for item in managed
                                    if item.service.name == "backend"
                                ),
                                None,
                            ),
                        )
                    except Exception:
                        if docker_image:
                            subprocess.run(
                                ["docker", "image", "rm", "--force", docker_image],
                                capture_output=True,
                                check=False,
                            )
                        raise
                    managed.append(process)
                self._wait_until_ready(record, managed)
                self._run_runtime_checks(record)
                self._apply_runtime_gate(job, record)
                if (
                    job.release_status == ReleaseStatus.QUARANTINED
                    and record.checks
                    and all(check.passed for check in record.checks)
                ):
                    job.quarantine_preview_consumed = True
                    job.touch()
            except Exception as exc:
                record.status = "failed"
                record.error = str(exc)
                self._stop_processes(managed)
                raise RuntimeError(str(exc)) from exc
            return record

    def get(self, job_id: str) -> PreviewRecord | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is not None and record.status == "running":
                managed = self._processes.get(job_id, [])
                if any(item.process.poll() is not None for item in managed):
                    record.status = "failed"
                    record.error = "A preview process exited unexpectedly. Inspect preview logs."
                    for service, item in zip(record.services, managed, strict=False):
                        service.status = "failed" if item.process.poll() is not None else "running"
            return record

    def stop(self, job_id: str) -> PreviewRecord | None:
        with self._lock:
            managed = self._processes.pop(job_id, [])
            self._stop_processes(managed)
            record = self._records.get(job_id)
            if record is not None and record.status != "failed":
                record.status = "stopped"
                record.stopped_at = time.time()
                for service in record.services:
                    service.status = "stopped"
            return record

    def stop_all(self) -> None:
        with self._lock:
            for job_id in list(self._processes):
                self.stop(job_id)

    def logs(self, job_id: str, service_name: str | None = None, limit: int = 30_000) -> str:
        record = self.get(job_id)
        if record is None:
            raise KeyError(job_id)
        selected = [
            service
            for service in record.services
            if service_name is None or service.name == service_name
        ]
        if not selected:
            raise KeyError(service_name or "")
        chunks: list[str] = []
        for service in selected:
            path = Path(service.log_path)
            content = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
            chunks.append(f"[{service.name}]\n{content[-limit:]}")
        return "\n\n".join(chunks)

    def _service_definitions(
        self,
        job_id: str,
        root: Path,
        spec: ProjectSpec,
    ) -> list[tuple[PreviewService, Path, list[str], dict[str, str]]]:
        definitions: list[tuple[PreviewService, Path, list[str], dict[str, str]]] = []
        bind_host = (
            "0.0.0.0"
            if self._settings.preview_sandbox_mode == "docker"
            else self._settings.preview_host
        )
        preferred_backend = spec.ports.get("backend", 8000)
        preferred_frontend = spec.ports.get("frontend", spec.ports.get("application", 3000))
        backend_url = ""

        backend = root / "backend"
        if backend.exists() and spec.backend_framework not in {None, "Python CLI"}:
            port = self._available_port(preferred_backend)
            backend_url = f"http://{self._settings.preview_host}:{port}"
            environment = {**_preview_backend_environment(backend), "PORT": str(port)}
            if (backend / "package.json").exists():
                command = [_npm_executable(), "run", "dev"]
            else:
                command = [
                    (
                        "python"
                        if self._settings.preview_sandbox_mode == "docker"
                        else str(self._preview_python(job_id, backend))
                    ),
                    "-m",
                    "uvicorn",
                    f"{_backend_module(backend)}:app",
                    "--host",
                    bind_host,
                    "--port",
                    str(port),
                ]
            definitions.append(
                (
                    self._service(job_id, "backend", "backend", port, command),
                    backend,
                    command,
                    environment,
                )
            )

        frontend = root / "frontend"
        if frontend.exists():
            port = self._available_port(
                preferred_frontend,
                reserved={item[0].port for item in definitions},
            )
            is_next = spec.frontend_framework == "Next.js"
            host_flag = "--hostname" if is_next else "--host"
            command = [
                _npm_executable(),
                "run",
                "dev",
                "--",
                host_flag,
                bind_host,
                "--port",
                str(port),
            ]
            frontend_url = f"http://{self._settings.preview_host}:{port}"
            public_api_base = (
                frontend_url
                if backend_url and self._settings.preview_sandbox_mode == "docker"
                else backend_url
            )
            environment = {
                "PORT": str(port),
                "VITE_API_BASE_URL": public_api_base,
                "NEXT_PUBLIC_API_BASE_URL": public_api_base,
            }
            if definitions and backend_url:
                frontend_origins = {
                    f"http://{self._settings.preview_host}:{port}",
                    f"http://localhost:{port}",
                }
                definitions[0][3]["CORS_ORIGINS"] = ",".join(sorted(frontend_origins))
            definitions.append(
                (
                    self._service(job_id, "frontend", "frontend", port, command),
                    frontend,
                    command,
                    environment,
                )
            )
        return definitions

    def _service(
        self,
        job_id: str,
        name: str,
        component: str,
        port: int,
        command: list[str],
    ) -> PreviewService:
        log_dir = self._settings.preview_cache_dir / job_id
        return PreviewService(
            name=name,
            component=component,
            port=port,
            url=f"http://{self._settings.preview_host}:{port}",
            log_path=str(log_dir / f"{name}.log"),
            command=command,
        )

    def _prepare_component(
        self,
        job_id: str,
        service: PreviewService,
        component: Path,
    ) -> str | None:
        if self._settings.preview_sandbox_mode == "docker":
            return self._build_docker_image(job_id, service, component)
        if (component / "package.json").exists():
            if not (component / "node_modules").exists():
                self._run_install(
                    [_npm_executable(), "ci", "--ignore-scripts", "--no-audit"],
                    component,
                )
            return None
        if (component / "pyproject.toml").exists() or (component / "requirements.txt").exists():
            python = self._preview_python(job_id, component)
            if (Path(python).parent / ".ready").exists():
                return
            if (component / "pyproject.toml").exists():
                command = [
                    _uv_executable(),
                    "sync",
                    "--locked",
                    "--no-dev",
                    "--no-editable",
                    "--project",
                    str(component),
                ]
                environment = {"UV_PROJECT_ENVIRONMENT": str(Path(python).parent.parent)}
            else:
                command = [
                    _uv_executable(),
                    "pip",
                    "install",
                    "--python",
                    str(python),
                    "-r",
                    str(component / "requirements.txt"),
                ]
                environment = None
            self._run_install(command, component, environment)
            (Path(python).parent / ".ready").touch()
        return None

    def _build_docker_image(
        self,
        job_id: str,
        service: PreviewService,
        component: Path,
    ) -> str:
        if shutil.which("docker") is None:
            raise RuntimeError("Docker sandbox mode is enabled but Docker is unavailable.")
        self._ensure_docker_network()
        image = f"agentic-forge-preview:{job_id[:8]}-{service.name}"
        build_dir = self._settings.preview_cache_dir / job_id / f"{service.name}-image"
        build_dir.mkdir(parents=True, exist_ok=True)
        dockerfile = build_dir / "Dockerfile"
        if (component / "package.json").exists():
            content = (
                "FROM node:20-alpine\n"
                "WORKDIR /workspace\n"
                "COPY --chown=node:node package*.json /workspace/\n"
                "RUN npm install --package-lock-only --ignore-scripts --no-audit "
                "&& npm ci --ignore-scripts --no-audit\n"
                "COPY --chown=node:node . /workspace\n"
                "RUN mkdir -p /workspace/node_modules/.vite "
                "/workspace/node_modules/.vite-temp /workspace/.next "
                "&& chown -R node:node /workspace/node_modules/.vite "
                "/workspace/node_modules/.vite-temp /workspace/.next\n"
                "USER node\n"
            )
        elif (component / "pyproject.toml").exists():
            content = (
                "FROM ghcr.io/astral-sh/uv:0.12.18-debian-slim\n"
                "WORKDIR /workspace\n"
                "ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy "
                "UV_PYTHON_INSTALL_DIR=/opt/uv/python UV_PROJECT_ENVIRONMENT=/opt/venv "
                "PATH=/opt/venv/bin:$PATH\n"
                "COPY pyproject.toml uv.lock .python-version /workspace/\n"
                "RUN uv sync --locked --no-dev --no-install-project --no-editable\n"
                "COPY . /workspace\n"
                "RUN uv sync --locked --no-dev --no-editable "
                "&& chmod -R a+rX /opt/uv /opt/venv\n"
                "USER 65534:65534\n"
            )
        else:
            content = (
                "FROM ghcr.io/astral-sh/uv:0.12.18-debian-slim\n"
                "WORKDIR /workspace\n"
                "ENV UV_LINK_MODE=copy PATH=/opt/venv/bin:$PATH\n"
                "COPY . /workspace\n"
                "RUN uv venv /opt/venv --python 3.11 && "
                "uv pip install --python /opt/venv/bin/python "
                "-r requirements.txt\n"
                "USER 65534:65534\n"
            )
        dockerfile.write_text(content, encoding="utf-8")
        result = subprocess.run(
            [
                "docker",
                "build",
                "--pull",
                "--network",
                "bridge",
                "--file",
                str(dockerfile),
                "--tag",
                image,
                str(component),
            ],
            env=self._safe_environment(),
            capture_output=True,
            text=True,
            timeout=self._settings.preview_install_timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            detail = "\n".join(
                output.strip() for output in (result.stdout, result.stderr) if output.strip()
            )[-4_000:]
            raise RuntimeError(f"Docker preview image build failed: {detail}")
        return image

    def _ensure_docker_network(self) -> None:
        network = self._settings.preview_docker_network
        inspected = subprocess.run(
            ["docker", "network", "inspect", network],
            capture_output=True,
            text=True,
            check=False,
        )
        if inspected.returncode == 0:
            return
        created = subprocess.run(
            ["docker", "network", "create", "--internal", network],
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode != 0:
            detail = (created.stderr or created.stdout)[-1_000:]
            raise RuntimeError(f"Unable to create Docker quarantine network: {detail}")

    def _preview_python(self, job_id: str, component: Path) -> Path:
        venv = self._settings.preview_cache_dir / job_id / "python-venv"
        python = venv / "bin" / "python"
        if sys.platform == "win32":
            python = venv / "Scripts" / "python.exe"
        if not python.exists():
            venv.parent.mkdir(parents=True, exist_ok=True)
            self._run_install(
                [_uv_executable(), "venv", str(venv), "--python", sys.executable],
                component,
            )
        return python

    def _run_install(
        self,
        command: list[str],
        cwd: Path,
        environment: dict[str, str] | None = None,
    ) -> None:
        safe_environment = self._safe_environment()
        safe_environment.update(environment or {})
        result = subprocess.run(
            command,
            cwd=cwd,
            env=safe_environment,
            capture_output=True,
            text=True,
            timeout=self._settings.preview_install_timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout)[-2_000:]
            raise RuntimeError(f"Preview dependency preparation failed: {detail}")

    def _spawn(
        self,
        job_id: str,
        service: PreviewService,
        component: Path,
        command: list[str],
        environment: dict[str, str],
        *,
        docker_image: str | None = None,
        backend_service: PreviewService | None = None,
    ) -> _ManagedProcess:
        Path(service.log_path).parent.mkdir(parents=True, exist_ok=True)
        resources = ExitStack()
        log_handle = resources.enter_context(
            Path(service.log_path).open("wb")  # noqa: SIM115 - closed by ExitStack
        )
        safe_environment = self._safe_environment()
        safe_environment.update(environment)
        if self._settings.preview_sandbox_mode == "docker":
            if docker_image is None:
                raise RuntimeError("Docker preview image was not prepared.")
            process_command = self._docker_command(
                job_id,
                service,
                command,
                environment,
                docker_image,
                is_node=(component / "package.json").exists(),
            )
            process_cwd = component.parent
        else:
            process_command = command
            process_cwd = component
        process = subprocess.Popen(
            process_command,
            cwd=process_cwd,
            env=safe_environment,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        service.pid = process.pid
        docker_containers: list[str] = []
        proxy_image: str | None = None
        if docker_image is not None:
            application_container = self._application_container_name(job_id, service)
            try:
                self._wait_for_container(application_container, process)
                proxy_container, proxy_image = self._start_preview_proxy(
                    job_id,
                    service,
                    application_container,
                    backend_service=backend_service,
                )
                docker_containers = [application_container, proxy_container]
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    process.terminate()
                subprocess.run(
                    ["docker", "rm", "--force", application_container],
                    capture_output=True,
                    check=False,
                )
                resources.close()
                raise
        return _ManagedProcess(
            service=service,
            process=process,
            resources=resources,
            docker_images=[image for image in (docker_image, proxy_image) if image],
            docker_containers=docker_containers,
        )

    @staticmethod
    def _application_container_name(job_id: str, service: PreviewService) -> str:
        return f"agentic-forge-{job_id[:8]}-{service.name}"

    def _start_preview_proxy(
        self,
        job_id: str,
        service: PreviewService,
        application_container: str,
        *,
        backend_service: PreviewService | None = None,
    ) -> tuple[str, str]:
        proxy_container = f"agentic-forge-{job_id[:8]}-{service.name}-proxy"
        build_dir = self._settings.preview_cache_dir / job_id / f"{service.name}-proxy-image"
        build_dir.mkdir(parents=True, exist_ok=True)
        config = build_dir / "default.conf"
        config.write_text(
            self._preview_proxy_config(
                job_id,
                service,
                application_container,
                backend_service=backend_service,
            ),
            encoding="utf-8",
        )
        dockerfile = build_dir / "Dockerfile"
        dockerfile.write_text(
            "FROM nginxinc/nginx-unprivileged:1.27-alpine\n"
            "COPY default.conf /etc/nginx/conf.d/default.conf\n",
            encoding="utf-8",
        )
        proxy_image = f"agentic-forge-preview:{job_id[:8]}-{service.name}-proxy"
        built = subprocess.run(
            [
                "docker",
                "build",
                "--pull",
                "--network",
                "bridge",
                "--file",
                str(dockerfile),
                "--tag",
                proxy_image,
                str(build_dir),
            ],
            capture_output=True,
            text=True,
            timeout=self._settings.preview_install_timeout_seconds,
            check=False,
        )
        if built.returncode != 0:
            raise RuntimeError(
                "Preview proxy image build failed: " + (built.stderr or built.stdout)[-1_500:]
            )
        create_command = [
            "docker",
            "create",
            "--name",
            proxy_container,
            "--network",
            "bridge",
            "--cpus",
            "0.25",
            "--memory",
            "128m",
            "--pids-limit",
            "64",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=32m",
            "--tmpfs",
            "/var/cache/nginx:rw,nosuid,nodev,size=32m,uid=101,gid=101",
            "--tmpfs",
            "/var/run:rw,nosuid,nodev,size=8m,uid=101,gid=101",
            "-p",
            f"{self._settings.preview_host}:{service.port}:8080",
            proxy_image,
        ]
        created = subprocess.run(
            create_command,
            capture_output=True,
            text=True,
            timeout=self._settings.preview_install_timeout_seconds,
            check=False,
        )
        if created.returncode != 0:
            subprocess.run(
                ["docker", "image", "rm", "--force", proxy_image],
                capture_output=True,
                check=False,
            )
            raise RuntimeError(
                "Preview proxy creation failed: " + (created.stderr or created.stdout)[-1_500:]
            )
        for command in (
            [
                "docker",
                "network",
                "connect",
                self._settings.preview_docker_network,
                proxy_container,
            ],
            ["docker", "start", proxy_container],
        ):
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self._settings.preview_startup_timeout_seconds,
                check=False,
            )
            if result.returncode != 0:
                subprocess.run(
                    ["docker", "rm", "--force", proxy_container],
                    capture_output=True,
                    check=False,
                )
                subprocess.run(
                    ["docker", "image", "rm", "--force", proxy_image],
                    capture_output=True,
                    check=False,
                )
                raise RuntimeError(
                    "Preview proxy startup failed: " + (result.stderr or result.stdout)[-1_500:]
                )
        return proxy_container, proxy_image

    def _preview_proxy_config(
        self,
        job_id: str,
        service: PreviewService,
        application_container: str,
        *,
        backend_service: PreviewService | None = None,
    ) -> str:
        locations: list[str] = []
        if service.name == "frontend" and backend_service is not None:
            backend_container = self._application_container_name(job_id, backend_service)
            backend_target = f"http://{backend_container}:{backend_service.port}"
            for route in ("= /api", "^~ /api/", "= /ws", "^~ /ws/", "^~ /socket.io/"):
                locations.append(
                    f"  location {route} {{\n"
                    f"    proxy_pass {backend_target};\n"
                    "    proxy_http_version 1.1;\n"
                    "    proxy_set_header Host $host;\n"
                    "    proxy_set_header X-Forwarded-Host $host;\n"
                    "    proxy_set_header X-Forwarded-Proto $scheme;\n"
                    "    proxy_set_header Upgrade $http_upgrade;\n"
                    '    proxy_set_header Connection "upgrade";\n'
                    "  }\n"
                )
        locations.append(
            "  location / {\n"
            f"    proxy_pass http://{application_container}:{service.port};\n"
            "    proxy_http_version 1.1;\n"
            "    proxy_set_header Host $host;\n"
            "    proxy_set_header Upgrade $http_upgrade;\n"
            '    proxy_set_header Connection "upgrade";\n'
            "  }\n"
        )
        return "server {\n  listen 8080;\n" + "".join(locations) + "}\n"

    def _wait_for_container(
        self,
        container: str,
        process: subprocess.Popen[bytes],
    ) -> None:
        deadline = time.monotonic() + min(self._settings.preview_startup_timeout_seconds, 15)
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Preview application container exited before proxy startup.")
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Running}}", container],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip() == "true":
                return
            time.sleep(0.1)
        raise RuntimeError("Preview application container did not become ready for proxying.")

    def _docker_command(
        self,
        job_id: str,
        service: PreviewService,
        command: list[str],
        environment: dict[str, str],
        image: str,
        *,
        is_node: bool,
    ) -> list[str]:
        command_text = " ".join(_shell_quote(part) for part in command)
        docker = [
            "docker",
            "run",
            "--rm",
            "--name",
            self._application_container_name(job_id, service),
            "--init",
            "--network",
            self._settings.preview_docker_network,
            "--cpus",
            "1.0",
            "--memory",
            f"{self._settings.preview_memory_limit_mb}m",
            "--pids-limit",
            "128",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,exec,size=256m",
        ]
        if is_node:
            docker.extend(
                [
                    "--tmpfs",
                    "/workspace/node_modules/.vite:rw,nosuid,nodev,exec,size=64m,uid=1000,gid=1000,mode=0770",
                    "--tmpfs",
                    "/workspace/node_modules/.vite-temp:rw,nosuid,nodev,exec,size=64m,uid=1000,gid=1000,mode=0770",
                    "--tmpfs",
                    "/workspace/.next:rw,nosuid,nodev,exec,size=256m,uid=1000,gid=1000,mode=0770",
                ]
            )
        else:
            docker.extend(["--workdir", "/tmp/runtime"])
        docker.extend(["-e", "PYTHONDONTWRITEBYTECODE=1"])
        if not is_node and "PYTHONPATH" not in environment:
            docker.extend(["-e", "PYTHONPATH=/workspace/src:/workspace"])
        for key, value in environment.items():
            docker.extend(["-e", f"{key}={value}"])
        docker.extend(
            [
                image,
                "sh",
                "-c",
                command_text,
            ]
        )
        return docker

    def _run_runtime_checks(self, record: PreviewRecord) -> None:
        primary = next(
            (service for service in record.services if service.name == "frontend"),
            record.services[0],
        )
        try:
            with urllib.request.urlopen(primary.url, timeout=5) as response:
                status = int(response.status)
                body = response.read(2_000)
            record.checks.append(
                RuntimeCheck(
                    name="http_smoke",
                    passed=200 <= status < 500 and bool(body),
                    message=f"{primary.name} returned HTTP {status} with a response body.",
                )
            )
        except (OSError, urllib.error.URLError) as exc:
            record.checks.append(RuntimeCheck(name="http_smoke", passed=False, message=str(exc)))
        self._run_playwright_check(record, primary)

    @staticmethod
    def _apply_runtime_gate(job: JobState, record: PreviewRecord) -> None:
        failed = [check for check in record.checks if not check.passed]
        if not failed or job.release_status == ReleaseStatus.QUARANTINED:
            record.release_status = job.release_status.value
            return
        job.release_status = ReleaseStatus.PROVISIONAL
        record.release_status = ReleaseStatus.PROVISIONAL.value
        message = (
            "Runtime preview verification failed; publication is locked until these checks pass: "
            + ", ".join(check.name for check in failed)
            + "."
        )
        if message not in job.warnings:
            job.warnings.append(message)
        job.touch()

    def _run_playwright_check(
        self,
        record: PreviewRecord,
        primary: PreviewService,
    ) -> None:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError:
            record.checks.append(
                RuntimeCheck(
                    name="browser_smoke",
                    passed=False,
                    message="Playwright is not installed; HTTP smoke check was used.",
                )
            )
            return
        screenshot = self._settings.preview_cache_dir / record.job_id / "runtime-preview.png"
        page_errors: list[str] = []
        screenshot_error: str | None = None
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                response = page.goto(
                    primary.url,
                    wait_until="domcontentloaded",
                    timeout=self._settings.preview_startup_timeout_seconds * 1_000,
                )
                page.wait_for_timeout(750)
                body = page.locator("body").inner_text().strip()
                try:
                    page.screenshot(path=str(screenshot), full_page=True)
                except (OSError, PlaywrightError, PlaywrightTimeoutError) as exc:
                    screenshot_error = str(exc)
                else:
                    record.screenshot_path = str(screenshot)
                browser.close()
            failure_marker = _preview_failure_marker(body)
            passed = (
                response is not None
                and response.status < 500
                and bool(body)
                and not page_errors
                and failure_marker is None
            )
            message = (
                "Headless browser rendered visible content without page errors."
                if passed
                else "; ".join(page_errors[:3])
                or (
                    f"Rendered application reported {failure_marker!r}."
                    if failure_marker
                    else "Browser response was incomplete."
                )
            )
            if screenshot_error:
                message += f" Screenshot capture was unavailable: {screenshot_error}"
            record.checks.append(
                RuntimeCheck(
                    name="browser_smoke",
                    passed=passed,
                    message=message,
                )
            )
        except (OSError, PlaywrightError, PlaywrightTimeoutError) as exc:
            record.checks.append(RuntimeCheck(name="browser_smoke", passed=False, message=str(exc)))

    def _wait_until_ready(
        self,
        record: PreviewRecord,
        managed: list[_ManagedProcess],
    ) -> None:
        deadline = time.monotonic() + self._settings.preview_startup_timeout_seconds
        pending = list(managed)
        while pending and time.monotonic() < deadline:
            for item in list(pending):
                if item.process.poll() is not None:
                    raise RuntimeError(
                        f"{item.service.name.title()} preview exited during startup. "
                        "Inspect the preview logs."
                    )
                if _http_is_ready(item.service.url, allow_not_found=item.service.name == "backend"):
                    item.service.status = "running"
                    pending.remove(item)
            if pending:
                time.sleep(0.2)
        if pending:
            names = ", ".join(item.service.name for item in pending)
            raise RuntimeError(f"Preview startup timed out for: {names}.")
        record.status = "running"

    def _stop_processes(self, managed: list[_ManagedProcess]) -> None:
        for item in managed:
            if item.process.poll() is None:
                try:
                    os.killpg(item.process.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    item.process.terminate()
        deadline = time.monotonic() + 3
        for item in managed:
            while item.process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            if item.process.poll() is None:
                try:
                    os.killpg(item.process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    item.process.kill()
            item.resources.close()
            for container in reversed(item.docker_containers):
                subprocess.run(
                    ["docker", "rm", "--force", container],
                    capture_output=True,
                    check=False,
                )
            for image in reversed(item.docker_images):
                subprocess.run(
                    ["docker", "image", "rm", "--force", image],
                    capture_output=True,
                    check=False,
                )

    def _available_port(self, preferred: int, reserved: set[int] | None = None) -> int:
        reserved = reserved or set()
        candidates = [
            preferred,
            *range(self._settings.preview_port_start, self._settings.preview_port_end + 1),
        ]
        for port in dict.fromkeys(candidates):
            if port in reserved:
                continue
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    probe.bind((self._settings.preview_host, port))
                except OSError:
                    continue
                return port
        raise RuntimeError("No preview port is available in the configured range.")

    def _safe_environment(self) -> dict[str, str]:
        return {
            key: value
            for key, value in os.environ.items()
            if key in {"HOME", "LANG", "LC_ALL", "PATH", "SYSTEMROOT", "TMPDIR"}
        } | {
            "CI": "1",
            "NODE_ENV": "development",
            "PYTHONDONTWRITEBYTECODE": "1",
            "UV_LINK_MODE": "copy",
            "UV_NO_PROGRESS": "1",
        }


def _backend_module(backend: Path) -> str:
    if (backend / "src" / "app" / "main.py").exists() or (backend / "app" / "main.py").exists():
        return "app.main"
    if (backend / "main.py").exists():
        return "main"
    return "app.main"


def _npm_executable() -> str:
    return "npm.cmd" if sys.platform == "win32" else "npm"


def _uv_executable() -> str:
    uv = shutil.which("uv")
    if uv:
        return uv
    for candidate in (
        Path.home() / ".local" / "bin" / "uv",
        Path("/opt/homebrew/bin/uv"),
        Path("/usr/local/bin/uv"),
    ):
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("uv is required for Python preview environments.")


def _preview_backend_environment(backend: Path) -> dict[str, str]:
    names = _preview_environment_names(backend)
    values: dict[str, str] = {}
    for name in names:
        upper = name.upper()
        if upper == "DATABASE_URL":
            values[name] = "sqlite+pysqlite:////tmp/agentic-forge-preview.db"
        elif upper in {"UPLOAD_DIR", "MEDIA_DIR", "MEDIA_ROOT", "STORAGE_DIR", "CACHE_DIR"}:
            values[name] = "/tmp/agentic-forge-media"
        elif upper.endswith(("_URL", "_ORIGIN")):
            values[name] = "http://127.0.0.1:9"
        elif any(marker in upper for marker in ("KEY", "PASSWORD", "SECRET", "TOKEN")):
            values[name] = "preview-only-not-a-real-secret-0123456789abcdef0123456789abcdef"
        elif any(
            marker in upper
            for marker in (
                "_COUNT",
                "_DAYS",
                "_HOURS",
                "_LIMIT",
                "_MAX",
                "_MINUTES",
                "_PORT",
                "_SECONDS",
                "_SIZE",
                "_TIMEOUT",
                "_TTL",
            )
        ):
            values[name] = "1"
        elif upper.startswith(("ENABLE_", "IS_")) or upper.endswith(("_ENABLED", "_SECURE")):
            values[name] = "false"
        else:
            values[name] = "preview"
    return values


def _preview_environment_names(backend: Path) -> set[str]:
    names: set[str] = set()
    env_example = backend / ".env.example"
    if env_example.exists():
        names.update(
            line.split("=", maxsplit=1)[0].strip()
            for line in env_example.read_text(encoding="utf-8", errors="replace").splitlines()
            if "=" in line
            and line.split("=", maxsplit=1)[0].strip()
            and not line.lstrip().startswith("#")
        )
    runtime_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in backend.rglob("*")
        if path.is_file()
        and path.stat().st_size <= 300_000
        and path.suffix.lower() in {".py", ".js", ".ts", ".mjs", ".cjs"}
        and "test" not in path.relative_to(backend).parts
        and "tests" not in path.relative_to(backend).parts
    )
    for pattern in ENVIRONMENT_REFERENCE_PATTERNS:
        names.update(pattern.findall(runtime_text))
    if re.search(r"sqlite(?:\+pysqlite)?:///", runtime_text, re.IGNORECASE):
        names.add("DATABASE_URL")
    for storage_name in ("UPLOAD_DIR", "MEDIA_DIR", "MEDIA_ROOT", "STORAGE_DIR", "CACHE_DIR"):
        if re.search(rf"\b{storage_name}\b", runtime_text):
            names.add(storage_name)
    return names


def _http_is_ready(url: str, *, allow_not_found: bool = False) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return 200 <= response.status < 400 and bool(response.read(1))
    except urllib.error.HTTPError as exc:
        return allow_not_found and exc.code == 404
    except (OSError, urllib.error.URLError):
        return False


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _preview_failure_marker(body: str) -> str | None:
    normalized = body.casefold()
    return next(
        (
            marker
            for marker in (
                "failed to fetch",
                "connection interrupted",
                "could not open your",
                "unable to reach",
                "application error",
                "internal server error",
            )
            if marker in normalized
        ),
        None,
    )


@lru_cache
def get_preview_manager() -> PreviewManager:
    manager = PreviewManager(get_settings())
    atexit.register(manager.stop_all)
    return manager
