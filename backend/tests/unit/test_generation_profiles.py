from software_developer_agent.config.settings import Settings
from software_developer_agent.models.job_state import JobRequest, JobState
from software_developer_agent.observability.cost_ledger import GlobalCostLedger
from software_developer_agent.orchestration.approval_policy import approval_contract
from software_developer_agent.orchestration.generation_profiles import (
    prepare_job_preflight,
    validate_budget_request,
)


def test_simple_frontend_request_routes_to_standard_profile() -> None:
    settings = Settings(app_env="test")
    job = JobState(
        request=JobRequest(
            prompt="Build a polished one-page portfolio with this uploaded photo.",
            metadata={
                "generation_profile": "auto",
                "authorized_budget_usd": 1.0,
                "uploaded_assets": [{"kind": "image"}],
            },
        )
    )

    preflight = prepare_job_preflight(job, settings)

    assert preflight["recommended_profile"] == "standard"
    assert preflight["effective_profile"] == "standard"
    assert preflight["uploaded_media"] == {"images": 1, "videos": 0}


def test_negative_capability_terms_do_not_force_advanced_recommendation() -> None:
    settings = Settings(app_env="test")
    job = JobState(
        request=JobRequest(
            prompt=(
                "Build a one-page media story using my uploaded image and video. "
                "No backend, database, authentication, payments, deployment, or cloud."
            ),
            metadata={
                "generation_profile": "standard",
                "authorized_budget_usd": 1.0,
                "uploaded_assets": [{"kind": "image"}, {"kind": "video"}],
            },
        )
    )

    preflight = prepare_job_preflight(job, settings)

    assert preflight["recommended_profile"] == "standard"
    assert preflight["signals"] == []


def test_full_stack_media_request_routes_to_advanced_profile() -> None:
    settings = Settings(app_env="test")
    job = JobState(
        request=JobRequest(
            prompt=(
                "Build a role-based video platform with login, Supabase database, uploads, "
                "streaming, payments, and deployment."
            ),
            metadata={
                "generation_profile": "auto",
                "uploaded_assets": [{"kind": "image"}, {"kind": "video"}],
            },
        )
    )

    preflight = prepare_job_preflight(job, settings)
    GlobalCostLedger(settings).initialize(job)

    assert preflight["recommended_profile"] == "advanced"
    assert preflight["effective_profile"] == "advanced"
    assert preflight["authorized_budget_usd"] == settings.default_advanced_run_budget_usd
    assert job.cost_ledger["hard_limit_usd"] == settings.default_advanced_run_budget_usd
    assert job.cost_ledger["normal_limit_usd"] == settings.default_advanced_run_budget_usd


def test_user_approval_contract_hides_internal_budget_details() -> None:
    settings = Settings(app_env="test")
    job = JobState(
        request=JobRequest(
            prompt="Build a role-based application with authentication and a database.",
            metadata={"generation_profile": "auto"},
        )
    )

    prepare_job_preflight(job, settings)
    contract = approval_contract(job)

    assert "authorized_budget_usd" in job.preflight
    assert "estimated_cost_usd" in job.preflight
    assert "authorized_budget_usd" not in contract["generation_preflight"]
    assert "estimated_cost_usd" not in contract["generation_preflight"]


def test_standard_profile_cannot_authorize_more_than_one_dollar() -> None:
    settings = Settings(app_env="test")

    try:
        validate_budget_request("standard", 1.1, settings)
    except ValueError as exc:
        assert "no more than $1.00" in str(exc)
    else:
        raise AssertionError("Standard mode accepted an over-limit budget.")


def test_advanced_profile_accepts_explicit_upfront_budget() -> None:
    settings = Settings(app_env="test", maximum_advanced_run_budget_usd=5.0)

    assert validate_budget_request("advanced", 2.5, settings) == 2.5
