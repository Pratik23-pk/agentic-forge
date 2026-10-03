from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from software_developer_agent.config.settings import Settings
from software_developer_agent.observability.cost_tracker import TokenUsage
from software_developer_agent.observability.langsmith import (
    configure_langsmith_environment,
    disable_langsmith_runtime_tracing,
    get_langsmith_status,
)


@dataclass(slots=True)
class LLMResponse:
    text: str
    usage: TokenUsage = field(default_factory=TokenUsage)


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> LLMResponse: ...


class DisabledLLMClient:
    def complete(self, system: str, user: str) -> LLMResponse:
        raise RuntimeError("LLM calls are disabled. Set ENABLE_LLM_CALLS=true to enable them.")


class OpenAIResponsesClient:
    def __init__(
        self,
        settings: Settings,
        model: str | None = None,
        *,
        node_name: str = "llm",
        reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] | None = None,
        max_output_tokens: int = 4_000,
        response_schema: dict[str, Any] | None = None,
        budget_authorizer: Callable[[str, str, int, int], int] | None = None,
        usage_recorder: Callable[[str, str, TokenUsage], None] | None = None,
    ) -> None:
        if settings.openai_api_key is None:
            raise RuntimeError("OPENAI_API_KEY is required when LLM calls are enabled.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install the openai package to enable LLM calls.") from exc

        configure_langsmith_environment(settings)
        client = OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            max_retries=settings.openai_transport_retries,
            timeout=settings.request_timeout_seconds,
        )
        if get_langsmith_status(settings).ready:
            try:
                from langsmith.wrappers import wrap_openai

                client = wrap_openai(client)
            except ImportError:
                pass
        else:
            disable_langsmith_runtime_tracing()

        self._client = client
        self._model = model or settings.openai_model
        self._node_name = node_name
        self._reasoning_effort = reasoning_effort
        self._max_output_tokens = max_output_tokens
        self._response_schema = response_schema
        self._budget_authorizer = budget_authorizer
        self._usage_recorder = usage_recorder

    def complete(self, system: str, user: str) -> LLMResponse:
        estimated_prompt_tokens = max((len(system) + len(user) + 3) // 4, 1)
        max_output_tokens = self._max_output_tokens
        if self._budget_authorizer is not None:
            max_output_tokens = self._budget_authorizer(
                self._node_name,
                self._model,
                estimated_prompt_tokens,
                max_output_tokens,
            )
        request = {
            "model": self._model,
            "instructions": system,
            "input": user,
            "max_output_tokens": max_output_tokens,
        }
        if self._reasoning_effort is not None:
            request["reasoning"] = {"effort": self._reasoning_effort}
        text_config: dict[str, Any] = {}
        if self._response_schema is not None:
            text_config["format"] = {
                "type": "json_schema",
                "name": f"{self._node_name.replace('.', '_')}_response",
                "schema": self._response_schema,
                "strict": True,
            }
        if self._model.startswith(("gpt-5.6", "gpt-6")):
            text_config["verbosity"] = "low"
        if text_config:
            request["text"] = text_config
        response = self._client.responses.create(
            **request,
        )
        usage = getattr(response, "usage", None)
        input_details = getattr(usage, "input_tokens_details", None) if usage else None
        output_details = getattr(usage, "output_tokens_details", None) if usage else None
        token_usage = TokenUsage(
            prompt_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            completion_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            cached_prompt_tokens=(
                getattr(input_details, "cached_tokens", 0) if input_details else 0
            ),
            reasoning_tokens=(
                getattr(output_details, "reasoning_tokens", 0) if output_details else 0
            ),
        )
        if self._usage_recorder is not None:
            self._usage_recorder(self._node_name, self._model, token_usage)
        response_status = getattr(response, "status", "completed")
        if response_status != "completed":
            incomplete_details = getattr(response, "incomplete_details", None)
            reason = getattr(incomplete_details, "reason", response_status)
            raise RuntimeError(f"OpenAI response did not complete: {reason}.")
        return LLMResponse(text=response.output_text, usage=token_usage)


def create_llm_client(
    settings: Settings,
    model: str | None = None,
    *,
    node_name: str = "llm",
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] | None = None,
    max_output_tokens: int = 4_000,
    response_schema: dict[str, Any] | None = None,
    budget_authorizer: Callable[[str, str, int, int], int] | None = None,
    usage_recorder: Callable[[str, str, TokenUsage], None] | None = None,
) -> LLMClient:
    if not settings.enable_llm_calls:
        return DisabledLLMClient()
    return OpenAIResponsesClient(
        settings,
        model=model,
        node_name=node_name,
        reasoning_effort=reasoning_effort,
        max_output_tokens=max_output_tokens,
        response_schema=response_schema,
        budget_authorizer=budget_authorizer,
        usage_recorder=usage_recorder,
    )
