from software_developer_agent.config.settings import Settings
from software_developer_agent.memory.approval_checkpoint import ApprovalCheckpointManager
from software_developer_agent.models.job_state import ApprovalGate, JobRequest, JobState
from software_developer_agent.orchestration.approval_policy import privileged_actions_for_job


def test_heritage_request_requires_no_privileged_action() -> None:
    job = JobState(
        request=JobRequest(
            prompt=(
                "Build a one-page website showing images of India's heritage. "
                "No database, deployment, or GitHub push."
            )
        ),
        request_policy={
            "excluded_capabilities": ["database", "deployment", "github"],
        },
    )

    assert privileged_actions_for_job(job) == []


def test_remote_repository_write_requires_approval() -> None:
    job = JobState(
        request=JobRequest(prompt="Build the website and push it to GitHub after validation.")
    )

    actions = privileged_actions_for_job(job)

    assert [item["action_id"] for item in actions] == ["github_write"]


def test_approval_state_is_checkpointed_separately_from_execution() -> None:
    settings = Settings(
        app_env="test",
        enable_persistence=False,
        enable_langgraph_checkpointing=True,
    )
    manager = ApprovalCheckpointManager(settings)
    job = JobState(request=JobRequest(prompt="Build a dashboard"))

    manager.record(job, ApprovalGate.PRODUCT_CONTRACT, "pending")
    manager.record(job, ApprovalGate.PRODUCT_CONTRACT, "approved")

    assert manager.status(job, ApprovalGate.PRODUCT_CONTRACT) == "approved"
    assert job.approval_state["revision"] == 2
    assert job.loop_count == 0
