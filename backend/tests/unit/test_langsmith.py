import os

from software_developer_agent.config.settings import Settings
from software_developer_agent.observability import langsmith


def test_configure_langsmith_environment_sets_workspace_and_aliases(monkeypatch) -> None:
    monkeypatch.delenv("LANGSMITH_WORKSPACE_ID", raising=False)
    settings = Settings(
        app_env="test",
        langsmith_tracing=True,
        langsmith_api_key="lsv2_pt_fake",
        langsmith_project="agentic-forge-test",
        langsmith_endpoint="https://api.smith.langchain.com",
        langsmith_workspace_id="workspace-123",
    )

    langsmith.configure_langsmith_environment(settings)

    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    assert os.environ["LANGSMITH_PROJECT"] == "agentic-forge-test"
    assert os.environ["LANGCHAIN_PROJECT"] == "agentic-forge-test"
    assert os.environ["LANGSMITH_WORKSPACE_ID"] == "workspace-123"


def test_langsmith_validation_reports_missing_key() -> None:
    settings = Settings(app_env="test", langsmith_tracing=True, langsmith_api_key=None)

    status = langsmith.validate_langsmith_configuration(settings)

    assert status.enabled
    assert not status.ready
    assert "LANGSMITH_API_KEY" in status.message


def test_langsmith_validation_explains_forbidden_workspace_issue(monkeypatch) -> None:
    class ForbiddenClient:
        def has_project(self, project_name: str) -> bool:
            raise RuntimeError("403 Forbidden")

    monkeypatch.setattr(langsmith, "get_langsmith_client", lambda settings: ForbiddenClient())
    settings = Settings(
        app_env="test",
        langsmith_tracing=True,
        langsmith_api_key="lsv2_pt_fake",
    )

    status = langsmith.validate_langsmith_configuration(settings)

    assert status.enabled
    assert not status.ready
    assert "LANGSMITH_WORKSPACE_ID" in status.message


def test_disable_runtime_tracing_preserves_configuration_but_stops_auto_tracing() -> None:
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGSMITH_API_KEY"] = "configured-key"

    langsmith.disable_langsmith_runtime_tracing()

    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
    assert os.environ["LANGSMITH_API_KEY"] == "configured-key"
