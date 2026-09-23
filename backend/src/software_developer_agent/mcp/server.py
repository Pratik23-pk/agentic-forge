from __future__ import annotations

import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from software_developer_agent.config.settings import Settings
from software_developer_agent.mcp.types import (
    MCPToolDefinition,
    MCPToolHandler,
    MCPToolRequest,
    MCPToolResponse,
)
from software_developer_agent.models.job_state import WorkerKind
from software_developer_agent.observability.metrics import metrics

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+"),
)


@dataclass(slots=True)
class RegisteredTool:
    definition: MCPToolDefinition
    handler: MCPToolHandler


class SecureMCPServer:
    """In-process MCP server boundary with allowlisted tools and redacted output."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, definition: MCPToolDefinition, handler: MCPToolHandler) -> None:
        self._tools[definition.name] = RegisteredTool(definition=definition, handler=handler)

    def list_tools(self, worker_kind: WorkerKind | None = None) -> list[MCPToolDefinition]:
        definitions = [tool.definition for tool in self._tools.values()]
        if worker_kind is None:
            return definitions
        return [
            definition for definition in definitions if worker_kind in definition.allowed_workers
        ]

    def call(self, request: MCPToolRequest) -> MCPToolResponse:
        metrics.increment("mcp_tool_calls")
        if not self._settings.enable_mcp_tools:
            return self._skipped(request, "MCP tools are disabled.")

        registered = self._tools.get(request.tool_name)
        if registered is None:
            return self._failed(request, "Tool is not registered on the MCP server.")

        if request.worker_kind not in registered.definition.allowed_workers:
            return self._failed(request, "Worker is not allowed to call this MCP tool.")

        started_at = perf_counter()
        try:
            response = registered.handler(request)
        except Exception as exc:
            response = self._failed(request, f"Tool handler failed: {exc}")

        elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
        response.content = _redact_text(response.content)
        response.output_summary = _redact_text(response.output_summary)
        response.error = _redact_text(response.error) if response.error else None
        response.metadata = _redact_mapping({**response.metadata, "elapsed_ms": elapsed_ms})
        return response

    @staticmethod
    def _failed(request: MCPToolRequest, message: str) -> MCPToolResponse:
        return MCPToolResponse(
            tool_name=request.tool_name,
            status="failed",
            input_summary=_summarize_input(request.input),
            output_summary=message,
            error=message,
        )

    @staticmethod
    def _skipped(request: MCPToolRequest, message: str) -> MCPToolResponse:
        return MCPToolResponse(
            tool_name=request.tool_name,
            status="skipped",
            input_summary=_summarize_input(request.input),
            output_summary=message,
        )


def _summarize_input(payload: dict[str, Any]) -> str:
    if "query" in payload:
        return str(payload["query"])[:500]
    if "url" in payload:
        return str(payload["url"])[:500]
    if "prompt" in payload:
        return str(payload["prompt"])[:500]
    return str(payload)[:500]


def _redact_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: _redact_value(value) for key, value in payload.items()}


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return _redact_mapping(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted
