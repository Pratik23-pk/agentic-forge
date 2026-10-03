from dataclasses import dataclass

from software_developer_agent.config.settings import Settings
from software_developer_agent.mcp.client import MCPClient, create_mcp_client
from software_developer_agent.mcp.types import MCPToolResponse
from software_developer_agent.models.job_state import JobTask
from software_developer_agent.tools.browser import PlaywrightBrowserTool, extract_urls
from software_developer_agent.tools.media_assets import MediaAssetPipeline
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
)

VIDEO_RESEARCH_TRIGGERS = (
    "video",
    "videos",
    "gameplay",
    "trailer",
    "footage",
    "clip",
    "clips",
)

MEDIA_USAGE_TRIGGERS = (
    "add",
    "give",
    "include",
    "place",
    "provide",
    "put",
    "show",
    "display",
    "feature",
    "hero",
    "gallery",
    "background",
    "download",
    "embed",
    "search",
    "find",
    "use",
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
        self._legacy_media = MediaAssetPipeline(settings, self._policy, self._legacy_search)

    def collect_context(self, task: JobTask) -> ToolContext:
        text = task.instructions
        request_text = self._request_text(task)
        results: list[MCPToolResponse] = []
        discovered_urls: list[str] = []

        if task.worker_kind.value == "frontend":
            for kind in self._requested_media_kinds(request_text):
                media_result = self._call_mcp(
                    "media_asset_acquisition",
                    task,
                    {
                        "query": self._media_search_query(task, kind),
                        "kind": kind,
                        "task_id": task.task_id,
                        "instructions": task.instructions,
                    },
                )
                results.append(media_result)
                discovered_urls.extend(
                    url
                    for url in media_result.metadata.get("urls", [])
                    if isinstance(url, str) and url
                )

        if self._should_search(request_text):
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
        elif tool_name == "serper_video_search":
            result = self._legacy_search.search_videos(str(payload.get("query", "")))
        elif tool_name == "media_asset_acquisition":
            kind = str(payload.get("kind", ""))
            if kind not in {"image", "video"}:
                return MCPToolResponse(
                    tool_name=tool_name,
                    status="failed",
                    input_summary=str(payload)[:500],
                    output_summary="Media kind must be image or video.",
                )
            result = self._legacy_media.acquire(
                str(payload.get("query", "")),
                kind,
                str(payload.get("task_id", "")),
                str(payload.get("instructions", "")),
            )
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

    @classmethod
    def _requested_media_kinds(cls, text: str) -> list[str]:
        lowered = text.lower()
        has_usage_request = any(trigger in lowered for trigger in MEDIA_USAGE_TRIGGERS)
        kinds: list[str] = []
        if cls._should_search_images(text) and has_usage_request:
            kinds.append("image")
        if any(trigger in lowered for trigger in VIDEO_RESEARCH_TRIGGERS) and has_usage_request:
            kinds.append("video")
        return kinds

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

    @staticmethod
    def _request_text(task: JobTask) -> str:
        return next(
            (
                line.removeprefix("Request:").strip()
                for line in task.instructions.splitlines()
                if line.startswith("Request:")
            ),
            task.title,
        )

    @staticmethod
    def _media_search_query(task: JobTask, kind: str) -> str:
        request = next(
            (
                line.removeprefix("Request:").strip()
                for line in task.instructions.splitlines()
                if line.startswith("Request:")
            ),
            task.title,
        )
        suffix = (
            "high quality editorial photography"
            if kind == "image"
            else "official embeddable video"
        )
        return f"{request[:420]} {suffix}"


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
