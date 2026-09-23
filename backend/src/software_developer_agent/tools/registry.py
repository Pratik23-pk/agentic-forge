from dataclasses import dataclass

from software_developer_agent.config.settings import Settings
from software_developer_agent.mcp.client import MCPClient, create_mcp_client
from software_developer_agent.mcp.types import MCPToolResponse
from software_developer_agent.models.job_state import JobTask
from software_developer_agent.tools.browser import PlaywrightBrowserTool, extract_urls
from software_developer_agent.tools.policy import ToolPolicy
from software_developer_agent.tools.serper_search import SerperSearchTool

RESEARCH_TRIGGERS = (
    "search",
    "internet",
    "web",
    "browser",
    "latest",
    "current",
    "docs",
    "documentation",
    "verify online",
)

IMAGE_RESEARCH_TRIGGERS = (
    "image",
    "images",
    "photo",
    "photos",
    "gallery",
    "visual reference",
    "media",
)


@dataclass(slots=True)
class ToolContext:
    content: str
    calls: list[dict]


class ToolRegistry:
    def __init__(self, settings: Settings, mcp_client: MCPClient | None = None) -> None:
        self._settings = settings
        self._policy = ToolPolicy.from_settings(settings)
        self._mcp_client = mcp_client or create_mcp_client(settings)
        self._legacy_search = SerperSearchTool(settings)
        self._legacy_browser = PlaywrightBrowserTool(settings, self._policy)

    def collect_context(self, task: JobTask) -> ToolContext:
        text = task.instructions
        results: list[MCPToolResponse] = []
        discovered_urls: list[str] = []

        if task.worker_kind.value == "frontend" and self._should_search_images(text):
            image_result = self._call_mcp(
                "serper_image_search",
                task,
                {"query": self._search_query(task)},
            )
            results.append(image_result)
            discovered_urls.extend(
                url for url in image_result.metadata.get("urls", []) if isinstance(url, str) and url
            )

        if self._should_search(text):
            search_result = self._call_mcp(
                "serper_search",
                task,
                {"query": self._search_query(task)},
            )
            results.append(search_result)
            discovered_urls.extend(
                url
                for url in search_result.metadata.get("urls", [])
                if isinstance(url, str) and url
            )

        urls = _dedupe_urls([*extract_urls(text), *discovered_urls])[
            : self._policy.max_browser_pages
        ]
        if urls or "browser" in text.lower():
            for url in urls:
                results.append(self._call_mcp("playwright_browser", task, {"url": url}))
            if not urls and self._settings.enable_browser:
                results.append(_skipped_mcp_response("playwright_browser", "no-url"))

        content = "\n\n".join(result.content for result in results if result.content)
        calls = [result.to_record() for result in results]
        return ToolContext(content=content, calls=calls)

    def call_visual_tool(self, task: JobTask, tool_name: str, payload: dict) -> MCPToolResponse:
        return self._call_mcp(tool_name, task, payload)

    def _call_mcp(
        self,
        tool_name: str,
        task: JobTask,
        payload: dict,
    ) -> MCPToolResponse:
        if self._settings.enable_mcp_tools:
            return self._mcp_client.call_tool(tool_name, task.worker_kind, payload)
        return self._call_legacy_tool(tool_name, payload)

    def _call_legacy_tool(self, tool_name: str, payload: dict) -> MCPToolResponse:
        if tool_name == "serper_search":
            result = self._legacy_search.search(str(payload.get("query", "")))
        elif tool_name == "serper_image_search":
            result = self._legacy_search.search_images(str(payload.get("query", "")))
        elif tool_name == "playwright_browser":
            result = self._legacy_browser.inspect(str(payload.get("url", "")))
        else:
            return MCPToolResponse(
                tool_name=tool_name,
                status="skipped",
                input_summary=str(payload)[:500],
                output_summary="Legacy tool fallback does not expose this capability.",
            )
        return MCPToolResponse(
            tool_name=result.tool_name,
            status=result.status,
            input_summary=result.input_summary,
            output_summary=result.output_summary,
            content=result.content,
            metadata=result.metadata,
        )

    @staticmethod
    def _should_search(text: str) -> bool:
        lowered = text.lower()
        return any(trigger in lowered for trigger in RESEARCH_TRIGGERS)

    @staticmethod
    def _should_search_images(text: str) -> bool:
        lowered = text.lower()
        return any(trigger in lowered for trigger in IMAGE_RESEARCH_TRIGGERS)

    @staticmethod
    def _search_query(task: JobTask) -> str:
        request = next(
            (
                line.removeprefix("Request:").strip()
                for line in task.instructions.splitlines()
                if line.startswith("Request:")
            ),
            task.title,
        )
        return f"{request[:420]} high quality editorial photography"


def _dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        unique.append(url)
    return unique


def _skipped_mcp_response(tool_name: str, input_summary: str) -> MCPToolResponse:
    return MCPToolResponse(
        tool_name=tool_name,
        status="skipped",
        input_summary=input_summary,
        output_summary="Browser requested, but no URL was present.",
    )
