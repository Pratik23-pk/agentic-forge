from software_developer_agent.models.job_state import (
    EvaluationResult,
    JobRequest,
    JobState,
    JobTask,
    WorkerKind,
)
from software_developer_agent.orchestration.conditional_router import ConditionalRouter, RouteAction
from software_developer_agent.orchestration.retry_policy import StrictRetryPolicy


def test_router_returns_success_when_evaluation_passes() -> None:
    job = JobState(request=JobRequest(prompt="Build backend"))
    job.evaluation = EvaluationResult(passed=True)

    router = ConditionalRouter(StrictRetryPolicy(max_worker_attempts=2, max_total_attempts=4))
    decision = router.route(job)

    assert decision.action == RouteAction.SUCCESS


def test_router_schedules_allowed_targeted_retry() -> None:
    job = JobState(request=JobRequest(prompt="Build frontend"))
    job.tasks = [JobTask(worker_kind=WorkerKind.FRONTEND, title="UI", instructions="Build UI")]
    job.tasks[0].attempt = 1
    job.evaluation = EvaluationResult(passed=False, retry_targets=[WorkerKind.FRONTEND])

    router = ConditionalRouter(StrictRetryPolicy(max_worker_attempts=2, max_total_attempts=4))
    decision = router.route(job)

    assert decision.action == RouteAction.RETRY
    assert decision.retry_targets == [WorkerKind.FRONTEND]


def test_router_requests_replan_before_targeted_retry() -> None:
    job = JobState(request=JobRequest(prompt="Build frontend"))
    job.evaluation = EvaluationResult(
        passed=False,
        retry_targets=[WorkerKind.FRONTEND],
        replan_required=True,
        failure_reason="Database task was explicitly excluded.",
    )

    router = ConditionalRouter(StrictRetryPolicy(max_worker_attempts=2, max_total_attempts=4))
    decision = router.route(job)

    assert decision.action == RouteAction.REPLAN
    assert decision.reason == "Database task was explicitly excluded."


def test_retry_budget_is_per_task_attempt_not_task_count() -> None:
    job = JobState(request=JobRequest(prompt="Build backend"))
    job.tasks = [
        JobTask(worker_kind=WorkerKind.BACKEND, title="API", instructions="Build API"),
        JobTask(worker_kind=WorkerKind.BACKEND, title="Docs", instructions="Build docs"),
    ]
    for task in job.tasks:
        task.attempt = 1

    decision = StrictRetryPolicy(max_worker_attempts=2, max_total_attempts=4).can_retry(
        job,
        WorkerKind.BACKEND,
    )

    assert decision.allowed
