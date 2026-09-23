import json

from software_developer_agent.agents.planner_agent import (
    PlannerAgent,
    _planner_failure_message,
)
from software_developer_agent.config.settings import Settings
from software_developer_agent.integrations.llm_client import LLMResponse
from software_developer_agent.memory.project_context_manager import ProjectContext
from software_developer_agent.models.job_state import JobRequest, WorkerKind


def test_planner_infers_full_stack_for_game_with_records() -> None:
    settings = Settings(app_env="test", enable_llm_calls=False)
    planner = PlannerAgent(settings)

    tasks = planner.plan(
        JobRequest(
            prompt="Build a local game webapp with user records, analytics, and sqlite database",
            project_id="game",
        ),
        ProjectContext(project_id="game", summary=""),
    )

    assert [task.worker_kind for task in tasks] == [
        WorkerKind.DATABASE,
        WorkerKind.BACKEND,
        WorkerKind.FRONTEND,
    ]


def test_planner_honors_explicit_database_exclusion() -> None:
    settings = Settings(app_env="test", enable_llm_calls=False)
    planner = PlannerAgent(settings)

    tasks = planner.plan(
        JobRequest(
            prompt=(
                "Build a simple tic-tac-toe game with two-user and vs-AI modes. "
                "No GitHub, deployment, database, cloud, or persistence is required. "
                "Use a FastAPI backend and include a README."
            ),
            project_id="tic-tac-toe",
        ),
        ProjectContext(project_id="tic-tac-toe", summary=""),
    )

    assert [task.worker_kind for task in tasks] == [
        WorkerKind.BACKEND,
        WorkerKind.FRONTEND,
    ]


def test_planner_honors_in_memory_only_exclusion() -> None:
    workers = PlannerAgent._infer_required_workers(
        "Build a game webapp that stores match state in memory only."
    )

    assert WorkerKind.DATABASE not in workers
    assert workers == [WorkerKind.BACKEND, WorkerKind.FRONTEND]


def test_planner_uses_frontend_pack_when_backend_is_explicitly_excluded() -> None:
    settings = Settings(app_env="test", enable_llm_calls=False)
    planner = PlannerAgent(settings)

    result = planner.create_plan(
        JobRequest(
            prompt=(
                "Build a standalone React Vite browser game with tests. "
                "No backend, database, authentication, deployment, or external API."
            ),
            project_id="standalone-game",
        ),
        ProjectContext(project_id="standalone-game", summary=""),
    )

    assert result.project_spec.capability_id == "react-vite"
    assert [task.worker_kind for task in result.tasks] == [WorkerKind.FRONTEND]
    assert result.tasks[0].capability_id == "react-vite"


def test_llm_planner_deduplicates_workers_and_shares_contract() -> None:
    contract = {
        "backend_port": 8000,
        "frontend_port": 5173,
        "routes": [
            {
                "method": "GET",
                "path": "/api/quote",
                "request_example": None,
                "response_example": {"quote": "example", "index": 0},
                "success_status": 200,
            }
        ],
    }

    class StubLLM:
        def complete(self, system: str, user: str) -> LLMResponse:
            return LLMResponse(
                text=json.dumps(
                    {
                        "api_contract": contract,
                        "tasks": [
                            {
                                "worker_kind": "backend",
                                "title": "API",
                                "instructions": "Implement the quote API.",
                                "depends_on": [],
                            },
                            {
                                "worker_kind": "backend",
                                "title": "Backend docs",
                                "instructions": "Document backend setup in notes.",
                                "depends_on": [],
                            },
                            {
                                "worker_kind": "frontend",
                                "title": "UI",
                                "instructions": "Build the quote UI.",
                                "depends_on": ["API"],
                            },
                        ],
                    }
                )
            )

    planner = PlannerAgent(
        Settings(app_env="test", enable_llm_calls=True),
        StubLLM(),
    )
    result = planner.create_plan(
        JobRequest(prompt="Build a local quote webapp", project_id="quotes"),
        ProjectContext(project_id="quotes", summary=""),
    )

    assert [task.worker_kind for task in result.tasks] == [
        WorkerKind.BACKEND,
        WorkerKind.FRONTEND,
    ]
    assert result.api_contract["routes"] == contract["routes"]
    assert result.api_contract["runtime_connectivity"] == {
        "api_base_strategy": "same_origin_proxy",
        "frontend_api_env": "VITE_API_BASE_URL",
        "backend_cors_env": "CORS_ORIGINS",
        "credentials_mode": "same-origin",
        "protocols": ["http"],
    }
    assert all("/api/quote" in task.instructions for task in result.tasks)


def test_llm_planner_falls_back_when_contract_routes_are_invalid() -> None:
    route = {
        "method": "GET",
        "path": "/api/quote",
        "request_example": None,
        "response_example": {"quote": "example"},
        "success_status": 200,
    }

    class StubLLM:
        def complete(self, system: str, user: str) -> LLMResponse:
            return LLMResponse(
                text=json.dumps(
                    {
                        "api_contract": {
                            "backend_port": 8000,
                            "frontend_port": 5173,
                            "routes": [route, route],
                        },
                        "tasks": [
                            {
                                "worker_kind": "backend",
                                "title": "API",
                                "instructions": "Implement API.",
                            },
                            {
                                "worker_kind": "frontend",
                                "title": "UI",
                                "instructions": "Implement UI.",
                            },
                        ],
                    }
                )
            )

    planner = PlannerAgent(
        Settings(app_env="test", enable_llm_calls=True),
        StubLLM(),
    )

    result = planner.create_plan(
        JobRequest(prompt="Build a quote webapp", project_id="quotes"),
        ProjectContext(project_id="quotes", summary=""),
    )

    assert [task.worker_kind for task in result.tasks] == [
        WorkerKind.BACKEND,
        WorkerKind.FRONTEND,
    ]
    assert result.api_contract["routes"] == []
    assert result.warnings
    assert "deterministic capability plan" in result.warnings[0]


def test_planner_reports_exhausted_openai_quota_actionably() -> None:
    message = _planner_failure_message(
        RuntimeError("429 {'code': 'insufficient_quota', 'message': 'quota exceeded'}")
    )

    assert "quota is exhausted" in message
    assert "billing" in message


def test_planner_adds_shared_upload_limit_to_worker_contracts() -> None:
    planner = PlannerAgent(Settings(app_env="test", enable_llm_calls=False))

    result = planner.create_plan(
        JobRequest(
            prompt="Build a React and FastAPI video upload platform",
            project_id="video-library",
        ),
        ProjectContext(project_id="video-library", summary=""),
    )

    assert result.api_contract["shared_limits"]["max_upload_bytes"] == 104_857_600
    assert all("max_upload_bytes" in task.instructions for task in result.tasks)


def test_planner_adds_authenticated_realtime_connectivity_contract() -> None:
    planner = PlannerAgent(Settings(app_env="test", enable_llm_calls=False))

    result = planner.create_plan(
        JobRequest(
            prompt="Build a React and FastAPI role-based realtime collaboration app",
            project_id="collaboration",
        ),
        ProjectContext(project_id="collaboration", summary=""),
    )

    connectivity = result.api_contract["runtime_connectivity"]
    assert connectivity["api_base_strategy"] == "same_origin_proxy"
    assert connectivity["credentials_mode"] == "include"
    assert connectivity["protocols"] == ["http", "websocket"]
