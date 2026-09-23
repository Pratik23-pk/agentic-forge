from dataclasses import dataclass

from software_developer_agent.models.job_state import JobState


@dataclass(slots=True)
class LoopDecision:
    allowed: bool
    message: str


class LoopCountInterceptor:
    def __init__(self, max_loops: int) -> None:
        self._max_loops = max_loops

    def enter_loop(self, job: JobState) -> LoopDecision:
        job.loop_count += 1
        job.touch()
        rejected_candidate_credit = sum(task.repair_rejections for task in job.tasks)
        effective_limit = self._max_loops + rejected_candidate_credit
        if job.loop_count > effective_limit:
            return LoopDecision(
                allowed=False,
                message=f"Job exceeded max loop count of {effective_limit}.",
            )
        return LoopDecision(allowed=True, message="Loop allowed.")
