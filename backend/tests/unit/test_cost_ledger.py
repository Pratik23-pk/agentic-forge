import pytest

from software_developer_agent.config.settings import Settings
from software_developer_agent.models.job_state import JobRequest, JobState, JobTask, WorkerKind
from software_developer_agent.observability.cost_ledger import (
    BudgetExceededError,
    GlobalCostLedger,
)
from software_developer_agent.observability.cost_tracker import TokenUsage


def test_cost_ledger_records_cached_and_output_token_costs() -> None:
    ledger = GlobalCostLedger(Settings(app_env="test"))
    job = JobState(request=JobRequest(prompt="Build a gallery"))

    cost = ledger.record(
        job,
        node="planner",
        model="gpt-5.6-terra",
        usage=TokenUsage(
            prompt_tokens=10_000,
            cached_prompt_tokens=4_000,
            completion_tokens=2_000,
            reasoning_tokens=500,
        ),
    )

    assert cost == pytest.approx(0.0368)
    assert job.cost_ledger["spent_usd"] == pytest.approx(0.0368)
    assert job.cost_ledger["reasoning_tokens"] == 500


def test_normal_nodes_cannot_reserve_beyond_normal_budget() -> None:
    settings = Settings(
        app_env="test",
        normal_run_budget_usd=0.01,
        maximum_run_budget_usd=1.0,
    )
    ledger = GlobalCostLedger(settings)
    job = JobState(request=JobRequest(prompt="Build a gallery"))

    with pytest.raises(BudgetExceededError):
        ledger.authorize(
            job,
            node="design",
            model="gpt-5.6-sol",
            estimated_prompt_tokens=3_000,
            requested_output_tokens=1_000,
        )


def test_repair_nodes_use_the_hard_repair_ceiling() -> None:
    settings = Settings(
        app_env="test",
        normal_run_budget_usd=0.01,
        maximum_run_budget_usd=1.0,
    )
    ledger = GlobalCostLedger(settings)
    job = JobState(request=JobRequest(prompt="Repair a gallery"))

    allowed = ledger.authorize(
        job,
        node="repair.sol",
        model="gpt-5.6-sol",
        estimated_prompt_tokens=3_000,
        requested_output_tokens=1_000,
    )

    assert allowed == 1_000
    assert job.cost_ledger["budget_phase"] == "repair"


def test_post_repair_evaluator_uses_the_hard_repair_ceiling() -> None:
    settings = Settings(
        app_env="test",
        normal_run_budget_usd=0.01,
        maximum_run_budget_usd=1.0,
    )
    ledger = GlobalCostLedger(settings)
    job = JobState(request=JobRequest(prompt="Repair a gallery"))

    ledger.authorize(
        job,
        node="repair.terra",
        model="gpt-5.6-terra",
        estimated_prompt_tokens=1_000,
        requested_output_tokens=1_000,
    )
    ledger.record(
        job,
        node="repair.terra",
        model="gpt-5.6-terra",
        usage=TokenUsage(prompt_tokens=1_000, completion_tokens=1_000),
    )

    allowed = ledger.authorize(
        job,
        node="evaluator",
        model="gpt-5.6-luna",
        estimated_prompt_tokens=1_000,
        requested_output_tokens=500,
    )

    assert job.cost_ledger["spent_usd"] > settings.normal_run_budget_usd
    assert allowed == 500


def test_cost_ledger_caps_repeated_calls_per_node() -> None:
    ledger = GlobalCostLedger(Settings(app_env="test", max_llm_calls_per_node=1))
    job = JobState(request=JobRequest(prompt="Build a gallery"))

    ledger.authorize(
        job,
        node="worker.frontend",
        model="gpt-5.6-luna",
        estimated_prompt_tokens=100,
        requested_output_tokens=500,
    )

    with pytest.raises(BudgetExceededError, match="Model-call limit exhausted"):
        ledger.authorize(
            job,
            node="worker.frontend",
            model="gpt-5.6-luna",
            estimated_prompt_tokens=100,
            requested_output_tokens=500,
        )


def test_denied_budget_authorization_does_not_consume_call_limit() -> None:
    ledger = GlobalCostLedger(
        Settings(
            app_env="test",
            normal_run_budget_usd=0.01,
            maximum_run_budget_usd=1.0,
            max_llm_calls_per_node=1,
        )
    )
    job = JobState(request=JobRequest(prompt="Build a gallery"))

    with pytest.raises(BudgetExceededError, match="Cost budget exhausted"):
        ledger.authorize(
            job,
            node="worker.frontend",
            model="gpt-5.6-sol",
            estimated_prompt_tokens=10_000,
            requested_output_tokens=500,
        )

    assert job.cost_ledger["authorizations"] == {}


def test_full_stack_worker_uses_hard_completion_reserve_instead_of_truncation() -> None:
    ledger = GlobalCostLedger(
        Settings(
            app_env="test",
            normal_run_budget_usd=0.25,
            maximum_run_budget_usd=1.0,
        )
    )
    job = JobState(
        request=JobRequest(prompt="Build a full-stack app"),
        tasks=[
            JobTask(worker_kind=WorkerKind.BACKEND, title="Backend", instructions="Build API"),
            JobTask(worker_kind=WorkerKind.FRONTEND, title="Frontend", instructions="Build UI"),
        ],
    )
    ledger.initialize(job)
    job.cost_ledger["spent_usd"] = 0.20

    allowed = ledger.authorize(
        job,
        node="worker.frontend",
        model="gpt-5.6-terra",
        estimated_prompt_tokens=5_000,
        requested_output_tokens=12_000,
    )

    assert allowed == 12_000
    assert job.cost_ledger["budget_phase"] == "completion_reserve"


def test_single_worker_project_stays_within_normal_budget() -> None:
    ledger = GlobalCostLedger(
        Settings(
            app_env="test",
            normal_run_budget_usd=0.25,
            maximum_run_budget_usd=1.0,
        )
    )
    job = JobState(
        request=JobRequest(prompt="Build a frontend"),
        tasks=[
            JobTask(worker_kind=WorkerKind.FRONTEND, title="Frontend", instructions="Build UI")
        ],
    )
    ledger.initialize(job)
    job.cost_ledger["spent_usd"] = 0.20

    allowed = ledger.authorize(
        job,
        node="worker.frontend",
        model="gpt-5.6-terra",
        estimated_prompt_tokens=2_000,
        requested_output_tokens=12_000,
    )

    assert allowed < 12_000
    assert job.cost_ledger["budget_phase"] == "normal"
