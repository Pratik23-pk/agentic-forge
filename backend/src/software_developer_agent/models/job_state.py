from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_HUMAN_FEEDBACK = "awaiting_human_feedback"
    EVALUATING = "evaluating"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class ReleaseStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    PROVISIONAL = "provisional"
    QUARANTINED = "quarantined"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkerKind(StrEnum):
    DATABASE = "database"
    BACKEND = "backend"
    FRONTEND = "frontend"


class HumanFeedbackStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    AUTO_APPROVED = "auto_approved"


class ApprovalGate(StrEnum):
    PRODUCT_CONTRACT = "product_contract"
    PRIVILEGED_ACTION = "privileged_action"
    RELEASE = "release"
    WORKER_REVIEW = "worker_review"


class HumanFeedbackDecision(StrEnum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"


@dataclass(slots=True)
class JobRequest:
    prompt: str
    project_id: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class JobTask:
    worker_kind: WorkerKind
    title: str
    instructions: str
    task_id: str = field(default_factory=lambda: str(uuid4()))
    status: TaskStatus = TaskStatus.PENDING
    attempt: int = 0
    max_attempts: int = 2
    depends_on: list[str] = field(default_factory=list)
    capability_id: str = "react-fastapi"
    adapter_ids: list[str] = field(default_factory=list)
    retry_context: str | None = None
    tool_context: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    transport_attempts: int = 0
    repair_rejections: int = 0


@dataclass(slots=True)
class WorkerResult:
    task_id: str
    worker_kind: WorkerKind
    status: TaskStatus
    summary: str
    output: str = ""
    errors: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    attempt: int = 1
    used_fallback: bool = False


@dataclass(slots=True)
class JobArtifact:
    artifact_id: str
    kind: str
    name: str
    path: str
    url: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HumanFeedbackRequest:
    gate: ApprovalGate
    worker_kind: WorkerKind | None
    task_id: str | None
    attempt: int
    title: str
    prompt: str
    summary: str
    visual_type: str
    visual_content: str
    checkpoint_id: str = field(default_factory=lambda: str(uuid4()))
    status: HumanFeedbackStatus = HumanFeedbackStatus.PENDING
    response: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def resolve(self, status: HumanFeedbackStatus, response: str | None = None) -> None:
        self.status = status
        self.response = response
        self.updated_at = datetime.now(UTC)


@dataclass(slots=True)
class GuardrailFinding:
    name: str
    passed: bool
    severity: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GuardrailReport:
    name: str
    passed: bool
    findings: list[GuardrailFinding] = field(default_factory=list)

    @property
    def failed_findings(self) -> list[GuardrailFinding]:
        return [finding for finding in self.findings if not finding.passed]


@dataclass(slots=True)
class EvaluationResult:
    passed: bool
    retry_targets: list[WorkerKind] = field(default_factory=list)
    replan_required: bool = False
    failure_reason: str | None = None
    checks: list[str] = field(default_factory=list)
    context_pruned: bool = False
    decision: str = "approved"
    warnings: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class RepairTicket:
    source: str
    worker_kind: WorkerKind
    category: str
    summary: str
    fingerprint: str
    occurrence: int
    strategy: str
    ticket_id: str = field(default_factory=lambda: str(uuid4()))
    validation_name: str | None = None
    command: str | None = None
    target_files: list[str] = field(default_factory=list)
    line: int | None = None
    expected: str | None = None
    actual: str | None = None
    evidence: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    adapter_ids: list[str] = field(default_factory=list)
    resolved: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class JobState:
    request: JobRequest
    job_id: str = field(default_factory=lambda: str(uuid4()))
    status: JobStatus = JobStatus.PENDING
    request_policy: dict[str, Any] = field(default_factory=dict)
    preflight: dict[str, Any] = field(default_factory=dict)
    project_spec: dict[str, Any] = field(default_factory=dict)
    design_spec: dict[str, Any] = field(default_factory=dict)
    project_explanation: dict[str, Any] = field(default_factory=dict)
    approval_state: dict[str, Any] = field(default_factory=dict)
    cost_ledger: dict[str, Any] = field(default_factory=dict)
    api_contract: dict[str, Any] = field(default_factory=dict)
    tasks: list[JobTask] = field(default_factory=list)
    worker_results: list[WorkerResult] = field(default_factory=list)
    manifest_state: dict[str, Any] = field(default_factory=dict)
    verified_manifest_state: dict[str, Any] = field(default_factory=dict)
    verified_validation: dict[str, Any] = field(default_factory=dict)
    manifest_generation: int = 0
    manifest_transaction: dict[str, Any] = field(default_factory=dict)
    guardrail_reports: list[GuardrailReport] = field(default_factory=list)
    artifacts: list[JobArtifact] = field(default_factory=list)
    release_status: ReleaseStatus = ReleaseStatus.PENDING
    risk_findings: list[dict[str, Any]] = field(default_factory=list)
    quarantine_preview_consumed: bool = False
    artifact_errors: list[str] = field(default_factory=list)
    validation_results: list[dict[str, Any]] = field(default_factory=list)
    repair_tickets: list[RepairTicket] = field(default_factory=list)
    active_repair_ticket_ids: dict[str, str] = field(default_factory=dict)
    failure_fingerprints: dict[str, int] = field(default_factory=dict)
    feedback_requests: list[HumanFeedbackRequest] = field(default_factory=list)
    active_feedback_request_id: str | None = None
    evaluation: EvaluationResult | None = None
    loop_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def set_status(self, status: JobStatus) -> None:
        self.status = status
        self.touch()

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC)

    def add_guardrail_report(self, report: GuardrailReport) -> None:
        self.guardrail_reports.append(report)
        self.touch()

    def add_worker_result(self, result: WorkerResult) -> None:
        self.worker_results.append(result)
        self.touch()

    def add_artifact(self, artifact: JobArtifact) -> None:
        existing = [item for item in self.artifacts if item.artifact_id != artifact.artifact_id]
        existing.append(artifact)
        self.artifacts = existing
        self.touch()

    def add_feedback_request(self, request: HumanFeedbackRequest) -> None:
        self.feedback_requests.append(request)
        self.active_feedback_request_id = request.checkpoint_id
        self.set_status(JobStatus.AWAITING_HUMAN_FEEDBACK)

    def add_repair_ticket(self, ticket: RepairTicket) -> None:
        self.repair_tickets.append(ticket)
        self.active_repair_ticket_ids[ticket.worker_kind.value] = ticket.ticket_id
        self.failure_fingerprints[ticket.fingerprint] = ticket.occurrence
        self.touch()

    def active_repair_ticket(self, worker_kind: WorkerKind) -> RepairTicket | None:
        ticket_id = self.active_repair_ticket_ids.get(worker_kind.value)
        if ticket_id is None:
            return None
        return next(
            (ticket for ticket in reversed(self.repair_tickets) if ticket.ticket_id == ticket_id),
            None,
        )

    def resolve_repair_tickets(self, worker_kinds: list[WorkerKind] | None = None) -> None:
        selected = set(worker_kinds or list(WorkerKind))
        for ticket in self.repair_tickets:
            if ticket.worker_kind in selected and not ticket.resolved:
                ticket.resolved = True
                self.active_repair_ticket_ids.pop(ticket.worker_kind.value, None)
        self.touch()

    def active_feedback_request(self) -> HumanFeedbackRequest | None:
        if self.active_feedback_request_id is None:
            return None
        for request in self.feedback_requests:
            if request.checkpoint_id == self.active_feedback_request_id:
                return request
        return None

    def resolve_active_feedback(
        self,
        status: HumanFeedbackStatus,
        response: str | None = None,
    ) -> HumanFeedbackRequest | None:
        request = self.active_feedback_request()
        if request is None:
            return None
        request.resolve(status, response)
        self.active_feedback_request_id = None
        self.touch()
        return request

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


def _serialize(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    return value


def job_state_from_dict(payload: dict[str, Any]) -> JobState:
    request = JobRequest(
        prompt=payload["request"]["prompt"],
        project_id=payload["request"].get("project_id", "default"),
        metadata=payload["request"].get("metadata", {}),
    )
    job = JobState(
        request=request,
        job_id=payload.get("job_id", str(uuid4())),
        status=JobStatus(payload.get("status", JobStatus.PENDING.value)),
        request_policy=dict(payload.get("request_policy", {})),
        preflight=dict(payload.get("preflight", {})),
        project_spec=dict(payload.get("project_spec", {})),
        design_spec=dict(payload.get("design_spec", {})),
        project_explanation=dict(payload.get("project_explanation", {})),
        approval_state=dict(payload.get("approval_state", {})),
        cost_ledger=dict(payload.get("cost_ledger", {})),
        api_contract=dict(payload.get("api_contract", {})),
        manifest_state=dict(payload.get("manifest_state", {})),
        verified_manifest_state=dict(payload.get("verified_manifest_state", {})),
        verified_validation=dict(payload.get("verified_validation", {})),
        manifest_generation=int(payload.get("manifest_generation", 0)),
        manifest_transaction=dict(payload.get("manifest_transaction", {})),
        release_status=ReleaseStatus(payload.get("release_status", ReleaseStatus.PENDING.value)),
        risk_findings=list(payload.get("risk_findings", [])),
        quarantine_preview_consumed=bool(payload.get("quarantine_preview_consumed", False)),
        loop_count=payload.get("loop_count", 0),
        errors=list(payload.get("errors", [])),
        warnings=list(payload.get("warnings", [])),
        artifact_errors=list(payload.get("artifact_errors", [])),
        validation_results=list(payload.get("validation_results", [])),
        active_repair_ticket_ids=dict(payload.get("active_repair_ticket_ids", {})),
        failure_fingerprints={
            str(key): int(value)
            for key, value in dict(payload.get("failure_fingerprints", {})).items()
        },
        created_at=_parse_datetime(payload.get("created_at")),
        updated_at=_parse_datetime(payload.get("updated_at")),
    )
    job.tasks = [
        JobTask(
            worker_kind=WorkerKind(item["worker_kind"]),
            title=item["title"],
            instructions=item["instructions"],
            task_id=item.get("task_id", str(uuid4())),
            status=TaskStatus(item.get("status", TaskStatus.PENDING.value)),
            attempt=item.get("attempt", 0),
            max_attempts=item.get("max_attempts", 2),
            depends_on=list(item.get("depends_on", [])),
            capability_id=item.get("capability_id", "react-fastapi"),
            adapter_ids=list(item.get("adapter_ids", [])),
            retry_context=item.get("retry_context"),
            tool_context=item.get("tool_context"),
            tool_calls=list(item.get("tool_calls", [])),
            transport_attempts=item.get("transport_attempts", 0),
            repair_rejections=item.get("repair_rejections", 0),
        )
        for item in payload.get("tasks", [])
    ]
    job.worker_results = [
        WorkerResult(
            task_id=item["task_id"],
            worker_kind=WorkerKind(item["worker_kind"]),
            status=TaskStatus(item["status"]),
            summary=item["summary"],
            output=item.get("output", ""),
            errors=list(item.get("errors", [])),
            artifacts=list(item.get("artifacts", [])),
            tool_calls=list(item.get("tool_calls", [])),
            attempt=item.get("attempt", 1),
            used_fallback=bool(item.get("used_fallback", False)),
        )
        for item in payload.get("worker_results", [])
    ]
    job.artifacts = [
        JobArtifact(
            artifact_id=item["artifact_id"],
            kind=item["kind"],
            name=item["name"],
            path=item["path"],
            url=item["url"],
            metadata=item.get("metadata", {}),
        )
        for item in payload.get("artifacts", [])
    ]
    job.feedback_requests = [
        HumanFeedbackRequest(
            gate=ApprovalGate(item.get("gate", ApprovalGate.WORKER_REVIEW.value)),
            worker_kind=(
                WorkerKind(item["worker_kind"]) if item.get("worker_kind") is not None else None
            ),
            task_id=item.get("task_id"),
            attempt=item.get("attempt", 1),
            title=item["title"],
            prompt=item["prompt"],
            summary=item["summary"],
            visual_type=item["visual_type"],
            visual_content=item["visual_content"],
            checkpoint_id=item.get("checkpoint_id", str(uuid4())),
            status=HumanFeedbackStatus(item.get("status", HumanFeedbackStatus.PENDING.value)),
            response=item.get("response"),
            metadata=item.get("metadata", {}),
            created_at=_parse_datetime(item.get("created_at")),
            updated_at=_parse_datetime(item.get("updated_at")),
        )
        for item in payload.get("feedback_requests", [])
    ]
    job.repair_tickets = [
        RepairTicket(
            source=item["source"],
            worker_kind=WorkerKind(item["worker_kind"]),
            category=item["category"],
            summary=item["summary"],
            fingerprint=item["fingerprint"],
            occurrence=int(item.get("occurrence", 1)),
            strategy=item.get("strategy", "targeted_patch"),
            ticket_id=item.get("ticket_id", str(uuid4())),
            validation_name=item.get("validation_name"),
            command=item.get("command"),
            target_files=list(item.get("target_files", [])),
            line=item.get("line"),
            expected=item.get("expected"),
            actual=item.get("actual"),
            evidence=list(item.get("evidence", [])),
            allowed_paths=list(item.get("allowed_paths", [])),
            adapter_ids=list(item.get("adapter_ids", [])),
            resolved=bool(item.get("resolved", False)),
            created_at=_parse_datetime(item.get("created_at")),
        )
        for item in payload.get("repair_tickets", [])
    ]
    job.active_feedback_request_id = payload.get("active_feedback_request_id")
    job.guardrail_reports = [
        GuardrailReport(
            name=item["name"],
            passed=item["passed"],
            findings=[
                GuardrailFinding(
                    name=finding["name"],
                    passed=finding["passed"],
                    severity=finding["severity"],
                    message=finding["message"],
                    metadata=finding.get("metadata", {}),
                )
                for finding in item.get("findings", [])
            ],
        )
        for item in payload.get("guardrail_reports", [])
    ]
    evaluation = payload.get("evaluation")
    if evaluation is not None:
        job.evaluation = EvaluationResult(
            passed=evaluation["passed"],
            retry_targets=[
                WorkerKind(worker_kind) for worker_kind in evaluation.get("retry_targets", [])
            ],
            replan_required=evaluation.get("replan_required", False),
            failure_reason=evaluation.get("failure_reason"),
            checks=list(evaluation.get("checks", [])),
            context_pruned=evaluation.get("context_pruned", False),
            decision=evaluation.get("decision", "approved"),
            warnings=list(evaluation.get("warnings", [])),
            evidence=list(evaluation.get("evidence", [])),
        )
    return job


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    return datetime.fromisoformat(value)
