from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from difflib import SequenceMatcher
from hashlib import sha256
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from software_developer_agent.artifacts.file_manifest import (
    WorkerFileManifest,
    worker_manifest_source_syntax_failure,
)
from software_developer_agent.artifacts.validation import ProjectValidationReport
from software_developer_agent.capabilities.models import ProjectSpec
from software_developer_agent.capabilities.registry import resolve_project_spec
from software_developer_agent.capabilities.validation_adapters import validate_with_adapters
from software_developer_agent.config.settings import Settings
from software_developer_agent.memory.langgraph_memory import open_langgraph_resources
from software_developer_agent.models.job_state import (
    EvaluationResult,
    JobState,
    JobTask,
    RepairTicket,
    WorkerKind,
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SOURCE_LOCATION = re.compile(
    r"(?P<path>(?:backend|frontend|database)/)?"
    r"(?P<file>[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\."
    r"(?:html|json|jsx|mjs|tsx|css|js|py|sql|ts))(?![A-Za-z0-9])"
    r"(?::(?P<line>\d+)(?::\d+)?)?"
)
EXPECTED_LINE = re.compile(r"^\s*(?:Expected|expected)\s*:?\s*(.+)$", re.MULTILINE)
ACTUAL_LINE = re.compile(r"^\s*(?:Received|Actual|actual)\s*:?\s*(.+)$", re.MULTILINE)
SEMANTIC_FAILURE_LINE = re.compile(
    r"^(?:E\s+|FAILED\s+|ERROR\s+|.*(?:AssertionError|Error:|Exception:).*)"
)
PRESERVED_SOURCE_SUFFIXES = {".css", ".html", ".js", ".jsx", ".py", ".sql", ".ts", ".tsx"}
MAX_REPAIR_SHRINK_RATIO = 0.75
MIN_REPAIR_TOKEN_SIMILARITY = 0.72


class RepairGraphState(TypedDict, total=False):
    source: str
    worker_kind: str
    failure_reason: str
    validation_name: str | None
    command: str | None
    stdout: str
    stderr: str
    adapter_ids: list[str]
    worker_attempt: int
    max_attempts: int
    previous_fingerprints: dict[str, int]
    normalized_evidence: str
    category: str
    fingerprint: str
    occurrence: int
    strategy: str
    target_files: list[str]
    line: int | None
    expected: str | None
    actual: str | None
    evidence: list[str]


@dataclass(frozen=True, slots=True)
class CandidateVerification:
    accepted: bool
    reason: str
    changed_paths: tuple[str, ...] = ()


def _normalize_failure(state: RepairGraphState) -> dict[str, Any]:
    combined = "\n".join(
        value
        for value in (
            state.get("failure_reason", ""),
            state.get("stderr", ""),
            state.get("stdout", ""),
        )
        if value
    )
    cleaned = ANSI_ESCAPE.sub("", combined).strip()
    locations = list(SOURCE_LOCATION.finditer(cleaned))
    target_files: list[str] = []
    for match in locations:
        candidate = _normalize_source_path(
            match.group("path"),
            match.group("file"),
            state["worker_kind"],
        )
        if candidate is not None and candidate not in target_files:
            target_files.append(candidate)
    first_line = next(
        (int(match.group("line")) for match in locations if match.group("line")),
        None,
    )
    expected_match = EXPECTED_LINE.search(cleaned)
    actual_match = ACTUAL_LINE.search(cleaned)
    evidence = _evidence_excerpt(cleaned)
    normalized = _normalize_for_fingerprint(
        "\n".join(
            (
                state.get("validation_name") or "unknown",
                state.get("command") or "",
                cleaned,
            )
        )
    )
    return {
        "normalized_evidence": normalized,
        "target_files": target_files,
        "line": first_line,
        "expected": expected_match.group(1).strip()[:500] if expected_match else None,
        "actual": actual_match.group(1).strip()[:500] if actual_match else None,
        "evidence": evidence,
    }


def _classify_failure(state: RepairGraphState) -> dict[str, Any]:
    evidence = state.get("normalized_evidence", "")
    validation_name = (state.get("validation_name") or "").lower()
    if state.get("source") == "evaluator":
        category = "requirement_gap"
    elif state.get("source") == "worker":
        category = "worker_output"
    elif any(term in evidence for term in ("npm ci", "dependency", "package-lock", "resolution")):
        category = "dependency"
    elif "build" in validation_name or any(
        term in evidence
        for term in (
            "error ts",
            "parse_error",
            "transform failed with",
            "typescript",
            "compile",
            "syntaxerror",
        )
    ):
        category = "build"
    elif any(term in evidence for term in ("getbyrole", "getbyalttext", "testinglibrary")):
        category = "test_contract"
    elif "test" in validation_name or any(
        term in evidence for term in ("assert", "pytest", "vitest")
    ):
        category = "test_failure"
    elif any(term in evidence for term in ("database", "migration", "postgres", "sql")):
        category = "database"
    elif any(term in evidence for term in ("cors", "network", "fetch", "websocket")):
        category = "integration"
    else:
        category = "runtime"
    fingerprint_evidence = _semantic_failure_evidence(state, evidence)
    if category in {"test_contract", "test_failure"} and (
        state.get("expected") or state.get("actual")
    ):
        fingerprint_evidence = "|".join(
            (
                _normalize_for_fingerprint(state.get("validation_name") or ""),
                _normalize_for_fingerprint(state.get("expected") or ""),
                _normalize_for_fingerprint(state.get("actual") or ""),
            )
        )
    fingerprint = sha256(
        f"{state['worker_kind']}|{category}|{fingerprint_evidence}".encode()
    ).hexdigest()
    occurrence = int(state.get("previous_fingerprints", {}).get(fingerprint, 0)) + 1
    return {
        "category": category,
        "fingerprint": fingerprint,
        "occurrence": occurrence,
    }


def _semantic_failure_evidence(state: RepairGraphState, fallback: str) -> str:
    salient = []
    for line in state.get("evidence", []):
        for candidate in line.splitlines():
            normalized = candidate.strip()
            if normalized and SEMANTIC_FAILURE_LINE.match(normalized):
                salient.append(_normalize_for_fingerprint(normalized))
    if not salient:
        return fallback
    return "|".join(dict.fromkeys(salient[-12:]))


def _select_strategy(state: RepairGraphState) -> dict[str, Any]:
    next_attempt = int(state.get("worker_attempt", 0)) + 1
    max_attempts = int(state.get("max_attempts", 1))
    occurrence = int(state.get("occurrence", 1))
    if next_attempt >= max_attempts:
        strategy = "final_patch"
    elif occurrence >= 2:
        strategy = "escalated_patch"
    else:
        strategy = "targeted_patch"
    return {"strategy": strategy}


def _build_graph(checkpointer, store):
    builder = StateGraph(RepairGraphState)
    builder.add_node("normalize_failure", _normalize_failure)
    builder.add_node("classify_failure", _classify_failure)
    builder.add_node("select_strategy", _select_strategy)
    builder.add_edge(START, "normalize_failure")
    builder.add_edge("normalize_failure", "classify_failure")
    builder.add_edge("classify_failure", "select_strategy")
    builder.add_edge("select_strategy", END)
    return builder.compile(checkpointer=checkpointer, store=store)


class UniversalRepairKernel:
    """Failure-only LangGraph subgraph shared by every stack and domain adapter."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def register_validation_failure(
        self,
        job: JobState,
        report: ProjectValidationReport,
    ) -> list[RepairTicket]:
        failed_result = next((result for result in report.results if not result.passed), None)
        targets = report.retry_targets or _infer_targets(report.failure_reason or "")
        tickets = []
        for worker_kind in targets:
            owned_findings = [
                finding
                for finding in report.adapter_findings
                if finding.get("worker_kind") == worker_kind.value and finding.get("blocking", True)
            ]
            owned_reason = "; ".join(
                str(finding.get("message", "")).strip()
                for finding in owned_findings
                if str(finding.get("message", "")).strip()
            )
            adapter_codes = [
                str(finding.get("code", "")).strip()
                for finding in owned_findings
                if str(finding.get("code", "")).strip()
            ]
            tickets.append(
                self._register(
                    job,
                    worker_kind=worker_kind,
                    source="adapter_validation",
                    failure_reason=(
                        owned_reason
                        or report.failure_reason
                        or "Generated project validation failed."
                    ),
                    validation_name=(
                        "adapter:" + ",".join(adapter_codes)
                        if adapter_codes
                        else failed_result.name
                        if failed_result
                        else None
                    ),
                    command=failed_result.command if failed_result else None,
                    stdout=(
                        json.dumps(owned_findings, sort_keys=True)
                        if owned_findings
                        else failed_result.stdout_excerpt
                        if failed_result
                        else ""
                    ),
                    stderr=failed_result.stderr_excerpt if failed_result else "",
                )
            )
        return tickets

    def register_evaluation_failure(
        self,
        job: JobState,
        evaluation: EvaluationResult,
    ) -> list[RepairTicket]:
        tickets = []
        evidence_text = "\n".join(json.dumps(item, sort_keys=True) for item in evaluation.evidence)
        for worker_kind in evaluation.retry_targets:
            worker_failure = any(
                check
                in {
                    f"worker_failed:{worker_kind.value}",
                    f"worker_not_succeeded:{worker_kind.value}",
                    f"missing_result:{worker_kind.value}",
                    f"missing_file_manifest:{worker_kind.value}",
                    f"certified_fallback_requires_repair:{worker_kind.value}",
                }
                for check in evaluation.checks
            )
            if worker_failure and job.active_repair_ticket(worker_kind) is not None:
                continue
            tickets.append(
                self._register(
                    job,
                    worker_kind=worker_kind,
                    source="worker" if worker_failure else "evaluator",
                    failure_reason=evaluation.failure_reason or "Acceptance criterion is unmet.",
                    validation_name=(
                        "worker_output_contract" if worker_failure else "semantic_evaluation"
                    ),
                    command=(
                        "manifest normalization"
                        if worker_failure
                        else "focused acceptance verification"
                    ),
                    stdout=evidence_text,
                    stderr="",
                )
            )
        return tickets

    def verify_candidate(
        self,
        job: JobState,
        task: JobTask,
        manifest: WorkerFileManifest,
    ) -> CandidateVerification:
        syntax_failure = worker_manifest_source_syntax_failure(manifest)
        if syntax_failure:
            return CandidateVerification(False, syntax_failure)
        previous = job.manifest_state.get("files", {}) if job.manifest_state else {}
        previous_for_task = {
            path: record
            for path, record in previous.items()
            if isinstance(record, dict) and record.get("task_id") == task.task_id
        }
        if not previous_for_task:
            return CandidateVerification(
                True,
                "Initial complete candidate accepted.",
                tuple(file.path for file in manifest.files),
            )
        if manifest.operation != "patch":
            return CandidateVerification(
                False,
                "Repair candidates must use operation=patch so unchanged files are preserved.",
            )
        changed_paths = []
        for file in manifest.files:
            record = previous.get(file.path)
            if not isinstance(record, dict) or record.get("content") != file.content:
                changed_paths.append(file.path)
        for path in manifest.deleted_files:
            record = previous.get(path)
            if isinstance(record, dict) and not record.get("deleted", False):
                changed_paths.append(path)
        if not changed_paths:
            return CandidateVerification(
                False,
                "The repair claimed success but produced no material file change.",
            )

        destructive_change = _unexpected_destructive_change(job, task, manifest, previous)
        if destructive_change:
            return CandidateVerification(False, destructive_change, tuple(changed_paths))

        preflight_failure = self._remaining_adapter_failure(job, manifest)
        if preflight_failure:
            return CandidateVerification(False, preflight_failure, tuple(changed_paths))
        return CandidateVerification(True, "Material scoped repair accepted.", tuple(changed_paths))

    def active_strategy(self, job: JobState, worker_kind: WorkerKind) -> str:
        ticket = job.active_repair_ticket(worker_kind)
        if ticket is None:
            return "initial_generation"
        task = next(
            (task for task in job.tasks if task.worker_kind == worker_kind),
            None,
        )
        rejections = task.repair_rejections if task is not None else 0
        if rejections >= 2:
            return "final_patch"
        if rejections >= 1 and ticket.strategy == "targeted_patch":
            return "escalated_patch"
        return ticket.strategy

    def _register(
        self,
        job: JobState,
        *,
        worker_kind: WorkerKind,
        source: str,
        failure_reason: str,
        validation_name: str | None,
        command: str | None,
        stdout: str,
        stderr: str,
    ) -> RepairTicket:
        task = next(task for task in job.tasks if task.worker_kind == worker_kind)
        state = RepairGraphState(
            source=source,
            worker_kind=worker_kind.value,
            failure_reason=failure_reason,
            validation_name=validation_name,
            command=command,
            stdout=stdout,
            stderr=stderr,
            adapter_ids=list(task.adapter_ids or job.project_spec.get("adapter_ids", [])),
            worker_attempt=task.attempt,
            max_attempts=task.max_attempts,
            previous_fingerprints=dict(job.failure_fingerprints),
        )
        with open_langgraph_resources(self._settings) as (checkpointer, store):
            graph = _build_graph(checkpointer, store)
            sequence = len(job.repair_tickets) + 1
            resolved = dict(
                graph.invoke(
                    state,
                    {
                        "configurable": {
                            "thread_id": f"{job.job_id}:repair:{job.manifest_generation}:{sequence}"
                        }
                    },
                )
            )
        ticket = RepairTicket(
            source=source,
            worker_kind=worker_kind,
            category=str(resolved["category"]),
            summary=_ticket_summary(resolved, failure_reason),
            fingerprint=str(resolved["fingerprint"]),
            occurrence=int(resolved["occurrence"]),
            strategy=str(resolved["strategy"]),
            validation_name=validation_name,
            command=command,
            target_files=list(resolved.get("target_files", [])),
            line=resolved.get("line"),
            expected=resolved.get("expected"),
            actual=resolved.get("actual"),
            evidence=list(resolved.get("evidence", [])),
            allowed_paths=[f"{worker_kind.value}/"],
            adapter_ids=list(state.get("adapter_ids", [])),
        )
        job.add_repair_ticket(ticket)
        return ticket

    @staticmethod
    def _remaining_adapter_failure(job: JobState, manifest: WorkerFileManifest) -> str | None:
        ticket = job.active_repair_ticket(manifest.worker_kind)
        if ticket is None:
            return None
        with tempfile.TemporaryDirectory(prefix="agentic-forge-patch-check-") as temp_dir:
            root = Path(temp_dir)
            for path, record in job.manifest_state.get("files", {}).items():
                if not isinstance(record, dict) or record.get("deleted", False):
                    continue
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(record.get("content", "")), encoding="utf-8")
            for path in manifest.deleted_files:
                (root / path).unlink(missing_ok=True)
            for file in manifest.files:
                target = root / file.path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(file.content, encoding="utf-8")
            spec = (
                ProjectSpec.from_dict(job.project_spec)
                if job.project_spec
                else resolve_project_spec(job.request.prompt, job.request.metadata)
            )
            validation = validate_with_adapters(root, spec)
            owned_blockers = [
                finding
                for finding in validation.blocking_findings
                if finding.worker_kind == manifest.worker_kind
            ]
            if owned_blockers:
                return (
                    "The proposed repair still fails deterministic capability preflight: "
                    + owned_blockers[0].message
                )
        return None


def _ticket_summary(state: RepairGraphState, fallback: str) -> str:
    parts = [
        f"Category: {state.get('category', 'unknown')}.",
        f"Strategy: {state.get('strategy', 'targeted_patch')}.",
        f"Failure: {fallback.strip()}",
    ]
    if state.get("target_files"):
        parts.append("Target files: " + ", ".join(state["target_files"]))
    if state.get("expected"):
        parts.append(f"Expected: {state['expected']}")
    if state.get("actual"):
        parts.append(f"Actual: {state['actual']}")
    return " ".join(parts)[:4_000]


def _normalize_source_path(prefix: str | None, file: str, worker_kind: str) -> str | None:
    normalized_file = file.replace("\\", "/").lstrip("/")
    parts = tuple(part for part in normalized_file.split("/") if part)
    if (
        not parts
        or any(part in {".", "..", ".venv", "venv", "site-packages"} for part in parts)
        or any("." in part for part in parts[:-1])
    ):
        return None
    if prefix:
        return f"{prefix}{normalized_file}".replace("//", "/")
    if normalized_file.startswith(("backend/", "frontend/", "database/")):
        return normalized_file
    if len(parts) > 1 and parts[0] not in {
        "app",
        "migrations",
        "public",
        "scripts",
        "src",
        "test",
        "tests",
    }:
        return None
    return f"{worker_kind}/{normalized_file}"


def _normalize_for_fingerprint(value: str) -> str:
    normalized = value.lower().replace("’", "'")
    normalized = re.sub(r"/[^\s:]+/(?:\.staging-)?[a-z0-9_-]+-[0-9a-f]{8}", "<project>", normalized)
    normalized = re.sub(r":[0-9]+(?::[0-9]+)?", ":<line>", normalized)
    normalized = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "<id>", normalized)
    normalized = re.sub(r"\b\d+(?:\.\d+)?s\b", "<duration>", normalized)
    return re.sub(r"\s+", " ", normalized).strip()[-6_000:]


def _evidence_excerpt(value: str, limit: int = 3_000) -> list[str]:
    if not value:
        return []
    if len(value) <= limit:
        return [value]
    head = (limit * 2) // 3
    return [f"{value[:head]}\n...[truncated]...\n{value[-(limit - head) :]}"]


def _infer_targets(failure_reason: str) -> list[WorkerKind]:
    lowered = failure_reason.lower()
    targets = [worker_kind for worker_kind in WorkerKind if worker_kind.value in lowered]
    return targets or [WorkerKind.FRONTEND]


def _unexpected_destructive_change(
    job: JobState,
    task: JobTask,
    manifest: WorkerFileManifest,
    previous: dict[str, Any],
) -> str | None:
    upgrading_certified_fallback = _is_upgrading_certified_fallback(job, task)
    ticket = job.active_repair_ticket(task.worker_kind)
    adapter_validated_integration = bool(
        ticket and ticket.category in {"database", "integration"}
    )
    for path in manifest.deleted_files:
        record = previous.get(path)
        if (
            isinstance(record, dict)
            and not record.get("deleted", False)
            and not upgrading_certified_fallback
            and not _destructive_change_requested(job, task, path)
        ):
            return (
                f"Repair candidate deletes {path} without an explicit file-deletion request. "
                "Preserve the checkpoint and return a narrower patch."
            )

    for file in manifest.files:
        record = previous.get(file.path)
        if not isinstance(record, dict) or record.get("deleted", False):
            continue
        previous_content = str(record.get("content", ""))
        if (
            Path(file.path).suffix.lower() not in PRESERVED_SOURCE_SUFFIXES
            or len(previous_content) < 500
            or upgrading_certified_fallback
            or _destructive_change_requested(job, task, file.path)
        ):
            continue
        if len(file.content) < len(previous_content) * MAX_REPAIR_SHRINK_RATIO:
            retained_percent = round((len(file.content) / len(previous_content)) * 100)
            return (
                f"Repair candidate unexpectedly shrinks {file.path} to {retained_percent}% of "
                "its checkpointed content. Preserve unrelated working behavior and return the "
                "smallest sufficient patch."
            )
        if _broad_rewrite_is_safe_to_validate(file.path) or adapter_validated_integration:
            continue
        similarity = _token_similarity(previous_content, file.content)
        if similarity < MIN_REPAIR_TOKEN_SIMILARITY:
            return (
                f"Repair candidate rewrites too much unrelated content in {file.path} "
                f"(similarity {similarity:.0%}). Restore the checkpoint and return only the "
                "smallest evidence-driven change."
            )
    return None


def _is_upgrading_certified_fallback(job: JobState, task: JobTask) -> bool:
    fallback_results = [
        result
        for result in reversed(job.worker_results)
        if result.task_id == task.task_id
        and result.used_fallback
        and result.status.value == "succeeded"
    ]
    if any(result.attempt == task.attempt for result in fallback_results):
        return True
    return job.active_repair_ticket(task.worker_kind) is not None and bool(fallback_results)


def _broad_rewrite_is_safe_to_validate(path: str) -> bool:
    normalized = path.lower().replace("\\", "/")
    name = Path(normalized).name
    return (
        "/tests/" in f"/{normalized}"
        or "/test/" in f"/{normalized}"
        or name.startswith("test_")
        and name.endswith(".py")
        or name.endswith("_test.py")
        or any(marker in name for marker in (".test.", ".spec.", "_test."))
        or normalized.startswith("database/")
        and name.startswith(("seed", "fixture"))
    )


def _destructive_change_requested(job: JobState, task: JobTask, path: str) -> bool:
    metadata = job.request.metadata
    context = "\n".join(
        str(value)
        for value in (
            task.instructions,
            task.retry_context or "",
            metadata.get("product_contract_feedback", ""),
            metadata.get("privileged_action_feedback", ""),
            metadata.get("release_feedback", ""),
        )
        if value
    ).lower()
    if re.search(
        r"\b(?:complete|completely|entire|full)\b[^\n.]{0,30}"
        r"\b(?:redesign|rebuild|rewrite|overhaul)\b",
        context,
    ) or re.search(
        r"\b(?:redesign|rebuild|rewrite|overhaul)\b[^\n.]{0,30}"
        r"\b(?:complete|completely|entire|full)\b",
        context,
    ):
        return True
    names = {path.lower(), Path(path).name.lower()}
    destructive_phrases = (
        "delete",
        "remove",
        "rewrite entirely",
        "rewrite the entire",
        "replace entirely",
        "replace the entire",
    )
    for name in names:
        escaped = re.escape(name)
        if any(
            re.search(rf"{phrase}[^\n.]{{0,80}}{escaped}", context)
            or re.search(rf"{escaped}[^\n.]{{0,80}}{phrase}", context)
            for phrase in destructive_phrases
        ):
            return True
    return False


def _token_similarity(previous_content: str, candidate_content: str) -> float:
    token_pattern = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*|\d+(?:\.\d+)?|[^\w\s]")
    previous_tokens = token_pattern.findall(previous_content)
    candidate_tokens = token_pattern.findall(candidate_content)
    return SequenceMatcher(
        None,
        previous_tokens,
        candidate_tokens,
        autojunk=True,
    ).ratio()
