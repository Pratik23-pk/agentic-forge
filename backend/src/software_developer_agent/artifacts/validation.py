from __future__ import annotations

import ast
import json
import keyword
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePath
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

from software_developer_agent.capabilities.models import ProjectSpec
from software_developer_agent.capabilities.registry import (
    COMMON_NPM_COMMANDS,
    resolve_capability,
    resolve_project_spec,
)
from software_developer_agent.capabilities.validation_adapters import validate_with_adapters
from software_developer_agent.config.settings import Settings
from software_developer_agent.guardrails.output.api_key_detection import scan_api_keys
from software_developer_agent.guardrails.output.dlp_scan import scan_dlp
from software_developer_agent.guardrails.output.vulnerability_scan import scan_vulnerabilities
from software_developer_agent.models.job_state import JobState, WorkerKind
from software_developer_agent.models.request_policy import RequestPolicy, derive_request_policy

SECRET_ENV_MARKERS = (
    "API_KEY",
    "DATABASE_URL",
    "PASSWORD",
    "SECRET",
    "STRIPE_",
    "SUPABASE_",
    "TOKEN",
)
STANDARD_ENVIRONMENT_VARIABLES = {
    "CI",
    "HOST",
    "NODE_ENV",
    "PATH",
    "PORT",
    "PYTHONPATH",
}
NPM_EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
PYTHON_EXACT_VERSION = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[^;\s]+")
ENVIRONMENT_REFERENCE_PATTERNS = (
    re.compile(r"os\.getenv\(\s*[\"']([A-Z][A-Z0-9_]*)[\"']"),
    re.compile(r"os\.environ(?:\.get)?\(\s*[\"']([A-Z][A-Z0-9_]*)[\"']"),
    re.compile(r"os\.environ\[\s*[\"']([A-Z][A-Z0-9_]*)[\"']\s*\]"),
    re.compile(r"import\.meta\.env\.([A-Z][A-Z0-9_]*)"),
    re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)"),
)
UNSAFE_EXECUTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "child process import": re.compile(
        r"(?:from\s+[\"']child_process[\"']|require\(\s*[\"']child_process[\"']\s*\))"
    ),
    "destructive filesystem call": re.compile(
        r"\b(?:shutil\.rmtree|os\.(?:remove|rmdir|unlink)|fs\.(?:rm|rmdir|unlink))\s*\("
    ),
    "dynamic Python execution": re.compile(r"\b(?:eval|exec)\s*\("),
    "shell execution": re.compile(
        r"\b(?:os\.system|subprocess\.(?:call|check_call|check_output|Popen|run))\s*\("
    ),
    "socket access": re.compile(r"^\s*(?:from\s+socket\s+import|import\s+socket\b)", re.MULTILINE),
}
DOCUMENTED_FILE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])"
    r"((?:backend|frontend|database|docs|scripts|artifacts)/[A-Za-z0-9_./-]+"
    r"|(?:requirements[^`\s]*\.txt|pyproject\.toml|package-lock\.json|package\.json|"
    r"docker-compose\.ya?ml|\.env\.example))"
)
INFRASTRUCTURE_FAILURE_PATTERNS = (
    "eai_again",
    "econnaborted",
    "econnreset",
    "econnrefused",
    "enetwork",
    "enetunreach",
    "etimedout",
    "err_socket_connection_timeout",
    "getaddrinfo",
    "max retries exceeded",
    "network is unreachable",
    "registry service unavailable",
    "request to https://registry.npmjs.org",
    "socket hang up",
    "temporary failure in name resolution",
    "tls handshake timeout",
    "validation command timed out",
    "signal sigkill",
    # npm/arborist aborts peer resolution with a null tree node when registry
    # metadata cannot be fetched. It is a dependency-registry failure, not a
    # defect in generated code, so it must not consume a worker attempt.
    "cannot read properties of null (reading 'edgesout')",
    "cannot read properties of undefined (reading 'edgesout')",
)
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
DIAGNOSTIC_LINE_PATTERN = re.compile(
    r"(?:assertionerror|error:|exception|failed|failure|referenceerror|typeerror|"
    r"unable to find|found multiple|expected|received|traceback|\bactual\b|"
    r"(?:src|tests?)/[^:\s]+:\d+)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ValidationCommandResult:
    name: str
    worker_kind: WorkerKind | None
    command: str
    cwd: str
    passed: bool
    exit_code: int | None
    duration_seconds: float
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    phase: str = "execution"
    failure_kind: str | None = None
    blocking: bool = True
    timed_out: bool = False
    attempt: int = 1

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["worker_kind"] = self.worker_kind.value if self.worker_kind else None
        return payload


@dataclass(slots=True)
class ProjectValidationReport:
    passed: bool
    release_ready: bool = True
    checks: list[str] = field(default_factory=list)
    results: list[ValidationCommandResult] = field(default_factory=list)
    retry_targets: list[WorkerKind] = field(default_factory=list)
    failure_reason: str | None = None
    failure_kind: str | None = None
    advisories: list[dict[str, Any]] = field(default_factory=list)
    adapter_findings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "release_ready": self.release_ready,
            "checks": self.checks,
            "results": [result.to_dict() for result in self.results],
            "retry_targets": [target.value for target in self.retry_targets],
            "failure_reason": self.failure_reason,
            "failure_kind": self.failure_kind,
            "advisories": self.advisories,
            "adapter_findings": self.adapter_findings,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ProjectValidationReport:
        return cls(
            passed=bool(payload.get("passed", False)),
            release_ready=bool(payload.get("release_ready", payload.get("passed", False))),
            checks=[str(item) for item in payload.get("checks", [])],
            results=[
                ValidationCommandResult(
                    name=str(item.get("name", "unknown")),
                    worker_kind=(
                        WorkerKind(str(item["worker_kind"]))
                        if item.get("worker_kind") in {kind.value for kind in WorkerKind}
                        else None
                    ),
                    command=str(item.get("command", "")),
                    cwd=str(item.get("cwd", "")),
                    passed=bool(item.get("passed", False)),
                    exit_code=item.get("exit_code"),
                    duration_seconds=float(item.get("duration_seconds", 0.0)),
                    stdout_excerpt=str(item.get("stdout_excerpt", "")),
                    stderr_excerpt=str(item.get("stderr_excerpt", "")),
                    phase=str(item.get("phase", "execution")),
                    failure_kind=item.get("failure_kind"),
                    blocking=bool(item.get("blocking", True)),
                    timed_out=bool(item.get("timed_out", False)),
                    attempt=int(item.get("attempt", 1)),
                )
                for item in payload.get("results", [])
                if isinstance(item, dict)
            ],
            retry_targets=[
                WorkerKind(str(item))
                for item in payload.get("retry_targets", [])
                if item in {kind.value for kind in WorkerKind}
            ],
            failure_reason=payload.get("failure_reason"),
            failure_kind=payload.get("failure_kind"),
            advisories=[
                dict(item) for item in payload.get("advisories", []) if isinstance(item, dict)
            ],
            adapter_findings=[
                dict(item) for item in payload.get("adapter_findings", []) if isinstance(item, dict)
            ],
        )


class ArtifactValidationError(RuntimeError):
    def __init__(self, report: ProjectValidationReport) -> None:
        self.report = report
        super().__init__(report.failure_reason or "Generated project validation failed.")


class ProjectValidator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def validate(self, root: Path, job: JobState) -> ProjectValidationReport:
        if self._settings.app_env == "test":
            return ProjectValidationReport(
                passed=True,
                checks=["structural_validation:skipped_in_test"],
            )
        try:
            return self._validate_project(root, job)
        finally:
            # Installed dependencies and build output must never reach the published
            # folder or ZIP, including on an early return or a mid-validation error.
            self._clean_validation_outputs(root)

    def _validate_project(self, root: Path, job: JobState) -> ProjectValidationReport:
        policy = (
            RequestPolicy.from_dict(job.request_policy)
            if job.request_policy
            else derive_request_policy(job.request.prompt)
        )
        project_spec = (
            ProjectSpec.from_dict(job.project_spec)
            if job.project_spec
            else resolve_project_spec(job.request.prompt, job.request.metadata, policy)
        )
        preparation = ProjectValidationReport(passed=True)
        if self._settings.enable_artifact_validation:
            for component, worker_kind in (
                ("backend", WorkerKind.BACKEND),
                ("frontend", WorkerKind.FRONTEND),
            ):
                if not (root / component / "package.json").exists():
                    continue
                package_findings = _node_manifest_findings(
                    component,
                    {
                        f"{component}/package.json": (root / component / "package.json").read_text(
                            encoding="utf-8", errors="replace"
                        )
                    },
                    project_spec,
                )
                if package_findings:
                    return ProjectValidationReport(
                        passed=False,
                        checks=[f"{component}_manifest_preflight:failed"],
                        retry_targets=[worker_kind],
                        failure_reason="; ".join(package_findings),
                    )
                lockfile_command = [
                    _npm_executable(),
                    "install",
                    "--package-lock-only",
                    "--ignore-scripts",
                    "--no-audit",
                ]
                lockfile_cwd = root / component
                if self._settings.artifact_validation_sandbox_mode == "docker":
                    lockfile_command = self._docker_lockfile_command(lockfile_cwd)
                    lockfile_cwd = root
                if not self._generate_lockfile(
                    preparation,
                    component=component,
                    worker_kind=worker_kind,
                    command=lockfile_command,
                    cwd=lockfile_cwd,
                ):
                    return preparation

        structural = self._validate_structure(root, policy, project_spec)
        structural.checks = [*preparation.checks, *structural.checks]
        structural.results = [*preparation.results, *structural.results]
        if not structural.passed:
            return structural

        if self._settings.enable_domain_adapter_validation:
            adapter_validation = validate_with_adapters(root, project_spec)
            structural.checks.extend(adapter_validation.checks)
            structural.adapter_findings.extend(
                finding.to_dict() for finding in adapter_validation.findings
            )
            structural.advisories.extend(
                finding.to_dict() for finding in adapter_validation.advisories
            )
            if adapter_validation.blocking_findings:
                return ProjectValidationReport(
                    passed=False,
                    checks=structural.checks,
                    results=structural.results,
                    retry_targets=sorted(
                        {finding.worker_kind for finding in adapter_validation.blocking_findings},
                        key=lambda item: item.value,
                    ),
                    failure_reason="; ".join(
                        finding.message for finding in adapter_validation.blocking_findings
                    ),
                    advisories=structural.advisories,
                    adapter_findings=structural.adapter_findings,
                )
        else:
            structural.checks.append("domain_adapter_validation:stack_certification_only")

        if not self._settings.enable_artifact_validation:
            structural.checks.append("execution_validation:skipped")
            return structural

        report = structural
        worker_order = _validation_worker_order(job)
        if job.active_repair_ticket_ids:
            targeted_workers = [
                worker.value for worker in worker_order if job.active_repair_ticket(worker)
            ]
            report.checks.append("targeted_validation_first:" + ",".join(targeted_workers))
        if self._settings.artifact_validation_sandbox_mode == "docker":
            self._validate_in_docker(root, report, project_spec, worker_order)
            if report.passed and job.api_contract.get("routes"):
                self._validate_contract(root, None, job.api_contract, report)
            if not report.passed and report.failure_reason is None:
                report.failure_reason = "Generated project validation failed in Docker."
            return report

        with tempfile.TemporaryDirectory(prefix="agentic-forge-validation-") as temp_dir:
            temp_root = Path(temp_dir)
            for worker_kind in worker_order:
                if worker_kind == WorkerKind.BACKEND and (root / "backend").exists():
                    self._validate_backend(root, temp_root, report, project_spec)
                elif worker_kind == WorkerKind.FRONTEND and (root / "frontend").exists():
                    self._validate_frontend(root, report, project_spec)
                if not report.passed:
                    break
            if report.passed and job.api_contract.get("routes"):
                self._validate_contract(root, temp_root, job.api_contract, report)

        if not report.passed and report.failure_reason is None:
            report.failure_reason = "Generated project validation failed."
        return report

    def _generate_lockfile(
        self,
        report: ProjectValidationReport,
        *,
        component: str,
        worker_kind: WorkerKind,
        command: list[str],
        cwd: Path,
    ) -> bool:
        """Create the deterministic lockfile, tolerating a crash in npm's peer resolver."""

        result = self._run(
            report,
            name=f"{component}_lockfile_generation",
            worker_kind=worker_kind,
            command=command,
            cwd=cwd,
            allow_network=True,
            phase="dependency_install",
            infrastructure_retries=self._settings.artifact_infrastructure_retry_attempts,
        )
        if report.passed:
            return True
        if not _is_peer_resolution_crash(result):
            return False

        # npm can abort peer resolution with a null tree node instead of reporting a
        # real conflict. That is a package-manager defect, not a generated-code defect,
        # so retry once with the documented escape hatch rather than failing a worker.
        report.passed = True
        report.release_ready = True
        report.failure_kind = None
        report.failure_reason = None
        report.retry_targets = []
        report.checks.append(f"{component}_lockfile_generation:peer_resolver_fallback")
        self._run(
            report,
            name=f"{component}_lockfile_generation_compat",
            worker_kind=worker_kind,
            command=[*command, "--legacy-peer-deps"],
            cwd=cwd,
            allow_network=True,
            phase="dependency_install",
            infrastructure_retries=self._settings.artifact_infrastructure_retry_attempts,
        )
        return report.passed

    def _validate_in_docker(
        self,
        root: Path,
        report: ProjectValidationReport,
        project_spec: ProjectSpec,
        worker_order: list[WorkerKind],
    ) -> None:
        if shutil.which("docker") is None:
            report.passed = False
            report.release_ready = False
            report.retry_targets = []
            report.failure_kind = "infrastructure"
            report.failure_reason = "Docker is required for isolated executable validation."
            report.checks.append("docker_sandbox:unavailable")
            return

        components = {
            WorkerKind.BACKEND: "backend",
            WorkerKind.FRONTEND: "frontend",
        }
        for worker_kind in worker_order:
            component = components.get(worker_kind)
            if component is None:
                continue
            component_root = root / component
            if not component_root.exists():
                continue
            if (component_root / "package.json").exists():
                script = self._node_sandbox_script(component_root)
                image = "node:20-alpine"
            else:
                script = self._python_sandbox_script(root, component_root, project_spec)
                image = "python:3.11-slim"
            self._run(
                report,
                name=f"{component}_docker_execution",
                worker_kind=worker_kind,
                command=self._docker_validation_command(root, component, image, script),
                cwd=root,
                allow_network=True,
                phase="execution",
                infrastructure_retries=self._settings.artifact_infrastructure_retry_attempts,
            )
            if not report.passed:
                return
            if (component_root / "package.json").exists():
                self._validate_node_audits_in_docker(
                    root,
                    component,
                    image,
                    report,
                    worker_kind,
                )
                if not report.passed:
                    return
        report.checks.append("docker_sandbox:passed")

    def _node_sandbox_script(self, component: Path) -> str:
        package = json.loads((component / "package.json").read_text(encoding="utf-8"))
        scripts = package.get("scripts", {})
        test_command = "npm test"
        if (
            "vitest" in str(scripts.get("test", "")).lower()
            and "--run" not in str(scripts.get("test", "")).lower()
        ):
            test_command += " -- --run"
        return (
            "npm ci --ignore-scripts --no-audit && { "
            "build_status=0; test_status=0; "
            "npm run build || build_status=$?; "
            f"{test_command} || test_status=$?; "
            '[ "$build_status" -eq 0 ] && [ "$test_status" -eq 0 ]; }'
        )

    def _validate_node_audits_in_docker(
        self,
        root: Path,
        component: str,
        image: str,
        report: ProjectValidationReport,
        worker_kind: WorkerKind,
    ) -> None:
        audits = (
            (
                f"{component}_production_dependency_audit",
                "npm audit --omit=dev --audit-level=high",
                True,
                True,
            ),
            (
                f"{component}_development_critical_audit",
                "npm audit --audit-level=critical",
                True,
                True,
            ),
            (
                f"{component}_development_high_advisory",
                "npm audit --audit-level=high",
                False,
                False,
            ),
        )
        for name, script, blocking, incomplete_blocks_release in audits:
            result = self._run(
                report,
                name=name,
                worker_kind=worker_kind,
                command=self._docker_validation_command(root, component, image, script),
                cwd=root,
                allow_network=True,
                blocking=blocking,
                phase="dependency_security",
                failure_kind="security",
                timeout_seconds=self._settings.artifact_audit_timeout_seconds,
                infrastructure_retries=(
                    self._settings.artifact_infrastructure_retry_attempts if blocking else 0
                ),
                infrastructure_failure_is_advisory=True,
                incomplete_blocks_release=incomplete_blocks_release,
            )
            if not report.passed:
                return
            if result.failure_kind == "infrastructure":
                report.checks.append("dependency_audit_circuit:registry_unavailable")
                break

    def _python_sandbox_script(
        self,
        root: Path,
        component: Path,
        project_spec: ProjectSpec,
    ) -> str:
        install_target = "."
        if (component / "pyproject.toml").exists():
            try:
                pyproject = tomllib.loads(
                    (component / "pyproject.toml").read_text(encoding="utf-8")
                )
            except tomllib.TOMLDecodeError:
                pyproject = {}
            extras = pyproject.get("project", {}).get("optional-dependencies", {})
            for extra in ("test", "tests", "dev"):
                if extra in extras:
                    install_target = f".[{extra}]"
                    break
            install = f"/tmp/venv/bin/pip install {shlex.quote(install_target)}"
        else:
            install = "/tmp/venv/bin/pip install -r requirements.txt"
        commands = [
            "python -m venv /tmp/venv",
            install,
            "/tmp/venv/bin/pip check",
        ]
        if (component / "tests").exists():
            commands.append("/tmp/venv/bin/python -m pytest -vv --tb=long")
        if project_spec.backend_framework != "Python CLI":
            module = _backend_module(root)
            health_script = _backend_health_script(module)
            health_command = "/tmp/venv/bin/python -c " + shlex.quote(health_script)
            smoke_environment = _synthetic_smoke_environment(component)
            if smoke_environment:
                assignments = " ".join(
                    f"{name}={shlex.quote(value)}"
                    for name, value in sorted(smoke_environment.items())
                )
                health_command = f"env {assignments} {health_command}"
            commands.append(health_command)
        return " && ".join(commands)

    def _docker_validation_command(
        self,
        root: Path,
        component: str,
        image: str,
        script: str,
    ) -> list[str]:
        bootstrap = (
            "mkdir -p /tmp/home /tmp/project && "
            "cp -R /source/. /tmp/project && "
            f"cd /tmp/project && {script}"
        )
        return [
            "docker",
            "run",
            "--rm",
            "--name",
            f"agentic-forge-validation-{uuid4().hex[:12]}",
            "--network",
            "bridge",
            "--cpus",
            "1.0",
            "--memory",
            f"{self._settings.artifact_validation_memory_limit_mb}m",
            "--pids-limit",
            "128",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,exec,size=1024m",
            "-e",
            "HOME=/tmp/home",
            "-v",
            f"{_docker_mount_path(root / component)}:/source:ro",
            image,
            "sh",
            "-lc",
            bootstrap,
        ]

    def _docker_lockfile_command(self, component: Path) -> list[str]:
        return [
            "docker",
            "run",
            "--rm",
            "--name",
            f"agentic-forge-lockfile-{uuid4().hex[:12]}",
            "--network",
            "bridge",
            "--cpus",
            "1.0",
            "--memory",
            f"{self._settings.artifact_validation_memory_limit_mb}m",
            "--pids-limit",
            "128",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,exec,size=256m",
            "-e",
            "HOME=/tmp/home",
            "-v",
            f"{_docker_mount_path(component)}:/workspace:rw",
            "-w",
            "/workspace",
            "node:20-alpine",
            "npm",
            "install",
            "--package-lock-only",
            "--ignore-scripts",
            "--no-audit",
        ]

    def _validate_structure(
        self,
        root: Path,
        policy: RequestPolicy,
        project_spec: ProjectSpec,
    ) -> ProjectValidationReport:
        checks: list[str] = []
        findings: list[str] = []
        retry_targets: set[WorkerKind] = set()

        files = {
            path.relative_to(root).as_posix(): path for path in root.rglob("*") if path.is_file()
        }
        text_files = {
            relative_path: path.read_text(encoding="utf-8", errors="replace")
            for relative_path, path in files.items()
            if path.stat().st_size <= 300_000
        }
        for relative_path in files:
            reason = policy.forbidden_path_reason(relative_path)
            if reason:
                findings.append(f"{relative_path}: {reason}")
                retry_targets.update(_workers_for_path(relative_path))
            content = text_files.get(relative_path, "")
            for content_reason in policy.forbidden_content_reasons(relative_path, content):
                findings.append(f"{relative_path}: {content_reason}")
                retry_targets.update(_workers_for_path(relative_path))
        checks.append("explicit_exclusions")

        if any(path.startswith("backend/") for path in files):
            backend_manifests = {
                path
                for path in files
                if path
                in {
                    "backend/package.json",
                    "backend/pyproject.toml",
                    "backend/requirements.txt",
                }
            }
            if len(backend_manifests) != 1:
                findings.append(
                    "Backend must contain exactly one dependency strategy: "
                    "backend/package.json, backend/pyproject.toml, or backend/requirements.txt."
                )
                retry_targets.add(WorkerKind.BACKEND)
            if not any(_is_component_test_file(path, "backend") for path in files):
                findings.append("Backend focused tests are missing.")
                retry_targets.add(WorkerKind.BACKEND)
            if "backend/package.json" in files:
                backend_findings = _node_manifest_findings(
                    "backend",
                    text_files,
                    project_spec,
                )
            else:
                backend_findings = _backend_manifest_findings(
                    files,
                    text_files,
                    project_spec,
                )
            findings.extend(backend_findings)
            if backend_findings:
                retry_targets.add(WorkerKind.BACKEND)
            backend_connectivity_findings = _backend_runtime_connectivity_findings(
                text_files,
                project_spec,
            )
            findings.extend(backend_connectivity_findings)
            if backend_connectivity_findings:
                retry_targets.add(WorkerKind.BACKEND)
            checks.append("backend_dependency_manifest")
            checks.append("backend_test_presence")
            checks.append("backend_dependency_pinning")

        if any(path.startswith("frontend/") for path in files):
            if "frontend/package.json" not in files:
                findings.append("Frontend package.json is missing.")
                retry_targets.add(WorkerKind.FRONTEND)
            if "frontend/package-lock.json" not in files:
                findings.append("Frontend package-lock.json is missing.")
                retry_targets.add(WorkerKind.FRONTEND)
            if not any(_is_frontend_test_file(path) for path in files):
                findings.append("Frontend focused tests are missing.")
                retry_targets.add(WorkerKind.FRONTEND)
            frontend_findings = _node_manifest_findings(
                "frontend",
                text_files,
                project_spec,
            )
            frontend_findings.extend(_frontend_test_contract_findings(text_files))
            frontend_findings.extend(
                _frontend_runtime_connectivity_findings(text_files, project_spec)
            )
            findings.extend(frontend_findings)
            if frontend_findings:
                retry_targets.add(WorkerKind.FRONTEND)
            checks.extend(
                [
                    "frontend_dependency_manifest",
                    "frontend_lockfile",
                    "frontend_test_presence",
                    "frontend_dependency_pinning",
                    "frontend_script_safety",
                ]
            )

        readme = files.get("README.md")
        if readme is None:
            findings.append("Root README.md is missing.")
        else:
            readme_text = text_files.get("README.md", "")
            for referenced_path in sorted(set(DOCUMENTED_FILE_PATTERN.findall(readme_text))):
                if not _documented_path_exists(referenced_path, files):
                    findings.append(f"README.md references missing file {referenced_path}.")
                    retry_targets.update(_workers_for_path(referenced_path))
            readme_findings = _readme_consistency_findings(files, readme_text)
            findings.extend(readme_findings)
            if readme_findings:
                retry_targets.update({WorkerKind.BACKEND, WorkerKind.FRONTEND})
            checks.append("readme_file_references")
            checks.append("readme_manifest_consistency")

        configuration_findings = _configuration_findings(files, text_files)
        findings.extend(configuration_findings)
        for finding in configuration_findings:
            if finding.startswith("backend"):
                retry_targets.add(WorkerKind.BACKEND)
            elif finding.startswith("frontend"):
                retry_targets.add(WorkerKind.FRONTEND)
        checks.append("configuration_documentation")

        persistence_findings = _persistence_integration_findings(text_files, project_spec)
        findings.extend(persistence_findings)
        if persistence_findings:
            retry_targets.add(WorkerKind.BACKEND)
        checks.append("requested_persistence_integration")

        migration_ownership_findings = _migration_ownership_findings(files)
        findings.extend(migration_ownership_findings)
        if migration_ownership_findings:
            retry_targets.add(WorkerKind.BACKEND)
        checks.append("single_migration_owner")

        safety_findings = _execution_safety_findings(text_files)
        findings.extend(safety_findings)
        if safety_findings:
            retry_targets.update(
                worker
                for path in text_files
                for worker in _workers_for_path(path)
                if any(
                    pattern.search(text_files[path])
                    for pattern in UNSAFE_EXECUTION_PATTERNS.values()
                )
            )
        checks.append("generated_code_execution_safety")

        all_text = "\n\n".join(text_files.values())
        runtime_text = "\n\n".join(
            content for path, content in text_files.items() if _is_runtime_security_path(path)
        )
        for report in (
            scan_dlp(runtime_text),
            scan_api_keys(all_text),
            scan_vulnerabilities(runtime_text),
        ):
            if not report.passed:
                findings.extend(finding.message for finding in report.failed_findings)
                retry_targets.update({WorkerKind.BACKEND, WorkerKind.FRONTEND, WorkerKind.DATABASE})
            checks.append(f"final_{report.name}")

        if findings:
            available_workers = {
                worker
                for worker, prefix in (
                    (WorkerKind.BACKEND, "backend/"),
                    (WorkerKind.FRONTEND, "frontend/"),
                    (WorkerKind.DATABASE, "database/"),
                )
                if any(path.startswith(prefix) for path in files)
            }
            retry_targets.intersection_update(available_workers)
            return ProjectValidationReport(
                passed=False,
                checks=checks,
                retry_targets=sorted(retry_targets, key=lambda item: item.value),
                failure_reason="; ".join(findings),
            )
        return ProjectValidationReport(passed=True, checks=checks)

    def _validate_backend(
        self,
        root: Path,
        temp_root: Path,
        report: ProjectValidationReport,
        project_spec: ProjectSpec,
    ) -> None:
        backend = root / "backend"
        if (backend / "package.json").exists():
            self._validate_node_component(
                backend,
                report,
                worker_kind=WorkerKind.BACKEND,
                result_prefix="backend",
            )
            return
        venv = temp_root / "backend-venv"
        self._run(
            report,
            name="backend_virtualenv",
            worker_kind=WorkerKind.BACKEND,
            command=[sys.executable, "-m", "venv", str(venv)],
            cwd=root,
        )
        if not report.passed:
            return

        python = venv / "bin" / "python"
        if not python.exists():
            python = venv / "Scripts" / "python.exe"
        if (backend / "pyproject.toml").exists():
            install_target = str(backend)
            try:
                pyproject = tomllib.loads((backend / "pyproject.toml").read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError:
                pyproject = {}
            extras = pyproject.get("project", {}).get("optional-dependencies", {})
            for extra in ("test", "tests", "dev"):
                if extra in extras:
                    install_target = f"{backend}[{extra}]"
                    break
            install_command = [str(python), "-m", "pip", "install", install_target]
        else:
            install_command = [
                str(python),
                "-m",
                "pip",
                "install",
                "-r",
                str(backend / "requirements.txt"),
            ]
        self._run(
            report,
            name="backend_install",
            worker_kind=WorkerKind.BACKEND,
            command=install_command,
            cwd=root,
            allow_network=True,
        )
        if not report.passed:
            return
        self._run(
            report,
            name="backend_dependency_check",
            worker_kind=WorkerKind.BACKEND,
            command=[str(python), "-m", "pip", "check"],
            cwd=backend,
        )
        if not report.passed:
            return
        if (backend / "tests").exists():
            self._run(
                report,
                name="backend_tests",
                worker_kind=WorkerKind.BACKEND,
                command=[str(python), "-m", "pytest"],
                cwd=backend,
                extra_env=_python_path_env(backend),
            )
        if not report.passed:
            return

        if project_spec.backend_framework == "Python CLI":
            report.checks.append("python_cli_entrypoint:covered_by_tests")
            return

        module = _backend_module(root)
        self._run(
            report,
            name="backend_import",
            worker_kind=WorkerKind.BACKEND,
            command=[
                str(python),
                "-c",
                f"from {module} import app; assert app is not None",
            ],
            cwd=backend,
            extra_env=_python_path_env(backend),
        )
        if not report.passed:
            return
        self._run(
            report,
            name="backend_health_workflow",
            worker_kind=WorkerKind.BACKEND,
            command=[
                str(python),
                "-c",
                _backend_health_script(module),
            ],
            cwd=backend,
            extra_env=_python_path_env(backend),
        )

    def _validate_frontend(
        self,
        root: Path,
        report: ProjectValidationReport,
        project_spec: ProjectSpec,
    ) -> None:
        self._validate_node_component(
            root / "frontend",
            report,
            worker_kind=WorkerKind.FRONTEND,
            result_prefix="frontend",
        )

    def _validate_node_component(
        self,
        component: Path,
        report: ProjectValidationReport,
        *,
        worker_kind: WorkerKind,
        result_prefix: str,
    ) -> None:
        npm = _npm_executable()
        self._run(
            report,
            name=f"{result_prefix}_install",
            worker_kind=worker_kind,
            command=[npm, "ci", "--ignore-scripts", "--no-audit"],
            cwd=component,
            allow_network=True,
            phase="dependency_install",
            infrastructure_retries=self._settings.artifact_infrastructure_retry_attempts,
        )
        if not report.passed:
            return

        package = json.loads((component / "package.json").read_text(encoding="utf-8"))
        scripts = package.get("scripts", {})
        if "build" not in scripts:
            report.passed = False
            report.retry_targets.append(worker_kind)
            report.failure_reason = (
                f"{result_prefix.title()} package.json must define a build script."
            )
            return
        self._run(
            report,
            name=f"{result_prefix}_build",
            worker_kind=worker_kind,
            command=[npm, "run", "build"],
            cwd=component,
            phase="build",
        )
        if not report.passed:
            return
        if "test" not in scripts:
            report.passed = False
            report.retry_targets.append(worker_kind)
            report.failure_reason = (
                f"{result_prefix.title()} package.json must define a test script."
            )
            return
        test_command = [npm, "test"]
        if "vitest" in str(scripts["test"]).lower() and "--run" not in str(scripts["test"]).lower():
            test_command.extend(["--", "--run"])
        self._run(
            report,
            name=f"{result_prefix}_tests",
            worker_kind=worker_kind,
            command=test_command,
            cwd=component,
            phase="tests",
        )
        if not report.passed:
            return
        audit_result = self._run(
            report,
            name=f"{result_prefix}_production_dependency_audit",
            worker_kind=worker_kind,
            command=[npm, "audit", "--omit=dev", "--audit-level=high"],
            cwd=component,
            allow_network=True,
            phase="dependency_security",
            failure_kind="security",
            timeout_seconds=self._settings.artifact_audit_timeout_seconds,
            infrastructure_retries=self._settings.artifact_infrastructure_retry_attempts,
            infrastructure_failure_is_advisory=True,
            incomplete_blocks_release=True,
        )
        if not report.passed:
            return
        if audit_result is not None and audit_result.failure_kind == "infrastructure":
            report.checks.append("dependency_audit_circuit:registry_unavailable")
            return
        self._run(
            report,
            name=f"{result_prefix}_development_critical_audit",
            worker_kind=worker_kind,
            command=[npm, "audit", "--audit-level=critical"],
            cwd=component,
            allow_network=True,
            phase="dependency_security",
            failure_kind="security",
            timeout_seconds=self._settings.artifact_audit_timeout_seconds,
            infrastructure_retries=self._settings.artifact_infrastructure_retry_attempts,
            infrastructure_failure_is_advisory=True,
            incomplete_blocks_release=True,
        )
        if not report.passed:
            return
        self._run(
            report,
            name=f"{result_prefix}_development_high_advisory",
            worker_kind=worker_kind,
            command=[npm, "audit", "--audit-level=high"],
            cwd=component,
            allow_network=True,
            blocking=False,
            phase="dependency_security",
            failure_kind="security",
            timeout_seconds=self._settings.artifact_audit_timeout_seconds,
            infrastructure_retries=0,
            infrastructure_failure_is_advisory=True,
        )

    def _validate_contract(
        self,
        root: Path,
        temp_root: Path | None,
        contract: dict[str, Any],
        report: ProjectValidationReport,
    ) -> None:
        routes = contract.get("routes", [])
        if not isinstance(routes, list) or not routes:
            report.passed = False
            report.retry_targets = [WorkerKind.BACKEND, WorkerKind.FRONTEND]
            report.failure_reason = "Shared API contract is missing routes."
            return

        readme_text = (root / "README.md").read_text(encoding="utf-8", errors="replace")
        for port_name, default in (("backend_port", 8000), ("frontend_port", 5173)):
            port = int(contract.get(port_name, default))
            if f":{port}" not in readme_text:
                report.passed = False
                report.retry_targets = [WorkerKind.BACKEND, WorkerKind.FRONTEND]
                report.failure_reason = (
                    f"README.md does not document contracted {port_name} {port}."
                )
                return

        frontend_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in (root / "frontend").rglob("*")
            if path.is_file()
            and "node_modules" not in path.parts
            and path.suffix in {".js", ".jsx", ".ts", ".tsx"}
            and ".test." not in path.name
        )
        backend_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in (root / "backend").rglob("*")
            if path.is_file()
            and "node_modules" not in path.parts
            and "tests" not in path.parts
            and path.suffix in {".js", ".mjs", ".py", ".ts"}
        )
        frontend_port = int(contract.get("frontend_port", 5173))
        frontend_config_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in (root / "frontend").glob("*")
            if path.is_file() and path.suffix in {".js", ".json", ".ts"}
        )
        if frontend_port != 5173 and str(frontend_port) not in frontend_config_text:
            report.passed = False
            report.retry_targets = [WorkerKind.FRONTEND]
            report.failure_reason = (
                f"Frontend configuration does not use contracted port {frontend_port}."
            )
            return
        missing_route_references: list[str] = []
        for route in routes:
            path = str(route.get("path", ""))
            method = str(route.get("method", "GET")).upper()
            if _is_operational_route(route):
                continue
            direct_reference = bool(path) and _frontend_references_route(
                frontend_text, path
            )
            hypermedia_reference = bool(path) and _frontend_consumes_contract_url(
                frontend_text,
                path,
                routes,
            )
            if not direct_reference and not hypermedia_reference:
                missing_route_references.append(path or "<empty route>")
                continue
            referenced_methods = (
                _frontend_route_methods(frontend_text, path) if direct_reference else set()
            )
            if direct_reference and referenced_methods and method not in referenced_methods:
                report.passed = False
                report.retry_targets = [WorkerKind.FRONTEND]
                report.failure_reason = (
                    f"Frontend uses {sorted(referenced_methods)} for {path}; "
                    f"the shared contract requires {method}."
                )
                return
            query_parameters = [
                name for name, _ in parse_qsl(urlsplit(path).query, keep_blank_values=True)
            ]
            missing_frontend_query = [
                name
                for name in query_parameters
                if not _frontend_references_query_parameter(frontend_text, name)
            ]
            if missing_frontend_query:
                report.passed = False
                report.retry_targets = [WorkerKind.FRONTEND]
                report.failure_reason = (
                    f"Frontend does not use contracted query parameters "
                    f"{missing_frontend_query} for {path}."
                )
                return
            missing_backend_query = [
                name
                for name in query_parameters
                if not _backend_references_query_parameter(backend_text, name)
            ]
            if missing_backend_query:
                report.passed = False
                report.retry_targets = [WorkerKind.BACKEND]
                report.failure_reason = (
                    f"Backend does not accept contracted query parameters "
                    f"{missing_backend_query} for {path}."
                )
                return
            if method != "GET" and method not in frontend_text.upper():
                report.passed = False
                report.retry_targets = [WorkerKind.FRONTEND]
                report.failure_reason = (
                    f"Frontend does not reference contracted HTTP method {method} for {path}."
                )
                return
            request_example = route.get("request_example")
            if isinstance(request_example, dict):
                missing_request_fields = [
                    field
                    for field in request_example
                    if not _frontend_implements_request_field(frontend_text, field)
                ]
                if missing_request_fields:
                    report.passed = False
                    report.retry_targets = [WorkerKind.FRONTEND]
                    report.failure_reason = (
                        f"Frontend does not implement request fields {missing_request_fields} "
                        f"for {method} {path}."
                    )
                    return
            response_example = route.get("response_example")
            if isinstance(response_example, dict) and len(response_example) == 1:
                wrapper, wrapped_value = next(iter(response_example.items()))
                if isinstance(wrapped_value, (dict, list)) and wrapper not in frontend_text:
                    report.passed = False
                    report.retry_targets = [WorkerKind.FRONTEND]
                    report.failure_reason = (
                        f"Frontend does not handle response wrapper {wrapper!r} "
                        f"for {method} {path}."
                    )
                    return
        if missing_route_references:
            report.passed = False
            report.retry_targets = [WorkerKind.FRONTEND]
            report.failure_reason = (
                "Frontend does not reference contracted routes: "
                + ", ".join(missing_route_references)
                + "."
            )
            return
        report.checks.append("frontend_contract_reference")

        if temp_root is None:
            report.checks.append("backend_contract_workflow:covered_by_docker_tests")
            return
        if (root / "backend" / "package.json").exists():
            # The Python contract harness cannot import a Node backend; its own test
            # and build steps already exercised the contract.
            report.checks.append("backend_contract_workflow:covered_by_node_tests")
            return

        backend = root / "backend"
        venv = temp_root / "backend-venv"
        python = venv / "bin" / "python"
        if not python.exists():
            python = venv / "Scripts" / "python.exe"
        script = temp_root / "contract_check.py"
        script.write_text(
            _contract_check_script(_backend_module(root), contract),
            encoding="utf-8",
        )
        self._run(
            report,
            name="backend_contract_workflow",
            worker_kind=None,
            command=[str(python), str(script)],
            cwd=backend,
            extra_env=_python_path_env(backend),
            retry_targets=[WorkerKind.BACKEND, WorkerKind.FRONTEND],
        )

    def _run(
        self,
        report: ProjectValidationReport,
        *,
        name: str,
        worker_kind: WorkerKind | None,
        command: list[str],
        cwd: Path,
        extra_env: dict[str, str] | None = None,
        retry_targets: list[WorkerKind] | None = None,
        allow_network: bool = False,
        blocking: bool = True,
        phase: str = "execution",
        failure_kind: str = "application",
        timeout_seconds: int | None = None,
        infrastructure_retries: int = 0,
        infrastructure_failure_is_advisory: bool = False,
        incomplete_blocks_release: bool = False,
    ) -> ValidationCommandResult:
        import time

        command_timeout = timeout_seconds or self._settings.artifact_validation_timeout_seconds
        result: ValidationCommandResult | None = None
        infrastructure_failure = False
        for attempt in range(1, infrastructure_retries + 2):
            started = time.monotonic()
            timed_out = False
            try:
                completed = subprocess.run(
                    command,
                    cwd=cwd,
                    env=_validation_environment(extra_env, allow_network=allow_network),
                    capture_output=True,
                    text=True,
                    timeout=command_timeout,
                    check=False,
                )
                exit_code = completed.returncode
                stdout = completed.stdout
                stderr = completed.stderr
            except subprocess.TimeoutExpired as exc:
                _cleanup_timed_out_command(command)
                exit_code = None
                stdout = _to_text(exc.stdout)
                stderr = _to_text(exc.stderr) + "\nValidation command timed out."
                timed_out = True
            duration = time.monotonic() - started
            passed = exit_code == 0
            infrastructure_failure = timed_out or _looks_like_infrastructure_failure(
                stdout,
                stderr,
            )
            result = ValidationCommandResult(
                name=name,
                worker_kind=worker_kind,
                command=shlex.join(command),
                cwd=str(cwd),
                passed=passed,
                exit_code=exit_code,
                duration_seconds=round(duration, 3),
                stdout_excerpt=_excerpt(stdout),
                stderr_excerpt=_excerpt(stderr),
                phase=phase,
                failure_kind=(
                    None if passed else "infrastructure" if infrastructure_failure else failure_kind
                ),
                blocking=blocking,
                timed_out=timed_out,
                attempt=attempt,
            )
            report.results.append(result)
            if passed:
                report.checks.append(f"{name}:passed")
                return result
            if infrastructure_failure and attempt <= infrastructure_retries:
                report.checks.append(f"{name}:infrastructure_retry_{attempt}")
                continue
            break

        assert result is not None
        if infrastructure_failure and infrastructure_failure_is_advisory:
            report.checks.append(f"{name}:infrastructure_advisory")
            if incomplete_blocks_release:
                report.release_ready = False
            report.advisories.append(
                {
                    "source": "validation",
                    "name": name,
                    "phase": phase,
                    "failure_kind": "infrastructure",
                    "message": (
                        f"{name} could not complete because its external dependency was "
                        "unavailable. Executable validation remains valid and no worker attempt "
                        "was consumed."
                    ),
                    "blocking_publication": incomplete_blocks_release,
                    "attempts": result.attempt,
                }
            )
            return result

        outcome = "failed" if blocking else "advisory"
        report.checks.append(f"{name}:{outcome}")

        if not blocking:
            return result

        report.passed = False
        report.release_ready = False
        report.failure_kind = "infrastructure" if infrastructure_failure else failure_kind
        targets = (
            []
            if infrastructure_failure
            else retry_targets or ([worker_kind] if worker_kind else [])
        )
        report.retry_targets = list(dict.fromkeys([*report.retry_targets, *targets]))
        diagnostic_output = "\n".join(
            output for output in (result.stdout_excerpt, result.stderr_excerpt) if output
        )
        report.failure_reason = (
            f"{name} failed with exit code {result.exit_code}: {diagnostic_output or 'no output'}"
        )
        return result

    @staticmethod
    def _clean_validation_outputs(root: Path) -> None:
        for path in (
            root / "frontend" / "node_modules",
            root / "frontend" / "dist",
            root / "frontend" / ".next",
            root / "backend" / "node_modules",
            root / "backend" / "dist",
            root / "backend" / ".pytest_cache",
        ):
            if path.exists():
                shutil.rmtree(path)
        for path in root.rglob("__pycache__"):
            if path.is_dir():
                shutil.rmtree(path)
        for path in root.rglob("*.egg-info"):
            if path.is_dir():
                shutil.rmtree(path)
        for path in root.rglob("*.pyc"):
            path.unlink(missing_ok=True)


def _backend_manifest_findings(
    files: dict[str, Path],
    text_files: dict[str, str],
    project_spec: ProjectSpec,
) -> list[str]:
    findings: list[str] = []
    if "backend/setup.py" in files:
        findings.append(
            "backend/setup.py is not allowed because generated setup code is executable."
        )

    requirements = text_files.get("backend/requirements.txt")
    if requirements is not None:
        for line in requirements.splitlines():
            requirement = line.strip()
            if not requirement or requirement.startswith("#"):
                continue
            if requirement.startswith(("-e ", "--", "git+", "http://", "https://")):
                findings.append(
                    f"backend/requirements.txt contains unsupported install source {requirement!r}."
                )
                continue
            if not PYTHON_EXACT_VERSION.match(requirement):
                findings.append(
                    "backend/requirements.txt direct dependencies must use exact == versions: "
                    f"{requirement!r}."
                )

    backend_runtime = "\n".join(
        content
        for path, content in text_files.items()
        if path.startswith("backend/") and _is_runtime_security_path(path)
    )
    backend_source = "\n".join(
        content
        for path, content in text_files.items()
        if path.startswith("backend/")
        and PurePath(path).suffix in {".js", ".mjs", ".py", ".ts"}
        and _is_runtime_security_path(path)
    )
    dependency_text = "\n".join(
        text_files.get(path, "")
        for path in ("backend/requirements.txt", "backend/pyproject.toml")
    )
    if any(
        marker in backend_runtime
        for marker in (
            "sqlalchemy.ext.asyncio",
            "AsyncSession",
            "async_sessionmaker",
            "create_async_engine",
        )
    ) and not re.search(
        r"(?<![A-Za-z0-9_.-])greenlet(?:\[[^\]\r\n]+\])?==[^\"'\s,]+",
        dependency_text,
    ):
        findings.append(
            "Async SQLAlchemy backends must declare the certified greenlet runtime dependency."
        )

    seed_text = "\n".join(
        content
        for path, content in text_files.items()
        if path.startswith("database/")
        and ("/seed/" in path or "/seeds/" in path or PurePath(path).name.startswith("seed"))
    )
    if (
        (
            re.search(r"\$2[aby]\$\d{2}\$", seed_text)
            or re.search(
                r"gen_salt\s*\(\s*['\"]bf['\"]\s*\)",
                seed_text,
                re.IGNORECASE,
            )
        )
        and "PasswordHash.recommended" in backend_runtime
        and "BcryptHasher" not in backend_runtime
    ):
        findings.append(
            "Bcrypt seed passwords are incompatible with PasswordHash.recommended alone; "
            "configure pwdlib with BcryptHasher and Argon2Hasher or emit compatible seeds."
        )

    if project_spec.frontend_framework and project_spec.backend_framework == "FastAPI":
        if not re.search(
            r"add_middleware\s*\(\s*CORSMiddleware",
            backend_runtime,
            re.DOTALL,
        ):
            findings.append(
                "FastAPI full-stack backends must install CORSMiddleware for the generated frontend."
            )
        elif not re.search(r"\bCORS_ORIGINS?\b", backend_source):
            findings.append(
                "FastAPI CORS must consume the documented CORS_ORIGINS setting at runtime; "
                "fixed localhost origins do not satisfy dynamic preview or deployment ports."
            )
    pyproject_text = text_files.get("backend/pyproject.toml")
    if pyproject_text is None:
        return findings
    try:
        pyproject = tomllib.loads(pyproject_text)
    except tomllib.TOMLDecodeError as exc:
        findings.append(f"backend/pyproject.toml is invalid TOML: {exc}.")
        return findings

    build_backend = str(pyproject.get("build-system", {}).get("build-backend", ""))
    if build_backend not in {
        "flit_core.buildapi",
        "hatchling.build",
        "setuptools.build_meta",
    }:
        findings.append(
            "backend/pyproject.toml must use an allowlisted build backend "
            "(hatchling, setuptools, or flit)."
        )
    dependency_groups = [
        pyproject.get("project", {}).get("dependencies", []),
        *pyproject.get("project", {}).get("optional-dependencies", {}).values(),
    ]
    for dependency in (
        item
        for group in dependency_groups
        if isinstance(group, list)
        for item in group
        if isinstance(item, str)
    ):
        if not PYTHON_EXACT_VERSION.match(dependency.strip()):
            findings.append(
                "backend/pyproject.toml direct dependencies must use exact == versions: "
                f"{dependency!r}."
            )
    return findings


def _is_runtime_security_path(path: str) -> bool:
    normalized = path.lower()
    name = PurePath(normalized).name
    return not (
        normalized.startswith(("artifacts/", "docs/"))
        or normalized == "readme.md"
        or "/tests/" in f"/{normalized}"
        or "/test/" in f"/{normalized}"
        or "/fixtures/" in f"/{normalized}"
        or name.startswith(("seed.", "fixture."))
        or name.startswith("test_")
        and name.endswith(".py")
        or name.endswith("_test.py")
        or any(marker in name for marker in (".test.", ".spec.", "_test."))
    )


def _is_peer_resolution_crash(result: ValidationCommandResult) -> bool:
    combined = f"{result.stdout_excerpt}\n{result.stderr_excerpt}".lower()
    return "edgesout" in combined


def _looks_like_infrastructure_failure(stdout: str, stderr: str) -> bool:
    combined = f"{stdout}\n{stderr}".lower()
    return any(pattern in combined for pattern in INFRASTRUCTURE_FAILURE_PATTERNS)


def _docker_mount_path(path: Path) -> str:
    resolved = str(path.resolve())
    if sys.platform == "darwin" and resolved.startswith("/private/var/"):
        return resolved.removeprefix("/private")
    return resolved


def _cleanup_timed_out_command(command: list[str]) -> None:
    if not command or Path(command[0]).name != "docker" or "--name" not in command:
        return
    name_index = command.index("--name") + 1
    if name_index >= len(command):
        return
    try:
        subprocess.run(
            [command[0], "rm", "-f", command[name_index]],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return


def _frontend_manifest_findings(text_files: dict[str, str]) -> list[str]:
    """Backward-compatible frontend manifest validation used by focused unit tests."""

    return _node_manifest_findings(
        "frontend",
        text_files,
        resolve_project_spec("Build a React frontend"),
    )


def _frontend_test_contract_findings(text_files: dict[str, str]) -> list[str]:
    package_text = text_files.get("frontend/package.json", "")
    if "vitest" not in package_text.lower():
        return []
    findings: list[str] = []
    bare_jest_dom_import = re.compile(
        r"import\s+['\"]@testing-library/jest-dom['\"]\s*;?"
    )
    for path, content in text_files.items():
        if not path.startswith("frontend/") or PurePath(path).suffix.lower() not in {
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
        }:
            continue
        if bare_jest_dom_import.search(content):
            findings.append(
                f"{path} must import @testing-library/jest-dom/vitest when Vitest is used."
            )
    return findings


def _frontend_runtime_connectivity_findings(
    text_files: dict[str, str],
    project_spec: ProjectSpec,
) -> list[str]:
    if not (
        project_spec.frontend_framework
        and project_spec.backend_framework
        and "backend" in project_spec.ports
    ):
        return []
    hardcoded_local_url = re.compile(
        r"(?:https?|wss?)://(?:localhost|127\.0\.0\.1)(?::\d+)?",
        re.IGNORECASE,
    )
    findings: list[str] = []
    for path, content in text_files.items():
        name = PurePath(path).name.lower()
        if (
            not path.startswith("frontend/")
            or PurePath(path).suffix.lower() not in {".js", ".jsx", ".mjs", ".ts", ".tsx"}
            or not _is_runtime_security_path(path)
            or name.endswith((".config.js", ".config.mjs", ".config.ts"))
        ):
            continue
        if hardcoded_local_url.search(content):
            findings.append(
                f"{path} hardcodes a localhost runtime URL. Use relative same-origin routes or "
                "api_contract.runtime_connectivity.frontend_api_env so dynamic preview, CORS, "
                "WebSocket, upload, and streaming endpoints remain portable."
            )
    return findings


def _backend_runtime_connectivity_findings(
    text_files: dict[str, str],
    project_spec: ProjectSpec,
) -> list[str]:
    if not (
        project_spec.frontend_framework
        and project_spec.backend_framework == "Express"
    ):
        return []
    backend_runtime = "\n".join(
        content
        for path, content in text_files.items()
        if path.startswith("backend/") and _is_runtime_security_path(path)
    )
    if not re.search(r"\bcors\s*\(", backend_runtime, re.IGNORECASE):
        return [
            "Express full-stack backends must install and configure CORS middleware for the "
            "generated frontend."
        ]
    if not re.search(r"\bCORS_ORIGINS?\b", backend_runtime):
        return [
            "Express CORS must consume the documented CORS_ORIGINS setting at runtime; "
            "fixed localhost origins do not satisfy dynamic preview or deployment ports."
        ]
    return []


def _node_manifest_findings(
    component: str,
    text_files: dict[str, str],
    project_spec: ProjectSpec,
) -> list[str]:
    findings: list[str] = []
    package_path = f"{component}/package.json"
    lock_path = f"{component}/package-lock.json"
    package_text = text_files.get(package_path)
    lock_text = text_files.get(lock_path)
    if package_text is None:
        return findings
    try:
        package = json.loads(package_text)
    except json.JSONDecodeError as exc:
        return [f"{package_path} is invalid JSON: {exc}."]
    if not isinstance(package, dict):
        return [f"{package_path} must contain a JSON object."]

    for group_name in ("dependencies", "devDependencies", "optionalDependencies"):
        dependencies = package.get(group_name, {})
        if not isinstance(dependencies, dict):
            findings.append(f"{package_path} {group_name} must be an object.")
            continue
        for dependency, version in dependencies.items():
            if not isinstance(version, str) or not NPM_EXACT_VERSION.match(version.strip()):
                findings.append(
                    f"{component} dependency {dependency!r} must use an exact version, not {version!r}."
                )

    scripts = package.get("scripts", {})
    if not isinstance(scripts, dict):
        findings.append(f"{package_path} scripts must be an object.")
        scripts = {}
    for required_script in ("test", "build"):
        script = scripts.get(required_script)
        if not isinstance(script, str) or not script.strip():
            findings.append(
                f"{component.title()} package.json must define a {required_script} script."
            )
            continue
        if not _is_safe_npm_script(script, _allowed_npm_commands(project_spec)):
            findings.append(
                f"{component.title()} {required_script} script contains an unsupported command: "
                f"{script!r}."
            )

    if lock_text is not None:
        try:
            lock = json.loads(lock_text)
        except json.JSONDecodeError as exc:
            findings.append(f"{lock_path} is invalid JSON: {exc}.")
        else:
            if not isinstance(lock, dict) or int(lock.get("lockfileVersion", 0)) < 2:
                findings.append(f"{lock_path} must use lockfileVersion 2 or newer.")
            root_package = lock.get("packages", {}).get("", {}) if isinstance(lock, dict) else {}
            if isinstance(root_package, dict):
                for key in ("name", "version"):
                    if package.get(key) != root_package.get(key):
                        findings.append(f"{lock_path} root {key} does not match package.json.")
    return findings


def _allowed_npm_commands(project_spec: ProjectSpec) -> frozenset[str]:
    capability = resolve_capability(project_spec.capability_id)
    return capability.allowed_npm_commands or COMMON_NPM_COMMANDS


def _is_safe_npm_script(
    script: str,
    allowed_commands: frozenset[str] = COMMON_NPM_COMMANDS,
) -> bool:
    if re.search(r"[|;><`$]", script):
        return False
    for segment in re.split(r"\s*&&\s*", script):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            return False
        if not tokens or tokens[0] not in allowed_commands:
            return False
    return True


def _is_frontend_test_file(path: str) -> bool:
    return _is_component_test_file(path, "frontend")


def _is_component_test_file(path: str, component: str) -> bool:
    if not path.startswith(f"{component}/"):
        return False
    name = PurePath(path).name.lower()
    if name.startswith("test_") and name.endswith(".py"):
        return True
    if name.endswith("_test.py"):
        return True
    return any(
        marker in name
        for marker in (
            ".test.cjs",
            ".test.js",
            ".test.jsx",
            ".test.mjs",
            ".test.ts",
            ".test.tsx",
            ".spec.cjs",
            ".spec.js",
            ".spec.jsx",
            ".spec.mjs",
            ".spec.ts",
            ".spec.tsx",
        )
    )


def _readme_consistency_findings(files: dict[str, Path], readme: str) -> list[str]:
    findings: list[str] = []
    normalized = readme.lower()
    if "backend/requirements.txt" in files:
        if "pip install -r requirements.txt" not in normalized:
            findings.append("README.md must install backend/requirements.txt with pip install -r.")
        if "pip install ." in normalized or "pip install -e ." in normalized:
            findings.append(
                "README.md documents pyproject installation but backend uses requirements.txt."
            )
    if "backend/pyproject.toml" in files:
        if not _documents_pyproject_install(normalized):
            findings.append("README.md must install the backend from backend/pyproject.toml.")
        if "pip install -r requirements" in normalized:
            findings.append(
                "README.md references requirements.txt but backend uses pyproject.toml."
            )
    if (
        any(path.startswith("backend/") for path in files)
        and "pytest" not in normalized
        and "backend/package.json" not in files
    ):
        findings.append("README.md is missing the backend test command.")
    if "backend/package.json" in files:
        if "npm ci" not in normalized:
            findings.append("README.md must use npm ci for the Node backend.")
        if "npm test" not in normalized:
            findings.append("README.md is missing the Node backend test command.")
        if "npm run build" not in normalized:
            findings.append("README.md is missing the Node backend build command.")
    if any(path.startswith("frontend/") for path in files):
        if "npm ci" not in normalized:
            findings.append("README.md must use npm ci with the generated package-lock.json.")
        if "npm test" not in normalized:
            findings.append("README.md is missing the frontend test command.")
        if "npm run build" not in normalized:
            findings.append("README.md is missing the frontend build command.")
    env_examples = sorted(path for path in files if PurePath(path).name == ".env.example")
    for env_example in env_examples:
        if env_example not in readme:
            findings.append(f"README.md does not document configuration file {env_example}.")
    return findings


def _documents_pyproject_install(readme: str) -> bool:
    return bool(
        re.search(
            r"pip\s+install\s+(?:-e\s+)?[\"']?\.(?:\[[^\]\r\n]+\])?[\"']?",
            readme,
        )
    )


def _documented_path_exists(referenced_path: str, files: dict[str, Path]) -> bool:
    if referenced_path in files:
        return True
    if referenced_path.endswith("/.env"):
        return f"{referenced_path}.example" in files
    if "/" in referenced_path:
        return False
    return any(
        f"{component}/{referenced_path}" in files
        for component in ("backend", "frontend", "database")
    )


def _configuration_findings(
    files: dict[str, Path],
    text_files: dict[str, str],
) -> list[str]:
    findings: list[str] = []
    for component in ("backend", "frontend"):
        references: set[str] = set()
        for path, content in text_files.items():
            if not path.startswith(f"{component}/") or PurePath(path).name.startswith(".env"):
                continue
            for pattern in ENVIRONMENT_REFERENCE_PATTERNS:
                references.update(pattern.findall(content))
        references.difference_update(STANDARD_ENVIRONMENT_VARIABLES)
        if not references:
            continue
        env_path = f"{component}/.env.example"
        if env_path not in files:
            findings.append(
                f"{component} references environment variables {sorted(references)} "
                f"but {env_path} is missing."
            )
            continue
        declared = {
            line.split("=", maxsplit=1)[0].strip()
            for line in text_files.get(env_path, "").splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        }
        missing = sorted(references - declared)
        if missing:
            findings.append(f"{env_path} is missing variables referenced by code: {missing}.")
    return findings


def _execution_safety_findings(text_files: dict[str, str]) -> list[str]:
    findings: list[str] = []
    for path, content in text_files.items():
        if not path.startswith(("backend/", "frontend/")):
            continue
        for label, pattern in UNSAFE_EXECUTION_PATTERNS.items():
            if pattern.search(content):
                if label == "destructive filesystem call" and not _is_runtime_security_path(path):
                    continue
                if label == "shell execution" and _is_safe_python_import_probe(path, content):
                    continue
                findings.append(f"{path} contains unsafe generated-code operation: {label}.")
    return findings


def _is_safe_python_import_probe(path: str, content: str) -> bool:
    name = PurePath(path).name.lower()
    if not path.endswith(".py") or not (
        "/tests/" in f"/{path.lower()}" or name.startswith("test_") or name.endswith("_test.py")
    ):
        return False
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return False
    subprocess_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
    ]
    if not subprocess_calls:
        return False
    for call in subprocess_calls:
        if call.func.attr != "run" or not call.args:
            return False
        command = call.args[0]
        if not isinstance(command, (ast.List, ast.Tuple)) or len(command.elts) != 3:
            return False
        executable, flag, script = command.elts
        if not (
            isinstance(executable, ast.Attribute)
            and isinstance(executable.value, ast.Name)
            and executable.value.id == "sys"
            and executable.attr == "executable"
            and isinstance(flag, ast.Constant)
            and flag.value == "-c"
            and isinstance(script, ast.Constant)
            and isinstance(script.value, str)
            and re.fullmatch(
                r"from\s+[A-Za-z_][A-Za-z0-9_.]*\s+import\s+app;\s*"
                r"assert\s+app\s+is\s+not\s+None",
                script.value.strip(),
            )
        ):
            return False
        shell = next((keyword.value for keyword in call.keywords if keyword.arg == "shell"), None)
        if shell is not None and not (isinstance(shell, ast.Constant) and shell.value is False):
            return False
    return True


def _backend_module(root: Path) -> str:
    candidates = (
        (root / "backend" / "src" / "app" / "main.py", "app.main"),
        (root / "backend" / "app" / "main.py", "app.main"),
        (root / "backend" / "main.py", "main"),
    )
    for path, module in candidates:
        if path.exists():
            return module
    raise ValueError("Unable to locate backend application entry point.")


def _python_path_env(backend: Path) -> dict[str, str]:
    candidates = [backend / "src", backend]
    return {"PYTHONPATH": os.pathsep.join(str(path) for path in candidates if path.exists())}


def _npm_executable() -> str:
    npm = shutil.which("npm")
    if npm:
        return npm
    for candidate in ("/opt/homebrew/bin/npm", "/usr/local/bin/npm"):
        if Path(candidate).exists():
            return candidate
    raise RuntimeError("npm is required for frontend validation.")


def _validation_environment(
    extra: dict[str, str] | None = None,
    *,
    allow_network: bool = False,
) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in SECRET_ENV_MARKERS)
    }
    environment.update(
        {
            "CI": "true",
            "NO_COLOR": "1",
            "NPM_CONFIG_FUND": "false",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    if not allow_network:
        unavailable_proxy = "http://127.0.0.1:9"
        environment.update(
            {
                "ALL_PROXY": unavailable_proxy,
                "HTTP_PROXY": unavailable_proxy,
                "HTTPS_PROXY": unavailable_proxy,
                "NO_PROXY": "",
                "all_proxy": unavailable_proxy,
                "http_proxy": unavailable_proxy,
                "https_proxy": unavailable_proxy,
                "no_proxy": "",
            }
        )
    if extra:
        environment.update(extra)
    return environment


def _synthetic_smoke_environment(component: Path) -> dict[str, str]:
    env_example = component / ".env.example"
    if not env_example.exists():
        return {}
    names = {
        line.split("=", maxsplit=1)[0].strip()
        for line in env_example.read_text(encoding="utf-8", errors="replace").splitlines()
        if "=" in line
        and line.split("=", maxsplit=1)[0].strip()
        and not line.lstrip().startswith("#")
    }
    values: dict[str, str] = {}
    for name in names:
        upper = name.upper()
        if upper == "DATABASE_URL":
            values[name] = (
                "postgresql+psycopg://validator:validator@127.0.0.1:5432/validator"
            )
        elif upper.endswith(("_URL", "_ORIGIN")):
            values[name] = "http://127.0.0.1:9"
        elif any(marker in upper for marker in ("KEY", "PASSWORD", "SECRET", "TOKEN")):
            values[name] = "validation-only-not-a-real-secret-0123456789abcdef0123456789abcdef"
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
        elif upper.startswith(("ENABLE_", "IS_")) or upper.endswith(
            ("_ENABLED", "_SECURE")
        ):
            values[name] = "false"
        else:
            values[name] = "validation"
    return values


def _backend_health_script(module: str) -> str:
    return (
        "from fastapi.testclient import TestClient\n"
        f"from {module} import app\n"
        "paths = {getattr(route, 'path', '') for route in app.routes}\n"
        "health_path = '/api/health' if '/api/health' in paths else '/health'\n"
        "assert health_path in paths, sorted(paths)\n"
        "with TestClient(app) as client:\n"
        "    response = client.get(health_path)\n"
        "    assert response.status_code == 200, (response.status_code, response.text)\n"
        "print('health workflow passed')\n"
    )


def _contract_check_script(module: str, contract: dict[str, Any]) -> str:
    return (
        "import json\n"
        "from fastapi.testclient import TestClient\n"
        f"from {module} import app\n"
        f"contract = json.loads({json.dumps(contract)!r})\n"
        "def assert_shape(expected, actual, location='response'):\n"
        "    if isinstance(expected, dict):\n"
        "        assert isinstance(actual, dict), (location, expected, actual)\n"
        "        for key, value in expected.items():\n"
        "            assert key in actual, (location, key, actual)\n"
        "            assert_shape(value, actual[key], f'{location}.{key}')\n"
        "    elif isinstance(expected, list):\n"
        "        assert isinstance(actual, list), (location, expected, actual)\n"
        "        if expected:\n"
        "            assert actual, (location, expected, actual)\n"
        "            assert_shape(expected[0], actual[0], f'{location}[0]')\n"
        "    elif expected is not None:\n"
        "        assert isinstance(actual, type(expected)), (location, type(expected), type(actual))\n"
        "with TestClient(app) as client:\n"
        "    for route in contract.get('routes', []):\n"
        "        kwargs = {}\n"
        "        if route.get('request_example') is not None:\n"
        "            kwargs['json'] = route['request_example']\n"
        "        response = client.request(route.get('method', 'GET'), route['path'], **kwargs)\n"
        "        expected = int(route.get('success_status', 200))\n"
        "        assert response.status_code == expected, (route, response.status_code, response.text)\n"
        "        expected_body = route.get('response_example')\n"
        "        if expected_body is not None:\n"
        "            assert_shape(expected_body, response.json())\n"
        "print('contract workflow passed')\n"
    )


def _validation_worker_order(job: JobState) -> list[WorkerKind]:
    default = [WorkerKind.BACKEND, WorkerKind.FRONTEND]
    targeted = [worker for worker in default if job.active_repair_ticket(worker)]
    return [*targeted, *(worker for worker in default if worker not in targeted)]


def _workers_for_path(path: str) -> set[WorkerKind]:
    if path.startswith("backend/"):
        return {WorkerKind.BACKEND}
    if path.startswith("frontend/"):
        return {WorkerKind.FRONTEND}
    if path.startswith("database/"):
        return {WorkerKind.DATABASE}
    return {WorkerKind.BACKEND, WorkerKind.FRONTEND}


def _frontend_route_methods(frontend_text: str, route_path: str) -> set[str]:
    expanded_text = _expand_static_route_aliases(frontend_text)
    methods: set[str] = set()
    for match in _frontend_route_matches(expanded_text, route_path):
        window = _enclosing_call(expanded_text, match.start())
        if window is None:
            continue
        explicit_methods: set[str] = set()
        for method_match in re.finditer(
            r"\bmethod\s*:\s*['\"](GET|POST|PUT|PATCH|DELETE)['\"]",
            window,
            flags=re.IGNORECASE,
        ):
            explicit_methods.add(method_match.group(1).upper())
        if explicit_methods:
            methods.update(explicit_methods)
            continue
        wrapper_methods = _frontend_call_wrapper_methods(expanded_text, match.start())
        methods.update(wrapper_methods or {"GET"})
    return methods


def _frontend_call_wrapper_methods(source: str, route_offset: int) -> set[str]:
    opening = source.rfind("(", max(0, route_offset - 200), route_offset)
    if opening < 0:
        return set()
    callee_match = re.search(r"([A-Za-z_$][A-Za-z0-9_$]*)\s*$", source[:opening])
    if callee_match is None:
        return set()
    callee = callee_match.group(1)
    if callee in {"fetch", "axios"}:
        return set()
    declaration_patterns = (
        re.compile(
            rf"(?:async\s+)?function\s+{re.escape(callee)}(?:\s*<[^>]+>)?\s*"
            r"\([^)]*\)\s*"
            r"(?:\s*:\s*[^\{=]+)?\s*\{"
        ),
        re.compile(
            rf"(?:const|let|var)\s+{re.escape(callee)}\s*=\s*"
            r"(?:async\s*)?\([^)]*\)\s*(?:\s*:\s*[^=]+)?=>\s*\{"
        ),
    )
    methods: set[str] = set()
    for pattern in declaration_patterns:
        for declaration in pattern.finditer(source):
            block = _enclosing_brace_block(source, declaration.end() - 1)
            if block is None:
                continue
            methods.update(
                match.group(1).upper()
                for match in re.finditer(
                    r"\bmethod\s*:\s*['\"](GET|POST|PUT|PATCH|DELETE)['\"]",
                    block,
                    flags=re.IGNORECASE,
                )
            )
    return methods


def _enclosing_brace_block(source: str, opening: int) -> str | None:
    if opening < 0 or opening >= len(source) or source[opening] != "{":
        return None
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(opening, len(source)):
        character = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"', "`"}:
            quote = character
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[opening : index + 1]
    return None


def _enclosing_call(source: str, offset: int) -> str | None:
    opening = source.rfind("(", max(0, offset - 200), offset)
    if opening < 0:
        return None
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(opening, len(source)):
        character = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"', "`"}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                if index < offset:
                    return None
                return source[opening : index + 1]
    return None


def _frontend_references_route(frontend_text: str, route_path: str) -> bool:
    expanded_text = _expand_static_route_aliases(frontend_text)
    return next(_frontend_route_matches(expanded_text, route_path), None) is not None


def _frontend_consumes_contract_url(
    frontend_text: str,
    route_path: str,
    routes: list[dict[str, Any]],
) -> bool:
    for route in routes:
        for field_name, value in _response_string_fields(route.get("response_example")):
            if (
                field_name
                and field_name in frontend_text
                and _contract_url_matches_route(value, route_path)
            ):
                return True
    return False


def _response_string_fields(value: Any, field: str = ""):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield from _response_string_fields(nested, str(key))
    elif isinstance(value, list):
        for nested in value:
            yield from _response_string_fields(nested, field)
    elif isinstance(value, str):
        yield field, value


def _contract_url_matches_route(value: str, route_path: str) -> bool:
    candidate_path = urlsplit(value).path
    expected_path = route_path.split("?", maxsplit=1)[0]
    route_pattern = re.escape(expected_path)
    route_pattern = re.sub(r"\\\{[^{}]+\\\}", r"[^/]+", route_pattern)
    return re.fullmatch(route_pattern, candidate_path) is not None


def _frontend_route_matches(frontend_text: str, route_path: str):
    route_pattern = re.escape(route_path.split("?", maxsplit=1)[0])
    route_pattern = re.sub(
        r"\\\{[^{}]+\\\}",
        r"(?:[^'\"`$/{]+|\\$\\{[^}]+\\})",
        route_pattern,
    )
    return re.finditer(route_pattern + r"(?![A-Za-z0-9_/-])", frontend_text)


def _frontend_references_query_parameter(frontend_text: str, name: str) -> bool:
    escaped = re.escape(name)
    patterns = (
        rf"[?&]{escaped}\s*=",
        rf"\.(?:append|set)\(\s*['\"]{escaped}['\"]",
        rf"['\"]{escaped}['\"]\s*:",
        rf"\b{escaped}\s*:\s*[^,}}]+",
    )
    return any(re.search(pattern, frontend_text) for pattern in patterns)


def _frontend_implements_request_field(frontend_text: str, field: str) -> bool:
    normalized = field.strip().lower()
    if normalized in {"form_data", "formdata", "multipart", "multipart_form_data"}:
        return bool(re.search(r"\bFormData\s*\(", frontend_text))
    return field in frontend_text


def _backend_references_query_parameter(backend_text: str, name: str) -> bool:
    escaped = re.escape(name)
    alias_patterns = (
        rf"alias\s*=\s*['\"]{escaped}['\"]",
        rf"validation_alias\s*=\s*['\"]{escaped}['\"]",
        rf"(?:query|searchParams)\.(?:get|has)\(\s*['\"]{escaped}['\"]",
        rf"(?:query|searchParams)\[['\"]{escaped}['\"]\]",
        rf"(?:query|searchParams)\.{escaped}\b",
    )
    if any(re.search(pattern, backend_text) for pattern in alias_patterns):
        return True
    if keyword.iskeyword(name):
        return False
    return re.search(rf"\b{escaped}\s*(?::|=|,|\))", backend_text) is not None


def _expand_static_route_aliases(source: str) -> str:
    aliases: dict[str, str] = {}
    declarations = re.finditer(
        r"\bconst\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?P<value>[^;]+);",
        source,
    )
    for declaration in declarations:
        value = _static_string_value(declaration.group("value").strip(), aliases)
        if value is not None:
            aliases[declaration.group("name")] = value

    expanded = source
    for name, value in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        expanded = re.sub(
            rf"\$\{{\s*{re.escape(name)}\s*\}}",
            lambda _, replacement=value: replacement,
            expanded,
        )
        expanded = re.sub(
            rf"(?<![A-Za-z0-9_$]){re.escape(name)}(?![A-Za-z0-9_$])",
            lambda _, replacement=value: json.dumps(replacement),
            expanded,
        )
    return expanded


def _static_string_value(expression: str, aliases: dict[str, str]) -> str | None:
    if len(expression) < 2 or expression[0] not in {"'", '"', "`"}:
        return None
    quote = expression[0]
    if expression[-1] != quote:
        return None
    value = expression[1:-1]

    def join_array(match: re.Match[str]) -> str:
        items = re.findall(r"['\"]([^'\"]+)['\"]", match.group("items"))
        return match.group("separator").join(items)

    value = re.sub(
        r"\$\{\s*\[(?P<items>[^]]+)\]\.join\(\s*['\"]"
        r"(?P<separator>[^'\"]*)['\"]\s*\)\s*\}",
        join_array,
        value,
    )
    for name, resolved in aliases.items():
        value = re.sub(
            rf"\$\{{\s*{re.escape(name)}\s*\}}",
            lambda _, replacement=resolved: replacement,
            value,
        )
    if "${" in value:
        return None
    return value


def _is_operational_route(route: dict[str, Any]) -> bool:
    if route.get("frontend_required") is False:
        return True
    path = str(route.get("path", "")).rstrip("/") or "/"
    return path in {
        "/health",
        "/api/health",
        "/ready",
        "/readiness",
        "/live",
        "/liveness",
        "/metrics",
        "/docs",
        "/openapi.json",
    }


def _persistence_integration_findings(
    text_files: dict[str, str],
    project_spec: ProjectSpec,
) -> list[str]:
    requested = set(project_spec.requested_features)
    if not requested.intersection({"database", "persistence"}):
        return []
    backend_runtime = "\n".join(
        content
        for path, content in text_files.items()
        if path.startswith("backend/")
        and not _is_component_test_file(path, "backend")
        and PurePath(path).name
        not in {".env", ".env.example", "requirements.txt", "pyproject.toml", "package.json"}
    )
    normalized = backend_runtime.lower()
    connection_markers = (
        "database_url",
        "create_client(",
        "create_engine(",
        "create_async_engine(",
        "psycopg.connect(",
        "asyncpg.connect(",
        "prisma",
        "mongoose.connect(",
        "mongodb",
    )
    if any(marker in normalized for marker in connection_markers):
        return []
    return [
        (
            "The request requires database persistence, but backend runtime code does not "
            "configure or open a database connection."
        )
    ]


def _migration_ownership_findings(files: dict[str, Path]) -> list[str]:
    database_migrations = {
        path
        for path in files
        if path.startswith("database/migrations/") and path.endswith(".sql")
    }
    backend_migrations = {
        path
        for path in files
        if path.startswith(("backend/alembic/versions/", "backend/migrations/"))
        and path.endswith((".py", ".sql"))
    }
    if not database_migrations or not backend_migrations:
        return []
    return [
        (
            "The database worker already owns executable migrations, but the backend also generated "
            "a second migration system. Remove backend migration artifacts and make runtime models "
            "consume the canonical database/ schema."
        )
    ]


def _excerpt(value: str, limit: int = 4_000) -> str:
    stripped = ANSI_ESCAPE_PATTERN.sub("", value).strip()
    if len(stripped) <= limit:
        return stripped
    lines = stripped.splitlines()
    selected = set(range(min(8, len(lines))))
    selected.update(range(max(0, len(lines) - 8), len(lines)))
    for index, line in enumerate(lines):
        if not DIAGNOSTIC_LINE_PATTERN.search(line):
            continue
        selected.update(range(max(0, index - 1), min(len(lines), index + 3)))
    compact = "\n".join(lines[index] for index in sorted(selected)).strip()
    if len(compact) <= limit:
        return compact
    head = limit // 2
    tail = limit - head
    return f"{compact[:head]}\n...[diagnostic output compacted]...\n{compact[-tail:]}"


def _to_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
