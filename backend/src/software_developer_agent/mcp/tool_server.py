from __future__ import annotations

from html import escape
from textwrap import dedent
from urllib.parse import quote

from software_developer_agent.config.settings import Settings
from software_developer_agent.mcp.server import SecureMCPServer
from software_developer_agent.mcp.types import MCPToolDefinition, MCPToolRequest, MCPToolResponse
from software_developer_agent.models.job_state import WorkerKind
from software_developer_agent.tools.browser import PlaywrightBrowserTool
from software_developer_agent.tools.policy import ToolPolicy
from software_developer_agent.tools.serper_search import SerperSearchTool
from software_developer_agent.tools.types import ToolResult

ALL_WORKERS = {WorkerKind.DATABASE, WorkerKind.BACKEND, WorkerKind.FRONTEND}


def build_development_mcp_server(settings: Settings) -> SecureMCPServer:
    server = SecureMCPServer(settings)
    policy = ToolPolicy.from_settings(settings)
    search_tool = SerperSearchTool(settings)
    browser_tool = PlaywrightBrowserTool(settings, policy)

    server.register(
        MCPToolDefinition(
            name="serper_search",
            description="Search the web through Serper when web access is enabled.",
            allowed_workers=ALL_WORKERS,
            requires_network=True,
        ),
        lambda request: _from_tool_result(search_tool.search(_string_input(request, "query"))),
    )
    server.register(
        MCPToolDefinition(
            name="playwright_browser",
            description="Inspect a browser page through Playwright when browser use is enabled.",
            allowed_workers={WorkerKind.BACKEND, WorkerKind.FRONTEND},
            requires_browser=True,
        ),
        lambda request: _from_tool_result(browser_tool.inspect(_string_input(request, "url"))),
    )
    server.register(
        MCPToolDefinition(
            name="serper_image_search",
            description="Find relevant images and their source pages through Serper.",
            allowed_workers={WorkerKind.FRONTEND},
            requires_network=True,
        ),
        lambda request: _from_tool_result(
            search_tool.search_images(_string_input(request, "query"))
        ),
    )
    server.register(
        MCPToolDefinition(
            name="database_schema_diagram",
            description="Create a visual schema checkpoint for database review.",
            allowed_workers={WorkerKind.DATABASE},
        ),
        _database_schema_diagram,
    )
    server.register(
        MCPToolDefinition(
            name="backend_architecture_diagram",
            description="Create a visual service architecture checkpoint for backend review.",
            allowed_workers={WorkerKind.BACKEND},
        ),
        _backend_architecture_diagram,
    )
    server.register(
        MCPToolDefinition(
            name="frontend_screen_preview",
            description="Create a visual screen checkpoint for frontend review.",
            allowed_workers={WorkerKind.FRONTEND},
        ),
        _frontend_screen_preview,
    )
    return server


def _from_tool_result(result: ToolResult) -> MCPToolResponse:
    return MCPToolResponse(
        tool_name=result.tool_name,
        status=result.status,
        input_summary=result.input_summary,
        output_summary=result.output_summary,
        content=result.content,
        metadata=result.metadata,
    )


def _database_schema_diagram(request: MCPToolRequest) -> MCPToolResponse:
    prompt = _string_input(request, "prompt")
    project_id = _string_input(request, "project_id") or "Generated Project"
    include_billing = _has_any(prompt, "stripe", "billing", "subscription")
    include_ai = _has_any(prompt, "ai", "rag", "embedding", "knowledge")
    entities = ["accounts", "app_users", "events"]
    if include_billing:
        entities.append("subscriptions")
    if include_ai:
        entities.extend(["documents", "embeddings"])

    source_lines = [
        "erDiagram",
        "  accounts ||--o{ app_users : owns",
        "  accounts ||--o{ events : records",
    ]
    if include_billing:
        source_lines.append("  accounts ||--o{ subscriptions : bills")
    if include_ai:
        source_lines.extend(
            [
                "  accounts ||--o{ documents : stores",
                "  documents ||--o{ embeddings : indexes",
            ]
        )

    svg = _schema_svg(project_id, entities, include_billing, include_ai)
    return MCPToolResponse(
        tool_name=request.tool_name,
        status="succeeded",
        input_summary=prompt[:500],
        output_summary="Database schema review diagram generated.",
        content="\n".join(source_lines),
        metadata={
            "visual_type": "svg_data_uri",
            "image_data_uri": _svg_data_uri(svg),
            "entities": entities,
        },
    )


def _backend_architecture_diagram(request: MCPToolRequest) -> MCPToolResponse:
    prompt = _string_input(request, "prompt")
    project_id = _string_input(request, "project_id") or "Generated Project"
    has_auth = _has_any(prompt, "auth", "role", "login", "permission")
    has_billing = _has_any(prompt, "stripe", "billing", "subscription")
    has_realtime = _has_any(prompt, "realtime", "websocket", "stream")

    nodes = ["Frontend", "FastAPI", "Domain Services", "PostgreSQL"]
    if has_auth:
        nodes.append("Auth Policy")
    if has_billing:
        nodes.append("Stripe Adapter")
    if has_realtime:
        nodes.append("Event Channel")

    source = dedent(
        """
        flowchart LR
          Frontend --> FastAPI
          FastAPI --> DomainServices
          DomainServices --> PostgreSQL
        """
    ).strip()
    svg = _backend_svg(project_id, nodes, has_auth, has_billing, has_realtime)
    return MCPToolResponse(
        tool_name=request.tool_name,
        status="succeeded",
        input_summary=prompt[:500],
        output_summary="Backend architecture review diagram generated.",
        content=source,
        metadata={
            "visual_type": "svg_data_uri",
            "image_data_uri": _svg_data_uri(svg),
            "components": nodes,
        },
    )


def _frontend_screen_preview(request: MCPToolRequest) -> MCPToolResponse:
    prompt = _string_input(request, "prompt")
    project_id = _string_input(request, "project_id") or "Generated Project"
    features = _feature_labels(prompt)
    svg = _frontend_svg(project_id, features)
    return MCPToolResponse(
        tool_name=request.tool_name,
        status="succeeded",
        input_summary=prompt[:500],
        output_summary="Frontend review screen preview generated.",
        content="Front-page preview with hero, navigation, metrics, and feature cards.",
        metadata={
            "visual_type": "svg_data_uri",
            "image_data_uri": _svg_data_uri(svg),
            "features": features,
        },
    )


def _string_input(request: MCPToolRequest, key: str) -> str:
    value = request.input.get(key, "")
    return str(value).strip()


def _has_any(text: str, *needles: str) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


def _feature_labels(prompt: str) -> list[str]:
    labels = ["Dashboard", "API health", "Data model"]
    if _has_any(prompt, "auth", "role"):
        labels.append("Roles")
    if _has_any(prompt, "stripe", "billing"):
        labels.append("Billing")
    if _has_any(prompt, "analytics", "chart"):
        labels.append("Analytics")
    if _has_any(prompt, "realtime", "websocket"):
        labels.append("Realtime")
    return labels[:6]


def _svg_data_uri(svg: str) -> str:
    return f"data:image/svg+xml;utf8,{quote(svg)}"


def _schema_svg(
    project_id: str,
    entities: list[str],
    include_billing: bool,
    include_ai: bool,
) -> str:
    boxes = [
        _box(44, 74, "accounts", "account_id, name, plan"),
        _box(284, 58, "app_users", "user_id, account_id, role"),
        _box(284, 196, "events", "event_id, account_id, props"),
    ]
    connectors = [
        _line(224, 112, 284, 96),
        _line(224, 134, 284, 234),
    ]
    if include_billing:
        boxes.append(_box(44, 260, "subscriptions", "provider, customer, status"))
        connectors.append(_line(132, 174, 132, 260))
    if include_ai:
        boxes.append(_box(524, 90, "documents", "source, title, content"))
        boxes.append(_box(524, 236, "embeddings", "vector, metadata"))
        connectors.extend([_line(464, 104, 524, 128), _line(612, 176, 612, 236)])

    return _svg_canvas(
        "Database Schema Checkpoint",
        project_id,
        "".join(connectors + boxes),
    )


def _backend_svg(
    project_id: str,
    nodes: list[str],
    has_auth: bool,
    has_billing: bool,
    has_realtime: bool,
) -> str:
    boxes = [
        _box(34, 138, "Frontend", "React/Vite client"),
        _box(244, 138, "FastAPI", "Routes and validation"),
        _box(454, 138, "Domain Services", "Business workflows"),
        _box(664, 138, "PostgreSQL", "Durable state"),
    ]
    connectors = [_line(194, 176, 244, 176), _line(404, 176, 454, 176), _line(614, 176, 664, 176)]
    if has_auth:
        boxes.append(_box(244, 46, "Auth Policy", "roles and scopes"))
        connectors.append(_line(324, 114, 324, 138))
    if has_billing:
        boxes.append(_box(454, 46, "Stripe Adapter", "billing events"))
        connectors.append(_line(534, 114, 534, 138))
    if has_realtime:
        boxes.append(_box(454, 250, "Event Channel", "live updates"))
        connectors.append(_line(534, 214, 534, 250))

    return _svg_canvas(
        "Backend Architecture Checkpoint",
        f"{project_id} - {len(nodes)} components",
        "".join(connectors + boxes),
    )


def _frontend_svg(project_id: str, features: list[str]) -> str:
    cards = []
    for index, feature in enumerate(features[:6]):
        column = index % 3
        row = index // 3
        cards.append(_box(52 + column * 230, 278 + row * 92, feature, "ready for review"))

    hero_title = escape(_truncate(project_id, 30))
    feature_count = escape(str(len(features)))
    body = f"""
    <rect x="36" y="64" width="728" height="60" rx="10" fill="#0e2238" stroke="#2d5f8f"/>
    <circle cx="68" cy="94" r="12" fill="#6ee7c6"/>
    <text x="92" y="100" fill="#dcefff" font-size="18" font-weight="700">{hero_title}</text>
    <rect x="590" y="82" width="136" height="26" rx="6" fill="#1d74b7"/>
    <text x="624" y="100" fill="#f3fbff" font-size="12" font-weight="700">Primary CTA</text>
    <rect x="52" y="158" width="380" height="86" rx="10" fill="#10263e" stroke="#2d5f8f"/>
    <text x="76" y="192" fill="#f2f8ff" font-size="26" font-weight="800">Product front page</text>
    <text x="76" y="222" fill="#8aa6bf" font-size="14">{feature_count} feature areas mapped</text>
    <rect x="476" y="158" width="250" height="86" rx="10" fill="#071421" stroke="#274c74"/>
    <path d="M502 214 C532 186 558 204 586 180 C624 148 656 190 700 166" fill="none" stroke="#6ee7c6" stroke-width="4"/>
    {"".join(cards)}
    """
    return _svg_canvas("Frontend Screen Checkpoint", "First-viewport preview", body)


def _svg_canvas(title: str, subtitle: str, body: str) -> str:
    return f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="820" height="480" viewBox="0 0 820 480">
      <rect width="820" height="480" rx="18" fill="#050910"/>
      <rect x="18" y="18" width="784" height="444" rx="16" fill="#081521" stroke="#234667"/>
      <text x="40" y="42" fill="#79bdff" font-size="13" font-weight="800">{escape(title)}</text>
      <text x="40" y="60" fill="#68839b" font-size="11">{escape(subtitle)}</text>
      {body}
    </svg>
    """


def _box(x_coord: int, y_coord: int, title: str, subtitle: str) -> str:
    return f"""
    <rect x="{x_coord}" y="{y_coord}" width="180" height="76" rx="10" fill="#10263e" stroke="#2d5f8f"/>
    <text x="{x_coord + 18}" y="{y_coord + 31}" fill="#e8f5ff" font-size="16" font-weight="800">{escape(title)}</text>
    <text x="{x_coord + 18}" y="{y_coord + 54}" fill="#8aa6bf" font-size="11">{escape(subtitle)}</text>
    """


def _line(start_x: int, start_y: int, end_x: int, end_y: int) -> str:
    return (
        f'<path d="M{start_x} {start_y} L{end_x} {end_y}" '
        'stroke="#5aa9e6" stroke-width="3" stroke-linecap="round"/>'
    )


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."
