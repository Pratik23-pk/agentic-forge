from dataclasses import dataclass, field
from enum import StrEnum

from software_developer_agent.models.job_state import JobState, JobStatus, WorkerKind
from software_developer_agent.orchestration.retry_policy import StrictRetryPolicy


class RouteAction(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    RETRY = "retry"
    REPLAN = "replan"
    HUMAN_FEEDBACK = "human_feedback"


@dataclass(slots=True)
class RouteDecision:
    action: RouteAction
    reason: str
    retry_targets: list[WorkerKind] = field(default_factory=list)


class ConditionalRouter:
    def __init__(self, retry_policy: StrictRetryPolicy) -> None:
        self._retry_policy = retry_policy

    def route(self, job: JobState) -> RouteDecision:
        if job.status == JobStatus.AWAITING_HUMAN_FEEDBACK:
            return RouteDecision(RouteAction.HUMAN_FEEDBACK, "Job is waiting for human feedback.")

        if job.status in {JobStatus.BLOCKED, JobStatus.FAILED}:
            return RouteDecision(RouteAction.FAILURE, "Job is already blocked or failed.")

        if job.evaluation is None:
            return RouteDecision(RouteAction.FAILURE, "Evaluator did not produce a result.")

        if job.evaluation.passed:
            return RouteDecision(RouteAction.SUCCESS, "Evaluator passed all checks.")

        if job.evaluation.replan_required:
            return RouteDecision(
                RouteAction.REPLAN,
                job.evaluation.failure_reason or "Evaluator requested a new plan.",
            )

        if not job.evaluation.retry_targets:
            return RouteDecision(
                RouteAction.FAILURE,
                job.evaluation.failure_reason or "Evaluator failed without retry target.",
            )

        allowed_targets: list[WorkerKind] = []
        denial_reasons: list[str] = []
        for target in job.evaluation.retry_targets:
            decision = self._retry_policy.can_retry(job, target)
            if decision.allowed:
                allowed_targets.append(target)
            else:
                denial_reasons.append(decision.reason)

        if not allowed_targets:
            return RouteDecision(
                RouteAction.FAILURE,
                "; ".join(denial_reasons) or "No retry targets allowed.",
            )

        return RouteDecision(
            RouteAction.RETRY,
            "Targeted retry scheduled.",
            retry_targets=allowed_targets,
        )
