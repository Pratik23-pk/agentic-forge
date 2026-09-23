from software_developer_agent.capabilities.templates import deterministic_stack_files
from software_developer_agent.models.job_state import WorkerKind


def test_postgres_auth_template_does_not_imply_supabase() -> None:
    files = deterministic_stack_files(
        "react-fastapi",
        WorkerKind.DATABASE,
        "Build a video platform with authentication and PostgreSQL persistence.",
        "video-library",
    )

    assert files is not None
    assert files["database/.env.example"] == "DATABASE_URL=\n"
    assert "auth.users" not in files["database/migrations/001_initial.sql"]
    assert "storage.buckets" not in files["database/migrations/001_initial.sql"]


def test_explicit_supabase_template_includes_supabase_configuration() -> None:
    files = deterministic_stack_files(
        "react-fastapi",
        WorkerKind.DATABASE,
        "Build an authenticated Supabase app with media upload and PostgreSQL persistence.",
        "media-library",
    )

    assert files is not None
    assert "SUPABASE_URL=" in files["database/.env.example"]
    assert "SUPABASE_ANON_KEY=" in files["database/.env.example"]
    assert "auth.users" in files["database/migrations/001_initial.sql"]
    assert "storage.buckets" in files["database/migrations/001_initial.sql"]


def test_explicit_supabase_exclusion_is_respected() -> None:
    files = deterministic_stack_files(
        "react-fastapi",
        WorkerKind.DATABASE,
        "Build an authenticated PostgreSQL app without Supabase.",
        "local-auth",
    )

    assert files is not None
    assert files["database/.env.example"] == "DATABASE_URL=\n"
    assert "auth.users" not in files["database/migrations/001_initial.sql"]
