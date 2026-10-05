from software_developer_agent.capabilities.adapters import resolve_adapter_ids
from software_developer_agent.capabilities.registry import (
    capability_registry,
    required_workers,
    resolve_project_spec,
)
from software_developer_agent.capabilities.templates import deterministic_stack_files
from software_developer_agent.models.job_state import WorkerKind
from software_developer_agent.models.request_policy import derive_request_policy


def test_certified_capability_registry_covers_initial_stacks() -> None:
    assert set(capability_registry()) == {
        "fastapi-api",
        "nextjs-fullstack",
        "node-api",
        "python-cli",
        "react-fastapi",
        "react-node",
        "react-vite",
    }


def test_explicit_stack_selection_wins_over_prompt_inference() -> None:
    spec = resolve_project_spec(
        "Build a FastAPI service",
        {"capability_id": "nextjs-fullstack"},
    )
    assert spec.capability_id == "nextjs-fullstack"
    assert spec.explicitly_selected is True


def test_nextjs_request_does_not_force_python_backend() -> None:
    spec = resolve_project_spec("Build a full-stack Next.js application with route handlers")
    assert spec.capability_id == "nextjs-fullstack"
    assert spec.backend_framework == "Next.js route handlers"
    assert spec.primary_languages == ["TypeScript"]


def test_fastapi_game_selects_react_fastapi_pack() -> None:
    spec = resolve_project_spec("Build a web tic-tac-toe game with a FastAPI backend")
    assert spec.capability_id == "react-fastapi"


def test_domain_adapters_are_composed_without_creating_more_workers() -> None:
    spec = resolve_project_spec("Build an online multiplayer game with WebSocket reconnect support")

    assert "browser-game" in spec.adapter_ids
    assert "realtime" in spec.adapter_ids
    assert spec.adapter_ids[:2] == ["core", f"stack:{spec.capability_id}"]
    assert any("authoritative-state" in criterion for criterion in spec.acceptance_criteria)


def test_sensitive_frontend_requirements_select_fullstack_capability() -> None:
    spec = resolve_project_spec(
        "Build a website with login, admin-only analytics, and a Supabase database"
    )

    assert spec.capability_id == "react-fastapi"
    assert {"auth-rbac", "analytics", "persistence"}.issubset(spec.adapter_ids)


def test_explicit_adapters_are_merged_with_detected_adapters() -> None:
    adapter_ids = resolve_adapter_ids(
        "Build a live chat with WebSocket reconnect behavior",
        "react-node",
        {"adapter_ids": ["auth-rbac"]},
    )

    assert "auth-rbac" in adapter_ids
    assert "realtime" in adapter_ids


def test_negative_backend_constraint_keeps_standalone_frontend() -> None:
    prompt = (
        "Build a standalone React Vite browser game. "
        "No backend, database, authentication, or deployment."
    )
    policy = derive_request_policy(prompt)
    spec = resolve_project_spec(prompt, policy=policy)

    assert spec.capability_id == "react-vite"
    assert policy.excludes("backend")
    assert [worker.value for worker in required_workers(spec, policy)] == ["frontend"]


def test_fastapi_persistence_template_configures_postgresql_only_when_requested() -> None:
    persistent = deterministic_stack_files(
        "react-fastapi",
        WorkerKind.BACKEND,
        "Build a FastAPI service with PostgreSQL persistence",
        "persistent-api",
    )
    standalone = deterministic_stack_files(
        "react-fastapi",
        WorkerKind.BACKEND,
        "Build a stateless FastAPI service",
        "stateless-api",
    )

    assert persistent is not None
    assert standalone is not None
    assert "create_engine(" in persistent["backend/src/app/main.py"]
    assert "DATABASE_URL" in persistent["backend/.env.example"]
    assert "sqlalchemy==2.0.36" in persistent["backend/pyproject.toml"]
    assert "CORS_ORIGINS" in standalone["backend/.env.example"]
    assert "DATABASE_URL" not in standalone["backend/.env.example"]
    assert "sqlalchemy==2.0.36" not in standalone["backend/pyproject.toml"]


def test_node_persistence_template_configures_postgresql_only_when_requested() -> None:
    persistent = deterministic_stack_files(
        "react-node",
        WorkerKind.BACKEND,
        "Build an Express service with a PostgreSQL database",
        "persistent-node",
    )
    standalone = deterministic_stack_files(
        "react-node",
        WorkerKind.BACKEND,
        "Build a stateless Express service",
        "stateless-node",
    )

    assert persistent is not None
    assert standalone is not None
    assert "new Pool(" in persistent["backend/src/app.ts"]
    assert '"pg": "8.16.3"' in persistent["backend/package.json"]
    assert "DATABASE_URL" in persistent["backend/.env.example"]
    assert "backend/.env.example" not in standalone
