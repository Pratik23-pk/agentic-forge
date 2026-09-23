from __future__ import annotations

from typing import Any

from software_developer_agent.config.settings import Settings
from software_developer_agent.mcp.server import SecureMCPServer
from software_developer_agent.mcp.tool_server import build_development_mcp_server
from software_developer_agent.mcp.types import MCPToolDefinition, MCPToolRequest, MCPToolResponse
from software_developer_agent.models.job_state import WorkerKind


class MCPClient:
    """MCP client adapter used by agents instead of direct tool imports."""

    def __init__(self, server: SecureMCPServer) -> None:
        self._server = server

    def list_tools(self, worker_kind: WorkerKind | None = None) -> list[MCPToolDefinition]:
        return self._server.list_tools(worker_kind)

    def call_tool(
        self,
        tool_name: str,
        worker_kind: WorkerKind,
        payload: dict[str, Any],
    ) -> MCPToolResponse:
        return self._server.call(
            MCPToolRequest(
                tool_name=tool_name,
                worker_kind=worker_kind,
                input=payload,
            )
        )


def create_mcp_client(settings: Settings) -> MCPClient:
    return MCPClient(build_development_mcp_server(settings))
