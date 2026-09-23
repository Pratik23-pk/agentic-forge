from __future__ import annotations

import json
import re
import shutil
import tempfile
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from textwrap import dedent
from typing import Any

from software_developer_agent.artifacts.file_manifest import (
    ManifestConflictError,
    collect_worker_file_manifests,
    collect_worker_file_specs,
    extract_worker_file_manifest,
    fallback_worker_manifest_json,
    merge_file_specs,
    validate_worker_manifest_scope,
)
from software_developer_agent.artifacts.validation import (
    ArtifactValidationError,
    ProjectValidationReport,
    ProjectValidator,
)
from software_developer_agent.capabilities.models import ProjectSpec
from software_developer_agent.capabilities.registry import resolve_project_spec
from software_developer_agent.config.settings import Settings
from software_developer_agent.guardrails.release_policy import decide_release
from software_developer_agent.models.job_state import (
    JobArtifact,
    JobState,
    ReleaseStatus,
    WorkerKind,
)
from software_developer_agent.models.request_policy import RequestPolicy, derive_request_policy
from software_developer_agent.prompts.system_prompts import ARTIFACT_WRITER_SYSTEM_PROMPT


@dataclass(slots=True)
class GeneratedProject:
    root_dir: Path
    zip_path: Path
    file_count: int
    source: str
    file_paths: list[str]
    validation: ProjectValidationReport
    release_status: ReleaseStatus
    risk_findings: list[dict[str, object]]


class ProjectArtifactGenerator:
    """Assembles, validates, and publishes a generated project atomically."""

    system_prompt = ARTIFACT_WRITER_SYSTEM_PROMPT

    def __init__(
        self,
        settings: Settings,
        validator: ProjectValidator | None = None,
    ) -> None:
        self._settings = settings
        self._validator = validator or ProjectValidator(settings)

    def generate(self, job: JobState) -> list[JobArtifact]:
        project = self._build_project(job)
        metadata = {
            "file_count": project.file_count,
            "source": project.source,
            "files": project.file_paths,
            "validation": project.validation.to_dict(),
            "validation_commands": [result.command for result in project.validation.results],
            "release_status": project.release_status.value,
            "publish_allowed": project.release_status == ReleaseStatus.VERIFIED,
            "risk_findings": project.risk_findings,
        }
        return [
            JobArtifact(
                artifact_id="project-folder",
                kind="folder",
                name=project.root_dir.name,
                path=str(project.root_dir),
                url=f"/api/jobs/{job.job_id}/files",
                metadata=metadata,
            ),
            JobArtifact(
                artifact_id="project-zip",
                kind="zip",
                name=project.zip_path.name,
                path=str(project.zip_path),
                url=f"/api/jobs/{job.job_id}/download",
                metadata=metadata,
            ),
        ]

    def _build_project(self, job: JobState) -> GeneratedProject:
        slug = _slugify(job.request.project_id or job.request.prompt)
        name = f"{slug}-{job.job_id[:8]}"
        root_dir = self._settings.generated_projects_dir / name
        staging_dir = self._settings.generated_projects_dir / f".staging-{name}"
        zip_path = self._settings.artifacts_dir / f"{name}.zip"
        staging_zip = self._settings.artifacts_dir / f".staging-{name}.zip"
        files, source = _project_files(job)

        self._settings.generated_projects_dir.mkdir(parents=True, exist_ok=True)
        self._settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
        _remove_path(staging_dir)
        _remove_path(staging_zip)
        staging_dir.mkdir(parents=True)

        try:
            for relative_path, content in files.items():
                destination = staging_dir / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")

            try:
                validation = self._validator.validate(staging_dir, job)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                validation = ProjectValidationReport(
                    passed=False,
                    release_ready=False,
                    checks=["validator_runtime:failed"],
                    # Not "infrastructure": an unavailable sandbox is a warning the job
                    # may pass through, but a crash inside the validator proves nothing
                    # about the project and must never be upgraded to a pass.
                    failure_kind="internal",
                    failure_reason=f"Validation runtime failed: {type(exc).__name__}: {exc}",
                )
            job.validation_results = [result.to_dict() for result in validation.results]
            release = decide_release(
                job,
                validation_passed=validation.passed and validation.release_ready,
                validation_reason=(
                    validation.failure_reason or _validation_release_reason(validation)
                ),
            )
            job.release_status = release.status
            job.risk_findings = release.findings
            risk_report = {
                "release_status": release.status.value,
                "publish_allowed": release.can_publish,
                "preview_isolation_required": release.requires_isolated_preview,
                "validation": validation.to_dict(),
                "findings": release.findings,
            }
            risk_report_path = staging_dir / "artifacts" / "risk-report.json"
            risk_report_path.parent.mkdir(parents=True, exist_ok=True)
            risk_report_path.write_text(
                json.dumps(risk_report, indent=2) + "\n",
                encoding="utf-8",
            )

            published_file_paths = sorted(
                path.relative_to(staging_dir).as_posix()
                for path in staging_dir.rglob("*")
                if path.is_file()
            )
            _write_zip(staging_dir, staging_zip)
            _verify_zip_parity(staging_dir, staging_zip)

            _remove_path(root_dir)
            _remove_path(zip_path)
            staging_dir.replace(root_dir)
            staging_zip.replace(zip_path)
        except Exception:
            _remove_path(staging_dir)
            _remove_path(staging_zip)
            raise

        return GeneratedProject(
            root_dir=root_dir,
            zip_path=zip_path,
            file_count=len(published_file_paths),
            source=source,
            file_paths=published_file_paths,
            validation=validation,
            release_status=release.status,
            risk_findings=release.findings,
        )


def refresh_artifact_release_report(job: JobState, settings: Settings) -> None:
    folder = next((artifact for artifact in job.artifacts if artifact.kind == "folder"), None)
    if folder is None or not Path(folder.path).is_dir():
        return
    root = Path(folder.path).resolve()
    if settings.generated_projects_dir.resolve() not in root.parents:
        raise ValueError("Release report must belong to a generated project.")
    report_path = root / "artifacts" / "risk-report.json"
    if not report_path.resolve().is_relative_to(root):
        raise ValueError("Release report path escapes the generated project.")
    payload = {
        "release_status": job.release_status.value,
        "publish_allowed": job.release_status == ReleaseStatus.VERIFIED,
        "preview_isolation_required": job.release_status == ReleaseStatus.QUARANTINED,
        "validation": folder.metadata.get("validation", {}),
        "findings": job.risk_findings,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".release-", dir=root.parent) as temp_dir:
        staged_report = Path(temp_dir) / "risk-report.json"
        staged_report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        staged_report.replace(report_path)
    for artifact in job.artifacts:
        if artifact.kind != "zip":
            continue
        zip_path = Path(artifact.path).resolve()
        if settings.artifacts_dir.resolve() not in zip_path.parents:
            raise ValueError("Release archive must belong to the artifact directory.")
        with tempfile.TemporaryDirectory(prefix=".release-", dir=zip_path.parent) as temp_dir:
            staged_zip = Path(temp_dir) / "project.zip"
            _write_zip(root, staged_zip)
            _verify_zip_parity(root, staged_zip)
            staged_zip.replace(zip_path)


def _project_files(job: JobState) -> tuple[dict[str, str], str]:
    manifests = collect_worker_file_manifests(job)
    for manifest in manifests:
        validate_worker_manifest_scope(manifest)
    specs = collect_worker_file_specs(job)
    source = "worker_manifests" if specs else "deterministic_fallback"
    try:
        files = merge_file_specs(specs) if specs else _fallback_project_files(job)
    except ManifestConflictError as exc:
        retry_targets = sorted(
            {
                worker_kind
                for worker_kinds in exc.conflicts.values()
                for worker_kind in worker_kinds
            },
            key=lambda item: item.value,
        )
        raise ArtifactValidationError(
            ProjectValidationReport(
                passed=False,
                checks=["manifest_conflicts:failed"],
                retry_targets=retry_targets,
                failure_reason=str(exc),
            )
        ) from exc

    policy = (
        RequestPolicy.from_dict(job.request_policy)
        if job.request_policy
        else derive_request_policy(job.request.prompt)
    )
    _enforce_policy(files, policy)
    files = _with_project_support_files(job, files, policy, source)
    _enforce_policy(files, policy)
    return files, source


def _validation_release_reason(validation: ProjectValidationReport) -> str | None:
    if validation.release_ready:
        return None
    messages = [
        str(item.get("message", "")).strip()
        for item in validation.advisories
        if item.get("blocking_publication") and str(item.get("message", "")).strip()
    ]
    return (
        "; ".join(messages)
        or "Release checks are incomplete; preview and download remain available."
    )


def _fallback_project_files(job: JobState) -> dict[str, str]:
    specs = []
    for task in job.tasks:
        manifest_json = fallback_worker_manifest_json(
            task,
            job.request.prompt,
            job.request.project_id,
        )
        manifest = extract_worker_file_manifest(manifest_json, task.worker_kind)
        validate_worker_manifest_scope(manifest)
        specs.extend(manifest.files)
    if not specs:
        raise ArtifactValidationError(
            ProjectValidationReport(
                passed=False,
                checks=["worker_files:failed"],
                failure_reason="No worker files are available for artifact generation.",
            )
        )
    return merge_file_specs(specs)


def _with_project_support_files(
    job: JobState,
    files: dict[str, str],
    policy: RequestPolicy,
    source: str,
) -> dict[str, str]:
    project_name = _titleize(job.request.project_id or "generated app")
    supported = dict(files)
    if "frontend/package.json" in supported:
        supported["frontend/package-lock.json"] = _placeholder_package_lock(
            supported["frontend/package.json"]
        )
    if "backend/package.json" in supported:
        supported["backend/package-lock.json"] = _placeholder_package_lock(
            supported["backend/package.json"]
        )
    project_spec = (
        ProjectSpec.from_dict(job.project_spec)
        if job.project_spec
        else resolve_project_spec(job.request.prompt, job.request.metadata, policy)
    )
    supported["README.md"] = _readme(
        project_name,
        job.request.prompt,
        supported,
        policy,
        job.api_contract,
        project_spec,
    )
    supported.setdefault(".gitignore", _gitignore())
    if job.api_contract:
        supported["artifacts/api-contract.json"] = json.dumps(job.api_contract, indent=2) + "\n"
    if policy.requests("docker"):
        supported.setdefault(
            "docker-compose.yml",
            _docker_compose(supported, job.api_contract, project_spec),
        )
    if policy.requests("ci") or policy.requests("github"):
        supported.setdefault(
            ".github/workflows/ci.yml",
            _github_actions_ci(supported, project_spec),
        )
    blueprint = {
        "project": project_name,
        "project_id": job.request.project_id,
        "prompt": job.request.prompt,
        "request_policy": policy.to_dict(),
        "project_spec": project_spec.to_dict(),
        "api_contract": job.api_contract,
        "source": source,
        "worker_tasks": [
            {
                "worker_kind": task.worker_kind.value,
                "title": task.title,
                "attempt": task.attempt,
            }
            for task in job.tasks
        ],
        "files": sorted([*supported, "artifacts/blueprint.json"]),
    }
    supported["artifacts/blueprint.json"] = json.dumps(blueprint, indent=2) + "\n"
    return supported


def _enforce_policy(files: dict[str, str], policy: RequestPolicy) -> None:
    findings: list[str] = []
    retry_targets: set[WorkerKind] = set()
    for path, content in files.items():
        reason = policy.forbidden_path_reason(path)
        if reason:
            findings.append(f"{path}: {reason}")
            retry_targets.update(_workers_for_path(path))
        for content_reason in policy.forbidden_content_reasons(path, content):
            findings.append(f"{path}: {content_reason}")
            retry_targets.update(_workers_for_path(path))
    if findings:
        raise ArtifactValidationError(
            ProjectValidationReport(
                passed=False,
                checks=["explicit_exclusions:failed"],
                retry_targets=sorted(retry_targets, key=lambda item: item.value),
                failure_reason="; ".join(findings),
            )
        )


def _readme(
    project_name: str,
    prompt: str,
    files: dict[str, str],
    policy: RequestPolicy,
    api_contract: dict[str, Any],
    project_spec: ProjectSpec | None = None,
) -> str:
    resolved_spec = project_spec or resolve_project_spec(prompt, policy=policy)
    sections = [
        f"# {project_name}",
        "",
        "Generated from this request:",
        "",
        f"> {prompt}",
        "",
        "## Prerequisites",
        "",
    ]
    has_backend = any(path.startswith("backend/") for path in files)
    has_frontend = any(path.startswith("frontend/") for path in files)
    has_database = any(path.startswith("database/") for path in files)
    python_backend = any(
        path in files for path in ("backend/pyproject.toml", "backend/requirements.txt")
    )
    node_backend = "backend/package.json" in files
    python_cli = resolved_spec.backend_framework == "Python CLI"
    backend_port = _contract_port(
        api_contract,
        "backend_port",
        resolved_spec.ports.get("backend", 8000),
    )
    frontend_port = _contract_port(
        api_contract,
        "frontend_port",
        resolved_spec.ports.get("frontend", resolved_spec.ports.get("application", 5173)),
    )
    if python_backend:
        sections.append("- Python 3.11 or newer")
    if has_frontend or node_backend:
        sections.extend(["- Node.js 20 or newer", "- npm 10 or newer"])
    if has_database:
        sections.append("- PostgreSQL 15 or newer, or a Supabase project")

    if has_backend:
        if node_backend:
            sections.extend(
                [
                    "",
                    "## Backend",
                    "",
                    "```bash",
                    "cd backend",
                    "npm ci",
                    "npm run dev",
                    "```",
                    "",
                    "Run backend validation:",
                    "",
                    "```bash",
                    "cd backend",
                    "npm test",
                    "npm run build",
                    "```",
                ]
            )
        else:
            install_command = _backend_install_command(files)
            run_command = (
                _python_cli_command(files)
                if python_cli
                else (
                    f"python -m uvicorn {_backend_module(files)}:app --host 127.0.0.1 "
                    f"--port {backend_port}"
                )
            )
            sections.extend(
                [
                    "",
                    "## Backend" if not python_cli else "## Command-line Application",
                    "",
                    "```bash",
                    "cd backend",
                    "python3.11 -m venv .venv",
                    "source .venv/bin/activate",
                    install_command,
                    run_command,
                    "```",
                    "",
                    "Run backend tests:",
                    "",
                    "```bash",
                    "cd backend",
                    "source .venv/bin/activate",
                    "python -m pytest",
                    "```",
                ]
            )
    if has_frontend:
        frontend_test_command = _frontend_test_command(files)
        sections.extend(
            [
                "",
                "## Frontend",
                "",
                "```bash",
                "cd frontend",
                "npm ci",
                "npm run dev",
                "```",
                "",
                "Run frontend validation:",
                "",
                "```bash",
                "cd frontend",
                frontend_test_command,
                "npm run build",
                "```",
            ]
        )

    if has_database:
        sql_migration = next(
            (
                path
                for path in sorted(files)
                if path.startswith("database/migrations/") and path.endswith(".sql")
            ),
            None,
        )
        alembic_directory = next(
            (
                directory
                for directory in ("backend", "database")
                if f"{directory}/alembic.ini" in files
            ),
            None,
        )
        database_command = (
            f'psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f {sql_migration}'
            if sql_migration
            else (
                f"cd {alembic_directory}\npython -m alembic upgrade head"
                if alembic_directory
                else "Apply the database schema using your PostgreSQL provider dashboard."
            )
        )
        sections.extend(
            [
                "",
                "## Database",
                "",
                "Set `DATABASE_URL` in your environment, then apply the migration:",
                "",
                "```bash",
                database_command,
                "```",
            ]
        )

    env_examples = sorted(path for path in files if PurePosixPath(path).name == ".env.example")
    if env_examples:
        sections.extend(["", "## Configuration", ""])
        for env_example in env_examples:
            component = PurePosixPath(env_example).parent.as_posix()
            sections.extend(
                [
                    (
                        f"Create `{component}/.env` from `{env_example}` and fill only "
                        "the values required for local development:"
                    ),
                    "",
                    "```bash",
                    f"cp {env_example} {component}/.env",
                    "```",
                    "",
                ]
            )

    sections.extend(["", "## Local URLs", ""])
    if has_backend and not python_cli and backend_port:
        sections.append(f"- Backend: http://127.0.0.1:{backend_port}")
    if has_frontend and frontend_port:
        sections.append(f"- Frontend: http://127.0.0.1:{frontend_port}")
    if python_cli:
        sections.append("- This project is a local command-line application and opens no port.")
    if policy.excluded_capabilities:
        sections.extend(
            [
                "",
                "## Intentionally Excluded",
                "",
                *[
                    f"- {capability.replace('_', ' ').title()}"
                    for capability in sorted(policy.excluded_capabilities)
                ],
            ]
        )
    sections.extend(
        [
            "",
            "## Troubleshooting",
            "",
            "- Run installation commands from the component directory shown above.",
            *(
                [
                    (
                        "- Confirm the documented local ports are available before starting "
                        "the application."
                    )
                ]
                if not python_cli
                else []
            ),
            "- Use the test and build commands above before changing dependencies.",
            "",
        ]
    )
    return "\n".join(sections)


def _backend_install_command(files: dict[str, str]) -> str:
    if "backend/requirements.txt" in files:
        return "python -m pip install -r requirements.txt"
    pyproject = files.get("backend/pyproject.toml", "")
    try:
        payload = tomllib.loads(pyproject)
    except tomllib.TOMLDecodeError:
        return "python -m pip install ."
    extras = payload.get("project", {}).get("optional-dependencies", {})
    for extra in ("test", "tests", "dev"):
        if extra in extras:
            return f'python -m pip install ".[{extra}]"'
    return "python -m pip install ."


def _python_cli_command(files: dict[str, str]) -> str:
    try:
        payload = tomllib.loads(files.get("backend/pyproject.toml", ""))
    except tomllib.TOMLDecodeError:
        return "python -m app"
    scripts = payload.get("project", {}).get("scripts", {})
    if isinstance(scripts, dict) and scripts:
        return str(next(iter(scripts))) + " --help"
    return "python -m app"


def _backend_module(files: dict[str, str]) -> str:
    if "backend/src/app/main.py" in files or "backend/app/main.py" in files:
        return "app.main"
    if "backend/main.py" in files:
        return "main"
    return "app.main"


def _frontend_test_command(files: dict[str, str]) -> str:
    try:
        package = json.loads(files.get("frontend/package.json", "{}"))
    except json.JSONDecodeError:
        return "npm test"
    script = str(package.get("scripts", {}).get("test", ""))
    if "vitest" in script.lower() and "--run" not in script.lower():
        return "npm test -- --run"
    return "npm test"


def _placeholder_package_lock(package_json: str) -> str:
    try:
        package = json.loads(package_json)
    except json.JSONDecodeError:
        package = {}
    root_package = {
        key: package[key]
        for key in (
            "name",
            "version",
            "dependencies",
            "devDependencies",
            "optionalDependencies",
            "engines",
        )
        if key in package
    }
    return (
        json.dumps(
            {
                "name": package.get("name", "generated-project"),
                "version": package.get("version", "0.1.0"),
                "lockfileVersion": 3,
                "requires": True,
                "packages": {"": root_package},
            },
            indent=2,
        )
        + "\n"
    )


def _gitignore() -> str:
    return (
        dedent(
            """
        .env
        .venv/
        __pycache__/
        *.pyc
        .pytest_cache/
        node_modules/
        dist/
        .next/
        coverage/
        .DS_Store
        """
        ).strip()
        + "\n"
    )


def _docker_compose(
    files: dict[str, str],
    api_contract: dict[str, Any],
    project_spec: ProjectSpec,
) -> str:
    services: list[str] = []
    backend_port = _contract_port(
        api_contract,
        "backend_port",
        project_spec.ports.get("backend", 8000),
    )
    frontend_port = _contract_port(
        api_contract,
        "frontend_port",
        project_spec.ports.get("frontend", project_spec.ports.get("application", 5173)),
    )
    if any(path.startswith("backend/") for path in files):
        if "backend/package.json" in files:
            services.append(
                dedent(
                    f"""
                      backend:
                        image: node:20-alpine
                        working_dir: /app/backend
                        command: sh -c "npm ci && npm run build && npm start"
                        environment:
                          PORT: "{backend_port}"
                        volumes:
                          - .:/app
                        ports:
                          - "{backend_port}:{backend_port}"
                    """
                ).rstrip()
            )
        else:
            install_command = _backend_install_command(files).replace("python -m ", "")
            python_version = _backend_python_version(files)
            if project_spec.backend_framework == "Python CLI":
                command = f"{install_command} && {_python_cli_command(files)}"
                ports = ""
            else:
                module = _backend_module(files)
                command = (
                    f"{install_command} && python -m uvicorn {module}:app "
                    f"--host 0.0.0.0 --port {backend_port}"
                )
                ports = f'\n    ports:\n      - "{backend_port}:{backend_port}"'
            services.append(
                dedent(
                    f"""
                      backend:
                        image: python:{python_version}-slim
                        working_dir: /app/backend
                        command: sh -c "{command}"
                        volumes:
                          - .:/app{ports}
                    """
                ).rstrip()
            )
    if any(path.startswith("frontend/") for path in files):
        is_next = project_spec.frontend_framework == "Next.js"
        dev_flags = (
            f"--hostname 0.0.0.0 --port {frontend_port}"
            if is_next
            else f"--host 0.0.0.0 --port {frontend_port}"
        )
        services.append(
            dedent(
                f"""
                  frontend:
                    image: node:20-alpine
                    working_dir: /app/frontend
                    command: sh -c "npm ci && npm run dev -- {dev_flags}"
                    volumes:
                      - .:/app
                    ports:
                      - "{frontend_port}:{frontend_port}"
                """
            ).rstrip()
        )
    return "services:\n" + "\n".join(services) + "\n"


def _github_actions_ci(files: dict[str, str], project_spec: ProjectSpec) -> str:
    steps = ["      - uses: actions/checkout@v4"]
    if any(path.startswith("backend/") for path in files):
        if "backend/package.json" in files:
            steps.extend(_node_ci_steps("backend"))
        else:
            install_command = _backend_install_command(files)
            python_version = _backend_python_version(files)
            steps.extend(
                [
                    "      - uses: actions/setup-python@v5",
                    f'        with: {{python-version: "{python_version}"}}',
                    f"      - run: {install_command}",
                    "        working-directory: backend",
                    "      - run: python -m pytest",
                    "        working-directory: backend",
                ]
            )
    if any(path.startswith("frontend/") for path in files):
        steps.extend(_node_ci_steps("frontend"))
    return (
        "name: CI\non: [push, pull_request]\njobs:\n  validate:\n    runs-on: ubuntu-latest\n    steps:\n"
        + "\n".join(steps)
        + "\n"
    )


def _node_ci_steps(component: str) -> list[str]:
    return [
        "      - uses: actions/setup-node@v4",
        '        with: {node-version: "20", cache: "npm", cache-dependency-path: "'
        + component
        + '/package-lock.json"}',
        "      - run: npm ci",
        f"        working-directory: {component}",
        "      - run: npm test",
        f"        working-directory: {component}",
        "      - run: npm run build",
        f"        working-directory: {component}",
    ]


def _backend_python_version(files: dict[str, str]) -> str:
    pyproject = files.get("backend/pyproject.toml", "")
    try:
        requires_python = str(
            tomllib.loads(pyproject).get("project", {}).get("requires-python", "")
        )
    except tomllib.TOMLDecodeError:
        requires_python = ""
    match = re.search(r"3\.(\d+)", requires_python)
    return f"3.{match.group(1)}" if match else "3.11"


def _contract_port(contract: dict[str, Any], name: str, default: int) -> int:
    value = contract.get(name, default)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _write_zip(root: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root))


def _verify_zip_parity(root: Path, zip_path: Path) -> None:
    folder_files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    with zipfile.ZipFile(zip_path) as archive:
        zip_files = {name.rstrip("/") for name in archive.namelist() if not name.endswith("/")}
    if folder_files != zip_files:
        missing = sorted(folder_files - zip_files)
        extra = sorted(zip_files - folder_files)
        raise ArtifactValidationError(
            ProjectValidationReport(
                passed=False,
                checks=["archive_content_verification:failed"],
                failure_reason=f"ZIP parity failed. Missing={missing}; extra={extra}",
            )
        )


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _workers_for_path(path: str) -> set[WorkerKind]:
    if path.startswith("backend/"):
        return {WorkerKind.BACKEND}
    if path.startswith("frontend/"):
        return {WorkerKind.FRONTEND}
    if path.startswith("database/"):
        return {WorkerKind.DATABASE}
    return {WorkerKind.BACKEND, WorkerKind.FRONTEND}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:64] or "generated-app"


def _titleize(value: str) -> str:
    return re.sub(r"[-_]+", " ", value).strip().title() or "Generated App"
