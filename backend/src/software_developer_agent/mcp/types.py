from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from software_developer_agent.models.job_state import WorkerKind

MCPToolStatus = Literal["succeeded", "failed", "skipped"]


@dataclass(slots=True)
class MCPToolDefinition:
    name: str
    description: str
    allowed_workers: set[WorkerKind]
    requires_network: bool = False
    requires_browser: bool = False


@dataclass(slots=True)
class MCPToolRequest:
    tool_name: str
    worker_kind: WorkerKind
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MCPToolResponse:
    tool_name: str
    status: MCPToolStatus
    input_summary: str
    output_summary: str = ""
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "tool": self.tool_name,
            "status": self.status,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "metadata": self.metadata,
            "error": self.error,
            "protocol": "mcp",
        }


MCPToolHandler = Callable[[MCPToolRequest], MCPToolResponse]
