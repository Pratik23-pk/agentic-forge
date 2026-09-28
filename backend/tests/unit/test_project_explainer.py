import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from software_developer_agent.api.routes import explanations as explanation_routes
from software_developer_agent.config.settings import Settings
from software_developer_agent.explanations.project_explainer import (
    EXPLAINER_REFUSAL,
    ExplainerBudgetError,
    ExplainerPromptLimitError,
    answer_project_question,
    build_project_evidence,
    initialize_project_explanation,
)
from software_developer_agent.integrations.llm_client import LLMResponse
from software_developer_agent.models.job_state import (
    JobArtifact,
    JobRequest,
    JobState,
    JobStatus,
    ReleaseStatus,
)
from software_developer_agent.observability.cost_tracker import TokenUsage
from software_developer_agent.orchestration.redis_queue import InMemoryJobQueue
from software_developer_agent.persistence.job_store import InMemoryJobStore


class FakeExplainerClient:
    def __init__(self, answer: str | None = None) -> None:
        self.calls = 0
        self.answer = answer or (
            "The frontend is a React application that renders the verified user interface."
        )

    def complete(self, system: str, user: str) -> LLMResponse:
        self.calls += 1
        assert "read-only Project Explainer" in system
        assert "frontend/src/App.tsx" in user
        return LLMResponse(
            text=json.dumps(
                {
                    "answer": self.answer,
                    "citations": ["frontend/src/App.tsx", "not/a/real/file.ts"],
                    "refusal": False,
                }
            ),
            usage=TokenUsage(prompt_tokens=1_000, completion_tokens=300),
        )


def _verified_job(tmp_path) -> tuple[JobState, Settings]:
    generated_root = tmp_path / "generated"
    project_root = generated_root / "demo-app"
    (project_root / "frontend" / "src").mkdir(parents=True)
    (project_root / "frontend" / "src" / "App.tsx").write_text(
        "export function App() { return <main>Demo</main>; }",
        encoding="utf-8",
    )
    (project_root / "frontend" / "package.json").write_text(
        '{"dependencies":{"react":"19.1.0"}}',
        encoding="utf-8",
    )
    (project_root / ".env.example").write_text(
        "VITE_API_URL=http://localhost:8000\nSECRET_TOKEN=do-not-copy\n",
        encoding="utf-8",
    )
    job = JobState(
        request=JobRequest(prompt="Build a polished React app", project_id="Demo App"),
        status=JobStatus.SUCCEEDED,
        release_status=ReleaseStatus.VERIFIED,
        validation_results=[{"name": "frontend_build", "passed": True}],
    )
    job.add_artifact(
        JobArtifact(
            artifact_id="project-folder",
            kind="folder",
            name="demo-app",
            path=str(project_root),
            url=f"/api/jobs/{job.job_id}/files",
        )
    )
    settings = Settings(
        app_env="test",
        generated_projects_dir=generated_root,
        enable_llm_calls=True,
        enable_project_explainer=True,
        openai_api_key="test-key",
        openai_explainer_model="gpt-6-luna",
    )
    return job, settings


def test_explainer_initialization_is_deterministic_and_migrates_static_guides(tmp_path) -> None:
    job, settings = _verified_job(tmp_path)
    job.project_explanation = {"status": "ready", "version": "1.0", "guide": {"title": "Old"}}

    first = initialize_project_explanation(job, settings=settings)
    second = initialize_project_explanation(job, settings=settings)

    assert first == second
    assert first["version"] == "2.0"
    assert first["mode"] == "read_only_conversation"
    assert first["prompt_limit"] == 10
    assert first["remaining_prompts"] == 10
    assert first["spent_usd"] == 0.0
    assert first["messages"] == []
    assert "guide" not in first


def test_explainer_answers_from_evidence_and_tracks_separate_cost(tmp_path) -> None:
    job, settings = _verified_job(tmp_path)
    client = FakeExplainerClient()

    result = answer_project_question(
        job,
        "What frontend was built?",
        settings=settings,
        llm_client=client,
    )

    assert client.calls == 1
    assert result["prompt_count"] == 1
    assert result["remaining_prompts"] == 9
    assert result["spent_usd"] == 0.000275
    assert result["messages"][-1]["citations"] == ["frontend/src/App.tsx"]
    assert result["messages"][-1]["refusal"] is False
    assert job.cost_ledger == {}


def test_repeated_question_uses_cached_answer_without_model_cost(tmp_path) -> None:
    job, settings = _verified_job(tmp_path)
    client = FakeExplainerClient()

    first = answer_project_question(
        job,
        "What frontend was built?",
        settings=settings,
        llm_client=client,
    )
    second = answer_project_question(
        job,
        "WHAT frontend was built?!",
        settings=settings,
        llm_client=client,
    )

    assert client.calls == 1
    assert second["prompt_count"] == 2
    assert second["spent_usd"] == first["spent_usd"]
    assert second["messages"][-1]["cached"] is True


def test_code_and_modification_requests_are_rejected_without_llm(tmp_path) -> None:
    job, settings = _verified_job(tmp_path)
    client = FakeExplainerClient()

    result = answer_project_question(
        job,
        "Give me the full App.tsx code and modify the frontend colors.",
        settings=settings,
        llm_client=client,
    )

    assert client.calls == 0
    assert result["prompt_count"] == 1
    assert result["spent_usd"] == 0.0
    assert result["messages"][-1]["content"] == EXPLAINER_REFUSAL
    assert result["messages"][-1]["refusal"] is True


def test_code_like_model_output_is_replaced_by_fixed_refusal(tmp_path) -> None:
    job, settings = _verified_job(tmp_path)
    client = FakeExplainerClient(answer="```tsx\nexport function App() {}\n```")

    result = answer_project_question(
        job,
        "Explain the frontend structure.",
        settings=settings,
        llm_client=client,
    )

    assert client.calls == 1
    assert result["messages"][-1]["content"] == EXPLAINER_REFUSAL
    assert result["messages"][-1]["refusal"] is True


def test_explainer_enforces_exactly_ten_submissions(tmp_path) -> None:
    job, settings = _verified_job(tmp_path)
    client = FakeExplainerClient()

    for attempt in range(10):
        answer_project_question(
            job,
            f"Give me the full source code for attempt {attempt}.",
            settings=settings,
            llm_client=client,
        )

    with pytest.raises(ExplainerPromptLimitError, match="limit reached"):
        answer_project_question(
            job,
            "What frontend was built?",
            settings=settings,
            llm_client=client,
        )

    assert client.calls == 0
    assert job.project_explanation["prompt_count"] == 10
    assert job.project_explanation["remaining_prompts"] == 0


def test_explainer_refuses_a_call_that_cannot_fit_the_budget(tmp_path) -> None:
    job, settings = _verified_job(tmp_path)
    settings = settings.model_copy(
        update={
            "explainer_budget_usd": 0.00001,
            "explainer_per_prompt_budget_usd": 0.00001,
        }
    )
    client = FakeExplainerClient()

    with pytest.raises(ExplainerBudgetError, match="safely answer"):
        answer_project_question(
            job,
            "What frontend was built?",
            settings=settings,
            llm_client=client,
        )

    assert client.calls == 0
    assert job.project_explanation["prompt_count"] == 0


def test_evidence_exposes_environment_names_but_not_values(tmp_path) -> None:
    job, settings = _verified_job(tmp_path)

    evidence = build_project_evidence(job, settings)
    payload = json.dumps(evidence)

    assert "VITE_API_URL" in evidence["environment_variable_names"]
    assert "SECRET_TOKEN" in evidence["environment_variable_names"]
    assert "do-not-copy" not in payload
    assert "frontend/src/App.tsx" in evidence["file_manifest"]


def test_project_explainer_routes_initialize_and_answer(tmp_path, monkeypatch) -> None:
    job, settings = _verified_job(tmp_path)
    store = InMemoryJobStore()
    queue = InMemoryJobQueue()
    store.save(job)
    monkeypatch.setattr(explanation_routes, "get_job_store", lambda: store)
    monkeypatch.setattr(explanation_routes, "get_job_queue", lambda: queue)
    monkeypatch.setattr(explanation_routes, "get_settings", lambda: settings)

    def fake_answer(current: JobState, question: str, **_: object) -> dict[str, object]:
        current.project_explanation["messages"] = [
            {"role": "user", "content": question},
            {"role": "assistant", "content": "A verified React frontend."},
        ]
        current.project_explanation["prompt_count"] = 1
        current.project_explanation["remaining_prompts"] = 9
        store.save(current)
        return current.project_explanation

    monkeypatch.setattr(explanation_routes, "answer_project_question", fake_answer)
    app = FastAPI()
    app.include_router(explanation_routes.router, prefix="/api")
    client = TestClient(app)

    initial = client.get(f"/api/jobs/{job.job_id}/guide")
    answered = client.post(
        f"/api/jobs/{job.job_id}/guide/messages",
        json={"question": "What frontend was built?"},
    )

    assert initial.status_code == 200
    assert initial.json()["explanation"]["remaining_prompts"] == 10
    assert answered.status_code == 200
    assert answered.json()["explanation"]["remaining_prompts"] == 9
    assert answered.json()["explanation"]["messages"][-1]["role"] == "assistant"
