import json
import logging

from software_developer_agent.artifacts.file_manifest import collect_worker_file_manifests
from software_developer_agent.config.settings import Settings
from software_developer_agent.integrations.llm_client import LLMClient
from software_developer_agent.models.job_state import (
    EvaluationResult,
    GuardrailReport,
    JobState,
    TaskStatus,
    WorkerKind,
)
from software_developer_agent.prompts.system_prompts import EVALUATOR_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class EvaluatorAgent:
    """Evaluates worker outputs and selects targeted retry scopes."""

    def __init__(
        self, settings: Settings | None = None, llm_client: LLMClient | None = None
    ) -> None:
        self._settings = settings
        self._llm_client = llm_client

    def evaluate(self, job: JobState) -> EvaluationResult:
        evidence_result = self._evaluate_file_evidence(job)
        if evidence_result is not None and not evidence_result.passed:
            return evidence_result
        if evidence_result is not None and evidence_result.decision == "warning":
            return evidence_result
        evidence_checks = evidence_result.checks if evidence_result is not None else []

        if self._settings and self._settings.enable_llm_calls and self._llm_client is not None:
            try:
                result = self._evaluate_with_llm(job)
                advisory_checks = [*evidence_checks, *result.checks]
                if result.passed:
                    return EvaluationResult(
                        passed=True,
                        checks=advisory_checks,
                        context_pruned=True,
                        decision=result.decision,
                        warnings=result.warnings,
                        evidence=result.evidence,
                    )
                if _is_actionable_semantic_failure(result):
                    result.checks = advisory_checks
                    return result
                advisory_checks.append("llm_evaluation:unsubstantiated_warning")
                return EvaluationResult(
                    passed=True,
                    checks=advisory_checks,
                    context_pruned=True,
                    decision="warning",
                    warnings=[
                        result.failure_reason
                        or "Evaluator concern lacked reproducible requirement evidence."
                    ],
                    evidence=result.evidence,
                )
            except Exception:
                logger.exception("evaluator.llm_fallback")

        checks: list[str] = list(evidence_checks)
        retry_targets: list[WorkerKind] = []

        if not job.tasks:
            return EvaluationResult(
                passed=False,
                failure_reason="Planner produced no tasks.",
                checks=["planner_task_presence"],
            )

        checks.append("planner_task_presence")

        for task in job.tasks:
            matching_results = [
                result for result in job.worker_results if result.task_id == task.task_id
            ]
            if not matching_results:
                retry_targets.append(task.worker_kind)
                checks.append(f"missing_result:{task.worker_kind.value}")
                continue

            accepted_checkpoint_result = next(
                (
                    result
                    for result in reversed(matching_results)
                    if result.status == TaskStatus.SUCCEEDED and result.attempt == task.attempt
                ),
                None,
            )
            latest = (
                accepted_checkpoint_result
                if task.status == TaskStatus.SUCCEEDED and accepted_checkpoint_result is not None
                else matching_results[-1]
            )
            if latest.status != TaskStatus.SUCCEEDED:
                retry_targets.append(task.worker_kind)
                checks.append(f"worker_failed:{task.worker_kind.value}")
            else:
                checks.append(f"worker_succeeded:{task.worker_kind.value}")

        if retry_targets:
            return EvaluationResult(
                passed=False,
                retry_targets=sorted(set(retry_targets), key=lambda item: item.value),
                failure_reason="One or more worker tasks need targeted retry.",
                checks=checks,
            )

        return EvaluationResult(passed=True, checks=checks, context_pruned=True)

    def _evaluate_file_evidence(self, job: JobState) -> EvaluationResult | None:
        if not job.tasks:
            return None

        checks: list[str] = []
        if job.artifact_errors:
            return EvaluationResult(
                passed=False,
                retry_targets=[],
                replan_required=False,
                failure_reason="; ".join(job.artifact_errors),
                checks=["artifact_assembly:failed"],
                context_pruned=True,
            )
        blocked_report = _first_blocking_guardrail(job.guardrail_reports)
        if blocked_report is not None:
            checks.append(f"guardrail_quarantine:{blocked_report.name}")

        manifests = collect_worker_file_manifests(job)
        paths_by_worker: dict[WorkerKind, set[str]] = {}
        for manifest in manifests:
            paths_by_worker.setdefault(manifest.worker_kind, set()).update(
                file.path for file in manifest.files
            )
        retry_targets: list[WorkerKind] = []
        failure_details: list[str] = []
        for task in job.tasks:
            if task.status != TaskStatus.SUCCEEDED:
                retry_targets.append(task.worker_kind)
                checks.append(f"worker_not_succeeded:{task.worker_kind.value}")
                latest_result = next(
                    (
                        result
                        for result in reversed(job.worker_results)
                        if result.task_id == task.task_id
                    ),
                    None,
                )
                detail = (
                    "; ".join(latest_result.errors)
                    if latest_result and latest_result.errors
                    else "worker did not complete successfully"
                )
                failure_details.append(f"{task.worker_kind.value}: {detail}")
                continue
            paths = paths_by_worker.get(task.worker_kind, set())
            if not paths:
                retry_targets.append(task.worker_kind)
                checks.append(f"missing_file_manifest:{task.worker_kind.value}")
                failure_details.append(f"{task.worker_kind.value}: valid file manifest is missing")
                continue
            if not _worker_has_scope_file(task.worker_kind, paths):
                retry_targets.append(task.worker_kind)
                checks.append(f"missing_scope_file:{task.worker_kind.value}")
                failure_details.append(
                    f"{task.worker_kind.value}: no file exists in the owned path scope"
                )
                continue
            accepted_result = next(
                (
                    result
                    for result in reversed(job.worker_results)
                    if result.task_id == task.task_id
                    and result.status == TaskStatus.SUCCEEDED
                    and result.attempt == task.attempt
                ),
                None,
            )
            if accepted_result is not None and accepted_result.used_fallback:
                retry_targets.append(task.worker_kind)
                checks.append(f"certified_fallback_requires_repair:{task.worker_kind.value}")
                failure_details.append(
                    f"{task.worker_kind.value}: the live worker response was unusable, so the "
                    "runnable certified checkpoint must now receive a focused implementation patch"
                )
                continue
            checks.append(f"file_manifest:{task.worker_kind.value}:{len(paths)}")

        has_folder = any(artifact.kind == "folder" for artifact in job.artifacts)
        has_zip = any(artifact.kind == "zip" for artifact in job.artifacts)
        checks.extend(
            [
                f"artifact_folder:{str(has_folder).lower()}",
                f"artifact_zip:{str(has_zip).lower()}",
            ]
        )

        if retry_targets:
            return EvaluationResult(
                passed=False,
                retry_targets=sorted(set(retry_targets), key=lambda item: item.value),
                failure_reason="; ".join(failure_details),
                checks=checks,
                context_pruned=True,
            )

        if not has_folder or not has_zip:
            return EvaluationResult(
                passed=False,
                retry_targets=[],
                failure_reason="Generated project folder and ZIP artifacts are missing.",
                checks=checks,
                context_pruned=True,
            )

        folder = next(artifact for artifact in job.artifacts if artifact.kind == "folder")
        validation = folder.metadata.get("validation", {})
        if not validation.get("passed", False):
            retry_targets = [
                WorkerKind(item)
                for item in validation.get("retry_targets", [])
                if item in {kind.value for kind in WorkerKind}
            ]
            return EvaluationResult(
                passed=False,
                retry_targets=retry_targets,
                replan_required=not bool(retry_targets),
                failure_reason=validation.get(
                    "failure_reason",
                    "Artifact validation evidence is missing or failed.",
                ),
                checks=[*checks, "artifact_validation:failed"],
                context_pruned=True,
            )
        checks.append("artifact_validation:passed")
        for result in validation.get("results", []):
            checks.append(
                f"validation_command:{result.get('name', 'unknown')}:"
                f"{'passed' if result.get('passed') else 'failed'}"
            )

        validation_warnings = [
            str(item.get("message", "")).strip()
            for item in validation.get("advisories", [])
            if isinstance(item, dict) and str(item.get("message", "")).strip()
        ]
        if not validation.get("release_ready", True):
            checks.append("release_validation:pending_infrastructure")
            return EvaluationResult(
                passed=True,
                checks=checks,
                context_pruned=True,
                decision="warning",
                warnings=validation_warnings
                or ["Release checks are pending, but executable validation passed."],
            )

        return EvaluationResult(passed=True, checks=checks, context_pruned=True)

    def _evaluate_with_llm(self, job: JobState) -> EvaluationResult:
        summary = {
            "request": job.request.prompt,
            "tasks": [
                {
                    "worker_kind": task.worker_kind.value,
                    "title": task.title,
                    "status": task.status.value,
                    "attempt": task.attempt,
                }
                for task in job.tasks
            ],
            "results": [
                {
                    "worker_kind": result.worker_kind.value,
                    "status": result.status.value,
                    "summary": result.summary,
                    "output_excerpt": result.output[:2500],
                    "errors": result.errors[:3],
                }
                for result in job.worker_results
            ],
            "file_evidence": [
                {
                    "worker_kind": manifest.worker_kind.value,
                    "summary": manifest.summary,
                    "files": [file.path for file in manifest.files],
                    "validation_commands": manifest.validation_commands,
                }
                for manifest in collect_worker_file_manifests(job)
            ],
            "semantic_source_evidence": _semantic_source_evidence(job),
            "project_spec": job.project_spec,
            "request_policy": job.request_policy,
            "api_contract": job.api_contract,
            "artifact_errors": job.artifact_errors,
            "validation_results": job.validation_results,
            "semantic_repair_history": [
                {
                    "worker_kind": ticket.worker_kind.value,
                    "category": ticket.category,
                    "summary": ticket.summary,
                    "fingerprint": ticket.fingerprint,
                    "occurrence": ticket.occurrence,
                    "strategy": ticket.strategy,
                    "resolved": ticket.resolved,
                }
                for ticket in job.repair_tickets
                if ticket.source == "evaluator"
            ],
            "artifacts": [
                {
                    "kind": artifact.kind,
                    "name": artifact.name,
                    "metadata": artifact.metadata,
                }
                for artifact in job.artifacts
            ],
            "guardrails": [
                {"name": report.name, "passed": report.passed} for report in job.guardrail_reports
            ],
        }
        user = (
            "Return JSON shape: "
            '{"decision":"approved|repair_required|warning","passed":true,'
            '"retry_targets":[],"replan_required":false,"failure_reason":null,'
            '"checks":[],"warnings":[],"evidence":[{"requirement":"...",'
            '"observation":"...","location":"frontend/src/App.tsx:10",'
            '"verification":"exact reproducible check"}]}\n'
            f"Job: {json.dumps(summary)}"
        )
        assert self._llm_client is not None
        response = self._llm_client.complete(EVALUATOR_SYSTEM_PROMPT, user)
        payload = json.loads(_extract_json(response.text))
        decision = str(payload.get("decision", "")).strip().lower()
        if decision not in {"approved", "repair_required", "warning"}:
            decision = "approved" if bool(payload.get("passed", False)) else "warning"
        return EvaluationResult(
            passed=decision != "repair_required",
            retry_targets=[WorkerKind(item) for item in payload.get("retry_targets", [])],
            replan_required=bool(payload.get("replan_required", False)),
            failure_reason=payload.get("failure_reason"),
            checks=list(payload.get("checks", [])),
            context_pruned=True,
            decision=decision,
            warnings=list(payload.get("warnings", [])),
            evidence=[dict(item) for item in payload.get("evidence", []) if isinstance(item, dict)],
        )


def _first_blocking_guardrail(reports: list[GuardrailReport]) -> GuardrailReport | None:
    latest_reports: dict[str, GuardrailReport] = {}
    for report in reversed(reports):
        latest_reports.setdefault(report.name, report)
    for report in latest_reports.values():
        if not report.passed:
            return report
    return None


def _worker_has_scope_file(worker_kind: WorkerKind, paths: set[str]) -> bool:
    if worker_kind == WorkerKind.DATABASE:
        return any(
            path.startswith("database/") or "migration" in path.lower() or "schema" in path.lower()
            for path in paths
        )
    if worker_kind == WorkerKind.FRONTEND:
        return any(path.startswith("frontend/") for path in paths)
    if worker_kind == WorkerKind.BACKEND:
        return any(path.startswith("backend/") for path in paths)
    return bool(paths)


def _is_actionable_semantic_failure(result: EvaluationResult) -> bool:
    if result.decision != "repair_required" or not (result.retry_targets or result.replan_required):
        return False
    if not result.failure_reason or not result.evidence:
        return False
    required_fields = {"requirement", "observation", "location", "verification"}
    return all(
        required_fields.issubset(item)
        and all(str(item.get(field, "")).strip() for field in required_fields)
        for item in result.evidence
    )


def _semantic_source_evidence(job: JobState, limit: int = 12) -> list[dict[str, str]]:
    preferred_markers = (
        "app.",
        "main.",
        "route",
        "service",
        "schema",
        "test.",
        ".test.",
        ".spec.",
    )
    candidates = [
        file
        for manifest in collect_worker_file_manifests(job)
        for file in manifest.files
        if any(marker in file.path.lower() for marker in preferred_markers)
    ]
    selected = sorted(candidates, key=lambda file: file.path)[:limit]
    return [{"path": file.path, "content_excerpt": file.content[:1_800]} for file in selected]


def _extract_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.removeprefix("json").strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found.")
    return stripped[start : end + 1]
