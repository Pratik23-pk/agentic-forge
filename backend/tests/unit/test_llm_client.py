import sys
from types import SimpleNamespace

from software_developer_agent.config.settings import Settings
from software_developer_agent.integrations.llm_client import OpenAIResponsesClient


def test_responses_client_applies_strict_json_schema(monkeypatch) -> None:
    captured = {}
    client_options = {}

    class Responses:
        @staticmethod
        def create(**request):
            captured.update(request)
            return SimpleNamespace(status="completed", output_text='{"files": []}', usage=None)

    fake_client = SimpleNamespace(responses=Responses())
    monkeypatch.setitem(
        sys.modules,
        "openai",
        SimpleNamespace(OpenAI=lambda **options: client_options.update(options) or fake_client),
    )
    schema = {
        "type": "object",
        "properties": {"files": {"type": "array", "items": {"type": "string"}}},
        "required": ["files"],
        "additionalProperties": False,
    }
    client = OpenAIResponsesClient(
        Settings(
            _env_file=None,
            openai_api_key="test-key",
            langsmith_tracing=False,
        ),
        model="gpt-5.6-terra",
        node_name="worker.frontend",
        response_schema=schema,
    )

    response = client.complete("system", "user")

    assert response.text == '{"files": []}'
    assert captured["text"] == {
        "format": {
            "type": "json_schema",
            "name": "worker_frontend_response",
            "schema": schema,
            "strict": True,
        },
        "verbosity": "low",
    }
    assert client_options["max_retries"] == 0
