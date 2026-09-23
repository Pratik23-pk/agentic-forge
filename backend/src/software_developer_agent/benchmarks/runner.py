from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from software_developer_agent.artifacts.project_generator import ProjectArtifactGenerator
from software_developer_agent.capabilities.models import ProjectSpec
from software_developer_agent.capabilities.registry import (
    required_workers,
    resolve_capability,
    resolve_project_spec,
)
from software_developer_agent.config.settings import Settings
from software_developer_agent.models.job_state import (
    JobRequest,
    JobState,
    JobStatus,
    JobTask,
    ReleaseStatus,
)
from software_developer_agent.models.request_policy import derive_request_policy
from software_developer_agent.orchestration.state_machine import AgentRuntime


@dataclass(slots=True)
class BenchmarkCaseResult:
    case_id: str
    capability_id: str
    passed: bool
    score: float
    checks: list[str] = field(default_factory=list)
    failure_reason: str | None = None
    file_count: int = 0
    content_digest: str = ""
    duration_seconds: float = 0.0
    job_status: str | None = None
    release_status: str | None = None
    worker_attempts: dict[str, int] = field(default_factory=dict)
    fallback_workers: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    artifact_available: bool = False
    artifact_path: str | None = None
    repair_rejections: dict[str, int] = field(default_factory=dict)
    loop_count: int = 0
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    repair_tickets: list[dict[str, Any]] = field(default_factory=list)
    final_evaluation: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BenchmarkReport:
    mode: str
    passed: bool
    average_score: float
    repeatable: bool
    cases: list[BenchmarkCaseResult]
    generated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "passed": self.passed,
            "average_score": self.average_score,
            "repeatable": self.repeatable,
            "cases": [asdict(case) for case in self.cases],
            "generated_at": self.generated_at,
        }


def run_benchmark(
    *,
    execute: bool = False,
    repeat: int = 2,
    case_ids: list[str] | None = None,
) -> BenchmarkReport:
    selected_ids = set(case_ids or [])
    cases = [
        case for case in _load_cases() if not selected_ids or str(case["case_id"]) in selected_ids
    ]
    if not cases:
        raise ValueError("No benchmark cases matched the requested case IDs.")
    runs = [[_run_case(case, execute=execute) for case in cases] for _ in range(repeat)]
    primary = runs[0]
    repeatable = repeat == 1 or all(
        result.content_digest == runs[0][index].content_digest
        for run in runs[1:]
        for index, result in enumerate(run)
    )
    average_score = round(sum(result.score for result in primary) / len(primary), 2)
    return BenchmarkReport(
        mode="certified_execution" if execute else "offline_structural",
        passed=all(result.passed for result in primary) and repeatable,
        average_score=average_score,
        repeatable=repeatable,
        cases=primary,
        generated_at=time.time(),
    )


def run_live_benchmark(case_ids: list[str] | None = None) -> BenchmarkReport:
    """Run selected category prompts through the complete configured agent workflow."""

    selected = [
        case for case in _load_cases() if case_ids is None or str(case["case_id"]) in set(case_ids)
    ]
    results = [_run_live_case(case) for case in selected]
    average_score = (
        round(
            sum(result.score for result in results) / len(results),
            2,
        )
        if results
        else 0.0
    )
    return BenchmarkReport(
        mode="live_agent_workflow",
        passed=bool(results) and all(result.passed for result in results),
        average_score=average_score,
        repeatable=False,
        cases=results,
        generated_at=time.time(),
    )


def _run_case(case: dict[str, Any], *, execute: bool) -> BenchmarkCaseResult:
    started = time.monotonic()
    capability_id = str(case["capability_id"])
    result = BenchmarkCaseResult(
        case_id=str(case["case_id"]),
        capability_id=capability_id,
        passed=False,
        score=0.0,
    )
    with tempfile.TemporaryDirectory(
        prefix=".agentic-forge-benchmark-",
        dir=Path.cwd(),
    ) as temp_dir:
        workspace = Path(temp_dir)
        settings = Settings(
            app_env="development" if execute else "test",
            artifacts_dir=workspace / "artifacts",
            generated_projects_dir=workspace / "generated",
            preview_cache_dir=workspace / "previews",
            enable_artifact_validation=execute,
            enable_domain_adapter_validation=not execute,
            enable_llm_calls=False,
            enable_human_checkpoints=False,
        )
        prompt = str(case["prompt"])
        project_id = str(case["project_id"])
        policy = derive_request_policy(prompt)
        spec = resolve_project_spec(prompt, {"capability_id": capability_id}, policy)
        job = JobState(
            job_id=f"benchmark-{case['case_id']}",
            request=JobRequest(
                prompt=prompt,
                project_id=project_id,
                metadata={"capability_id": capability_id},
            ),
            request_policy=policy.to_dict(),
            project_spec=spec.to_dict(),
        )
        job.tasks = [
            JobTask(
                worker_kind=worker,
                capability_id=capability_id,
                title=f"{worker.value.title()} benchmark",
                instructions=f"Generate the {capability_id} benchmark project.",
            )
            for worker in required_workers(spec, policy)
        ]
        try:
            artifacts = ProjectArtifactGenerator(settings).generate(job)
            folder_artifact = next(item for item in artifacts if item.kind == "folder")
            root = Path(folder_artifact.path)
            validation_payload = folder_artifact.metadata.get("validation", {})
            job.approval_state["benchmark_validation"] = validation_payload
            files = {
                path.relative_to(root).as_posix(): path
                for path in root.rglob("*")
                if path.is_file()
            }
            result.file_count = len(files)
            result.content_digest = _content_digest(root)
            result.score, result.checks = _score_case(case, spec, root, files, job)
            result.passed = result.score >= 12.0
            if not result.passed:
                result.failure_reason = str(
                    validation_payload.get("failure_reason")
                    or "Benchmark quality threshold of 12.0 was not met."
                )
        except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as exc:
            result.failure_reason = f"{type(exc).__name__}: {exc}"
    result.duration_seconds = round(time.monotonic() - started, 3)
    return result


def _run_live_case(case: dict[str, Any]) -> BenchmarkCaseResult:
    started = time.monotonic()
    result = BenchmarkCaseResult(
        case_id=str(case["case_id"]),
        capability_id=str(case["capability_id"]),
        passed=False,
        score=0.0,
    )
    with tempfile.TemporaryDirectory(
        prefix=".agentic-forge-live-benchmark-",
        dir=Path.cwd(),
    ) as temp_dir:
        workspace = Path(temp_dir)
        settings = Settings(
            app_env="development",
            artifacts_dir=workspace / "artifacts",
            generated_projects_dir=workspace / "generated",
            preview_cache_dir=workspace / "previews",
            enable_human_checkpoints=False,
            enable_persistence=False,
            enable_auto_preview=False,
        )
        job = JobState(
            request=JobRequest(
                prompt=str(case["prompt"]),
                project_id=str(case["project_id"]),
            )
        )
        try:
            AgentRuntime(settings).run_to_completion(job)
            folder = next((item for item in job.artifacts if item.kind == "folder"), None)
            result.artifact_available = folder is not None and Path(folder.path).is_dir()
            result.job_status = job.status.value
            result.release_status = job.release_status.value
            result.worker_attempts = {task.worker_kind.value: task.attempt for task in job.tasks}
            result.repair_rejections = {
                task.worker_kind.value: task.repair_rejections for task in job.tasks
            }
            result.fallback_workers = sorted(
                {
                    worker_result.worker_kind.value
                    for worker_result in job.worker_results
                    if worker_result.used_fallback
                }
            )
            result.cost_usd = float(job.cost_ledger.get("spent_usd", 0.0))
            result.loop_count = job.loop_count
            result.model_calls = [
                {
                    "node": call.get("node"),
                    "model": call.get("model"),
                    "cost_usd": call.get("cost_usd", 0.0),
                    "usage": call.get("usage", {}),
                }
                for call in job.cost_ledger.get("calls", [])
                if isinstance(call, dict)
            ]
            result.repair_tickets = [
                {
                    "worker_kind": ticket.worker_kind.value,
                    "source": ticket.source,
                    "category": ticket.category,
                    "occurrence": ticket.occurrence,
                    "strategy": ticket.strategy,
                    "summary": ticket.summary,
                    "resolved": ticket.resolved,
                }
                for ticket in job.repair_tickets
            ]
            if job.evaluation is not None:
                result.final_evaluation = {
                    "passed": job.evaluation.passed,
                    "decision": job.evaluation.decision,
                    "retry_targets": [
                        worker.value for worker in job.evaluation.retry_targets
                    ],
                    "failure_reason": job.evaluation.failure_reason,
                    "checks": job.evaluation.checks,
                    "warnings": job.evaluation.warnings,
                    "evidence": job.evaluation.evidence,
                }
            result.warnings = list(job.warnings[-5:])
            worker_errors = [
                f"{worker_result.worker_kind.value}: {error}"
                for worker_result in job.worker_results[-12:]
                for error in worker_result.errors[-2:]
            ]
            result.errors = [*job.errors, *worker_errors][-10:]
            if folder is not None and Path(folder.path).is_dir():
                job.approval_state["benchmark_validation"] = folder.metadata.get("validation", {})
                root = Path(folder.path)
                preserved_root = (
                    Path(__file__).resolve().parents[4]
                    / "benchmark-results"
                    / "live-artifacts"
                    / str(case["case_id"])
                )
                if preserved_root.exists():
                    shutil.rmtree(preserved_root)
                shutil.copytree(root, preserved_root)
                root = preserved_root
                result.artifact_path = str(root)
                files = {
                    path.relative_to(root).as_posix(): path
                    for path in root.rglob("*")
                    if path.is_file()
                }
                spec = ProjectSpec.from_dict(job.project_spec)
                result.file_count = len(files)
                result.content_digest = _content_digest(root)
                result.score, result.checks = _score_case(case, spec, root, files, job)
            result.passed = (
                job.status == JobStatus.SUCCEEDED
                and job.release_status == ReleaseStatus.VERIFIED
                and result.artifact_available
                and result.score >= 12.0
            )
            if not result.passed:
                result.failure_reason = "; ".join(job.errors[-3:]) or (
                    "Live workflow did not reach a verified successful artifact."
                )
        except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as exc:
            result.failure_reason = f"{type(exc).__name__}: {exc}"
    result.duration_seconds = round(time.monotonic() - started, 3)
    return result


def _score_case(
    case: dict[str, Any],
    spec: ProjectSpec,
    root: Path,
    files: dict[str, Path],
    job: JobState,
) -> tuple[float, list[str]]:
    score = 0.0
    checks: list[str] = []
    if spec.capability_id == case["capability_id"]:
        score += 1.0
        checks.append("capability_resolution")
    expected_paths = [str(path) for path in case["expected_paths"]]
    if all(_expected_path_present(path, files) for path in expected_paths):
        score += 2.0
        checks.append("required_paths")
    pack = resolve_capability(spec.capability_id)
    if all(_expected_path_present(path, files) for path in pack.required_paths):
        score += 1.0
        checks.append("pack_contract")
    if any("test" in path.lower() for path in files):
        score += 1.0
        checks.append("test_presence")
    readme = (root / "README.md").read_text(encoding="utf-8", errors="replace")
    if "install" in readme.lower() and (
        "run" in readme.lower() or "command-line" in readme.lower()
    ):
        score += 1.0
        checks.append("run_documentation")
    blueprint = json.loads((root / "artifacts" / "blueprint.json").read_text())
    if blueprint.get("project_spec", {}).get("capability_id") == spec.capability_id:
        score += 1.0
        checks.append("blueprint_traceability")
    validation = job.approval_state.get("benchmark_validation", {})
    if validation.get("passed", False):
        score += 2.0
        checks.append("validation")
    lowered_paths = "\n".join(files).lower()
    if all(exclusion not in lowered_paths for exclusion in spec.excluded_features):
        score += 1.0
        checks.append("exclusion_compliance")
    expected_adapters = set(case.get("expected_adapters", []))
    if not expected_adapters or expected_adapters.issubset(spec.adapter_ids):
        score += 1.0
        checks.append("domain_adapter_resolution")
    expected_workers = set(case.get("expected_workers", []))
    actual_workers = {task.worker_kind.value for task in job.tasks}
    if not expected_workers or expected_workers == actual_workers:
        score += 1.0
        checks.append("minimal_worker_scope")
    return score, checks


def _expected_path_present(path: str, files: dict[str, Path]) -> bool:
    if path in files:
        return True
    backend_manifest_alternatives = {
        "backend/pyproject.toml",
        "backend/requirements.txt",
        "backend/package.json",
    }
    return path in backend_manifest_alternatives and bool(
        backend_manifest_alternatives & files.keys()
    )


def _content_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root).as_posix()
        if relative_path == "artifacts/risk-report.json":
            continue
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _load_cases() -> list[dict[str, Any]]:
    return json.loads((Path(__file__).with_name("cases.json")).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Agentic Forge capability benchmark.")
    parser.add_argument(
        "--execute", action="store_true", help="Install and execute generated projects."
    )
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--live", action="store_true", help="Run the complete LLM workflow.")
    parser.add_argument("--case", action="append", dest="case_ids")
    arguments = parser.parse_args()
    report = (
        run_live_benchmark(arguments.case_ids)
        if arguments.live
        else run_benchmark(
            execute=arguments.execute,
            repeat=max(1, arguments.repeat),
            case_ids=arguments.case_ids,
        )
    )
    payload = json.dumps(report.to_dict(), indent=2) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
