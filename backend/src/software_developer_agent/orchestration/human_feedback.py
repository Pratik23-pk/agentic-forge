from __future__ import annotations

import json
import logging

from software_developer_agent.config.settings import Settings
from software_developer_agent.guardrails.input.acceptable_use import (
    ProhibitedRequestError,
    check_acceptable_use,
    prompt_fingerprint,
)
from software_developer_agent.memory.approval_checkpoint import ApprovalCheckpointManager
from software_developer_agent.models.job_state import (
    ApprovalGate,
    HumanFeedbackDecision,
    HumanFeedbackRequest,
    HumanFeedbackStatus,
    JobState,
    JobStatus,
    ReleaseStatus,
    TaskStatus,
    WorkerKind,
)
from software_developer_agent.observability.metrics import metrics
from software_developer_agent.orchestration.approval_policy import (
    approval_contract,
    privileged_actions_for_job,
)

logger = logging.getLogger(__name__)


class HumanFeedbackCoordinator:
    """Owns the three stage-level HITL gates and their durable decisions."""

    def __init__(self, settings: Settings, tool_registry=None) -> None:
        self._settings = settings
        self._checkpoints = ApprovalCheckpointManager(settings)

    def ensure_product_contract(self, job: JobState) -> HumanFeedbackRequest | None:
        if not self._settings.enable_human_checkpoints:
            return None
        existing = self._pending_request(job, ApprovalGate.PRODUCT_CONTRACT)
        if existing is not None or self._is_approved(job, ApprovalGate.PRODUCT_CONTRACT):
            return existing
        contract = approval_contract(job)
        return self._create_request(
            job,
            gate=ApprovalGate.PRODUCT_CONTRACT,
            title="Approve scope and workflow",
            prompt=(
                "Confirm the requested scope, recommended generation profile, and uploaded-media "
                "plan before planning and implementation begins."
            ),
            summary="Deterministic preflight is complete; paid generation has not started.",
            visual_content=json.dumps(contract, indent=2),
            metadata={"contract": contract, "required": True},
        )

    def ensure_privileged_actions(self, job: JobState) -> HumanFeedbackRequest | None:
        if not self._settings.enable_human_checkpoints:
            return None
        actions = privileged_actions_for_job(job)
        if not actions:
            if self._checkpoints.status(job, ApprovalGate.PRIVILEGED_ACTION) is None:
                self._checkpoints.record(
                    job,
                    ApprovalGate.PRIVILEGED_ACTION,
                    HumanFeedbackStatus.AUTO_APPROVED.value,
                    {"reason": "No privileged external action is required."},
                )
            return None
        existing = self._pending_request(job, ApprovalGate.PRIVILEGED_ACTION)
        if existing is not None or self._is_approved(job, ApprovalGate.PRIVILEGED_ACTION):
            return existing
        return self._create_request(
            job,
            gate=ApprovalGate.PRIVILEGED_ACTION,
            title="Approve privileged actions",
            prompt=(
                "Review the exact external side effects. Approval is scoped to these actions and "
                "does not authorize unrelated account or production changes."
            ),
            summary=f"{len(actions)} privileged action request(s) require approval.",
            visual_content=json.dumps({"actions": actions}, indent=2),
            metadata={"actions": actions, "required": False, "conditional": True},
        )

    def ensure_release(self, job: JobState) -> HumanFeedbackRequest | None:
        if not self._settings.enable_human_checkpoints:
            return None
        existing = self._pending_request(job, ApprovalGate.RELEASE)
        if existing is not None or self._is_approved(job, ApprovalGate.RELEASE):
            return existing
        validation = next(
            (
                artifact.metadata.get("validation", {})
                for artifact in job.artifacts
                if artifact.kind == "folder"
            ),
            {},
        )
        release = {
            "release_status": job.release_status.value,
            "publish_allowed_after_approval": job.release_status == ReleaseStatus.VERIFIED,
            "validation": validation,
            "risk_findings": job.risk_findings,
            "artifacts": [
                {"kind": artifact.kind, "name": artifact.name, "url": artifact.url}
                for artifact in job.artifacts
            ],
        }
        return self._create_request(
            job,
            gate=ApprovalGate.RELEASE,
            title="Approve the validated release",
            prompt=(
                "Review the runnable preview, validation evidence, risks, files, and cost. "
                "Approve to unlock release actions, or request a focused revision."
            ),
            summary="The latest runnable checkpoint is ready for final review.",
            visual_content=json.dumps(release, indent=2),
            metadata={"release": release, "required": True},
        )

    def apply_feedback(
        self,
        job: JobState,
        decision: HumanFeedbackDecision,
        message: str | None = None,
    ) -> HumanFeedbackRequest:
        request = job.active_feedback_request()
        if request is None:
            raise ValueError("Job has no active human feedback request.")

        response = (message or "").strip() or None
        if response is not None:
            _reject_prohibited_feedback(job, response)
        if decision == HumanFeedbackDecision.APPROVE:
            job.resolve_active_feedback(HumanFeedbackStatus.APPROVED, response)
            self._checkpoints.record(
                job,
                request.gate,
                HumanFeedbackStatus.APPROVED.value,
                {"checkpoint_id": request.checkpoint_id, "response": response},
            )
            job.set_status(JobStatus.RUNNING)
            metrics.increment("human_feedback_approved")
            return request

        job.resolve_active_feedback(HumanFeedbackStatus.CHANGES_REQUESTED, response)
        self._checkpoints.record(
            job,
            request.gate,
            HumanFeedbackStatus.CHANGES_REQUESTED.value,
            {"checkpoint_id": request.checkpoint_id, "response": response},
        )
        if request.gate == ApprovalGate.PRODUCT_CONTRACT:
            job.cost_ledger = {}
            _reset_for_replan(job, "product_contract_feedback", response)
        elif request.gate == ApprovalGate.PRIVILEGED_ACTION:
            denied = [
                str(item.get("action_id"))
                for item in request.metadata.get("actions", [])
                if isinstance(item, dict) and item.get("action_id")
            ]
            job.request.metadata["denied_privileged_actions"] = list(dict.fromkeys(denied))
            _reset_for_replan(job, "privileged_action_feedback", response)
        else:
            _prepare_release_revision(job, response)
        job.set_status(JobStatus.RETRYING)
        metrics.increment("human_feedback_changes_requested")
        return request

    def release_approved(self, job: JobState) -> bool:
        if not self._settings.enable_human_checkpoints:
            return True
        return self._is_approved(job, ApprovalGate.RELEASE)

    def _pending_request(
        self,
        job: JobState,
        gate: ApprovalGate,
    ) -> HumanFeedbackRequest | None:
        active = job.active_feedback_request()
        if active is not None and active.gate == gate:
            return active
        return None

    def _is_approved(self, job: JobState, gate: ApprovalGate) -> bool:
        return self._checkpoints.status(job, gate) in {
            HumanFeedbackStatus.APPROVED.value,
            HumanFeedbackStatus.AUTO_APPROVED.value,
        }

    def _create_request(
        self,
        job: JobState,
        *,
        gate: ApprovalGate,
        title: str,
        prompt: str,
        summary: str,
        visual_content: str,
        metadata: dict,
    ) -> HumanFeedbackRequest:
        if len(job.feedback_requests) >= self._settings.max_human_checkpoints:
            raise RuntimeError(
                "The configured human-checkpoint limit is too low for the required approval gates."
            )
        request = HumanFeedbackRequest(
            gate=gate,
            worker_kind=None,
            task_id=None,
            attempt=0,
            title=title,
            prompt=prompt,
            summary=summary,
            visual_type="structured_json",
            visual_content=visual_content,
            metadata={**metadata, "stage": gate.value},
        )
        job.add_feedback_request(request)
        self._checkpoints.record(
            job,
            gate,
            HumanFeedbackStatus.PENDING.value,
            {"checkpoint_id": request.checkpoint_id, **metadata},
        )
        metrics.increment("human_checkpoints_created")
        return request


def _reject_prohibited_feedback(job: JobState, response: str) -> None:
    """Stop prohibited instructions entering worker context through a checkpoint reply.

    Input guardrails only inspect the original prompt, so checkpoint feedback is the
    second door into worker instructions and is gated by the same deterministic rules.
    """

    report = check_acceptable_use(response)
    if report.passed:
        return
    error = ProhibitedRequestError(report, source="human_feedback")
    logger.warning(
        "guardrails.prohibited_feedback job_id=%s categories=%s fingerprint=%s",
        job.job_id,
        ",".join(error.categories),
        prompt_fingerprint(response),
    )
    metrics.increment("prohibited_requests")
    raise error


def _reset_for_replan(job: JobState, metadata_key: str, response: str | None) -> None:
    feedback = response or "Revise the plan using the human checkpoint decision."
    job.request.metadata[metadata_key] = feedback
    job.preflight = {}
    job.manifest_generation += 1
    job.tasks = []
    job.worker_results = []
    job.project_spec = {}
    job.design_spec = {}
    job.api_contract = {}
    job.manifest_state = {}
    job.verified_manifest_state = {}
    job.verified_validation = {}
    job.manifest_transaction = {}
    job.artifacts = []
    job.artifact_errors = []
    job.validation_results = []
    job.evaluation = None
    job.release_status = ReleaseStatus.PENDING
    job.touch()


def _prepare_release_revision(job: JobState, response: str | None) -> None:
    feedback = response or "Revise the release candidate using the requested changes."
    target = _revision_target(job, feedback)
    if target is None:
        _reset_for_replan(job, "release_feedback", feedback)
        return
    target.instructions = (
        f"{target.instructions.rstrip()}\n\nHuman release feedback:\n"
        f"- Requested change: {feedback}\n"
        "- Preserve the complete checkpoint and return only the smallest sufficient patch."
    )
    target.status = TaskStatus.PENDING
    target.max_attempts = max(target.max_attempts, target.attempt + 1)
    job.request.metadata["release_feedback"] = feedback
    job.evaluation = None
    job.artifact_errors = []
    job.validation_results = []
    job.touch()


def _revision_target(job: JobState, feedback: str):
    lowered = feedback.lower()
    preferred = (
        WorkerKind.DATABASE
        if any(term in lowered for term in ("database", "schema", "migration"))
        else WorkerKind.BACKEND
        if any(term in lowered for term in ("backend", "api", "server"))
        else WorkerKind.FRONTEND
    )
    return next(
        (task for task in job.tasks if task.worker_kind == preferred),
        job.tasks[0] if job.tasks else None,
    )
