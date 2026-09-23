from dataclasses import dataclass

from software_developer_agent.models.job_state import JobState, WorkerKind


@dataclass(slots=True)
class RetryDecision:
    allowed: bool
    reason: str


class StrictRetryPolicy:
    def __init__(self, max_worker_attempts: int, max_total_attempts: int) -> None:
        self._max_worker_attempts = max_worker_attempts
        self._max_total_attempts = max_total_attempts

    def can_retry(self, job: JobState, worker_kind: WorkerKind) -> RetryDecision:
        total_attempts = sum(task.attempt for task in job.tasks)
        if total_attempts >= self._max_total_attempts:
            return RetryDecision(False, "Total retry budget exhausted.")

        worker_attempts = max(
            (task.attempt for task in job.tasks if task.worker_kind == worker_kind),
            default=0,
        )
        if worker_attempts >= self._max_worker_attempts:
            return RetryDecision(False, f"Retry budget exhausted for {worker_kind.value}.")

        return RetryDecision(True, "Retry allowed.")
