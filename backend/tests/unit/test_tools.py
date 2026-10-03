from software_developer_agent.config.settings import Settings
from software_developer_agent.mcp.client import create_mcp_client
from software_developer_agent.models.job_state import JobTask, WorkerKind
from software_developer_agent.tools.registry import ToolRegistry


def test_media_intent_requires_usage_language() -> None:
    assert ToolRegistry._requested_media_kinds("Build a video upload platform") == []
    assert ToolRegistry._requested_media_kinds("Give me an image of the Xpulse 200") == ["image"]
    assert ToolRegistry._requested_media_kinds("Add an image gallery and embed a video") == [
        "image",
        "video",
    ]


def test_tool_registry_records_skipped_search_when_disabled() -> None:
    registry = ToolRegistry(Settings(app_env="test", enable_web_search=False))
    task = JobTask(
        worker_kind=WorkerKind.BACKEND,
        title="Research docs",
        instructions="Search the web for current API docs.",
    )

    context = registry.collect_context(task)

    assert context.content == ""
    assert context.calls[0]["tool"] == "serper_search"
    assert context.calls[0]["status"] == "skipped"


def test_mcp_server_denies_tool_for_unapproved_worker() -> None:
    client = create_mcp_client(Settings(app_env="test"))

    response = client.call_tool(
        "database_schema_diagram",
        WorkerKind.FRONTEND,
        {"prompt": "Build dashboard"},
    )

    assert response.status == "failed"
    assert "not allowed" in response.output_summary
