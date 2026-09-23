from software_developer_agent.agents.design_director_agent import DesignDirectorAgent
from software_developer_agent.config.settings import Settings
from software_developer_agent.models.job_state import JobRequest, JobState, JobTask, WorkerKind


class InvalidDesignLLM:
    def complete(self, system: str, user: str):
        raise RuntimeError("invalid design response")


def test_design_director_uses_deterministic_contract_on_model_failure() -> None:
    job = JobState(
        request=JobRequest(prompt="Build a premium gallery"),
        tasks=[
            JobTask(
                worker_kind=WorkerKind.FRONTEND,
                title="Frontend",
                instructions="Build it.",
            )
        ],
    )
    director = DesignDirectorAgent(
        Settings(app_env="development", enable_llm_calls=True),
        InvalidDesignLLM(),
    )

    spec = director.create_spec(job)

    assert spec["visual_direction"]["tone"] == "premium, minimal, content-led"
    assert job.warnings
