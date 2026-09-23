from software_developer_agent.models.request_policy import derive_request_policy


def test_request_policy_understands_negative_capability_list() -> None:
    policy = derive_request_policy(
        "Build a FastAPI and React app. No GitHub, deployment, database, cloud, "
        "Docker, analytics, or external APIs are required."
    )

    assert policy.excludes("database")
    assert policy.excludes("persistence")
    assert policy.excludes("docker")
    assert policy.excludes("github")
    assert policy.excludes("deployment")
    assert policy.excludes("cloud")
    assert policy.excludes("analytics")
    assert policy.excludes("external_apis")


def test_request_policy_requires_positive_database_intent() -> None:
    local_policy = derive_request_policy("Build a game with user scores and analytics.")
    database_policy = derive_request_policy(
        "Build a game and persist user scores in a PostgreSQL database."
    )

    assert not local_policy.requests("database")
    assert database_policy.requests("database")
    assert database_policy.requests("persistence")


def test_request_policy_rejects_unrequested_infrastructure_paths() -> None:
    policy = derive_request_policy("Build a local FastAPI app.")

    assert policy.forbidden_path_reason("docker-compose.yml")
    assert policy.forbidden_path_reason("database/schema.sql")
    assert policy.forbidden_path_reason(".github/workflows/ci.yml")


def test_no_server_does_not_remove_python_implementation_worker() -> None:
    policy = derive_request_policy(
        "Build a Python command-line utility. It requires no server or database."
    )

    assert not policy.excludes("backend")
    assert policy.excludes("database")
