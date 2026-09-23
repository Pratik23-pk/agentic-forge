from software_developer_agent.artifacts.project_generator import ProjectArtifactGenerator
from software_developer_agent.models.job_state import WorkerKind
from software_developer_agent.prompts.system_prompts import (
    ARTIFACT_WRITER_SYSTEM_PROMPT,
    BACKEND_SYSTEM_PROMPT,
    DATABASE_SYSTEM_PROMPT,
    EVALUATOR_SYSTEM_PROMPT,
    FRONTEND_SYSTEM_PROMPT,
    PLANNER_SYSTEM_PROMPT,
    get_worker_system_prompt,
)


def test_all_six_system_prompts_are_registered() -> None:
    prompts = [
        PLANNER_SYSTEM_PROMPT,
        DATABASE_SYSTEM_PROMPT,
        BACKEND_SYSTEM_PROMPT,
        FRONTEND_SYSTEM_PROMPT,
        EVALUATOR_SYSTEM_PROMPT,
        ARTIFACT_WRITER_SYSTEM_PROMPT,
    ]

    assert all("Return only compact JSON" in prompt for prompt in prompts[:5])
    assert get_worker_system_prompt(WorkerKind.DATABASE) == DATABASE_SYSTEM_PROMPT
    assert get_worker_system_prompt(WorkerKind.BACKEND) == BACKEND_SYSTEM_PROMPT
    assert get_worker_system_prompt(WorkerKind.FRONTEND) == FRONTEND_SYSTEM_PROMPT
    assert ProjectArtifactGenerator.system_prompt == ARTIFACT_WRITER_SYSTEM_PROMPT


def test_system_prompts_enforce_generation_contracts() -> None:
    assert "An explicit exclusion always overrides keyword matching" in PLANNER_SYSTEM_PROMPT
    assert "Never introduce SQLite" in DATABASE_SYSTEM_PROMPT
    assert "Never reference a dependency file that is not generated" in BACKEND_SYSTEM_PROMPT
    assert "EmailStr requires the certified email-validator package" in BACKEND_SYSTEM_PROMPT
    assert "Never use `latest` dependency versions" in FRONTEND_SYSTEM_PROMPT
    assert "import `defineConfig` from `vitest/config`" in FRONTEND_SYSTEM_PROMPT
    assert "include Vite client environment types" in FRONTEND_SYSTEM_PROMPT
    assert "register Testing Library `cleanup`" in FRONTEND_SYSTEM_PROMPT
    assert "never an unrelated plain object" in FRONTEND_SYSTEM_PROMPT
    assert "do not add TypeScript generic arguments to Vitest matchers" in FRONTEND_SYSTEM_PROMPT
    assert "preserve lifecycle nullability across backend and frontend" in FRONTEND_SYSTEM_PROMPT
    assert "terminal and empty-state response shapes" in FRONTEND_SYSTEM_PROMPT
    assert "omitting a contract file is an invalid response" in FRONTEND_SYSTEM_PROMPT
    assert "Tests must import the\napplication component" in FRONTEND_SYSTEM_PROMPT
    assert "never replace a requested product with a generic scaffold" in FRONTEND_SYSTEM_PROMPT
    assert '"replan_required": false' in EVALUATOR_SYSTEM_PROMPT
    assert "Evaluate the final checkpoint" in EVALUATOR_SYSTEM_PROMPT
    assert "Never reference requirements.txt unless it exists" in ARTIFACT_WRITER_SYSTEM_PROMPT
