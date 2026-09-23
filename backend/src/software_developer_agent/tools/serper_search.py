from dataclasses import dataclass

from software_developer_agent.config.settings import Settings
from software_developer_agent.tools.types import ToolResult
from software_developer_agent.tools.web_content import sanitize_untrusted_web_text


@dataclass(slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str


class SerperSearchTool:
    endpoint = "https://google.serper.dev/search"
    image_endpoint = "https://google.serper.dev/images"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def search(self, query: str) -> ToolResult:
        if not self._settings.enable_web_search:
            return ToolResult("serper_search", "skipped", query, "Web search is disabled.")
        if self._settings.serper_api_key is None:
            return ToolResult(
                "serper_search", "skipped", query, "SERPER_API_KEY is not configured."
            )

        try:
            import httpx
        except ImportError as exc:
            return ToolResult("serper_search", "failed", query, f"httpx is not installed: {exc}")

        try:
            response = httpx.post(
                self.endpoint,
                headers={
                    "X-API-KEY": self._settings.serper_api_key.get_secret_value(),
                    "Content-Type": "application/json",
                },
                json={"q": query, "num": self._settings.max_search_results},
                timeout=self._settings.tool_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return ToolResult("serper_search", "failed", query, f"Search request failed: {exc}")

        payload = response.json()
        hits = [
            SearchHit(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=sanitize_untrusted_web_text(item.get("snippet", ""), max_chars=600),
            )
            for item in payload.get("organic", [])[: self._settings.max_search_results]
        ]
        content = "\n".join(
            f"- {hit.title}\n  URL: {hit.url}\n  Snippet: {hit.snippet}" for hit in hits
        )
        return ToolResult(
            tool_name="serper_search",
            status="succeeded",
            input_summary=query,
            output_summary=f"{len(hits)} search result(s).",
            content=content,
            metadata={"result_count": len(hits), "urls": [hit.url for hit in hits]},
        )

    def search_images(self, query: str) -> ToolResult:
        if not self._settings.enable_web_search:
            return ToolResult("serper_image_search", "skipped", query, "Web search is disabled.")
        if self._settings.serper_api_key is None:
            return ToolResult(
                "serper_image_search",
                "skipped",
                query,
                "SERPER_API_KEY is not configured.",
            )
        try:
            import httpx
        except ImportError as exc:
            return ToolResult(
                "serper_image_search", "failed", query, f"httpx is not installed: {exc}"
            )
        try:
            response = httpx.post(
                self.image_endpoint,
                headers={
                    "X-API-KEY": self._settings.serper_api_key.get_secret_value(),
                    "Content-Type": "application/json",
                },
                json={"q": query, "num": self._settings.max_search_results},
                timeout=self._settings.tool_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return ToolResult(
                "serper_image_search",
                "failed",
                query,
                f"Image search request failed: {exc}",
            )

        payload = response.json()
        images = [
            {
                "title": sanitize_untrusted_web_text(str(item.get("title", "")), max_chars=180),
                "image_url": str(item.get("imageUrl", "")),
                "source_url": str(item.get("link", "")),
                "source": sanitize_untrusted_web_text(str(item.get("source", "")), max_chars=120),
            }
            for item in payload.get("images", [])[: self._settings.max_search_results]
            if item.get("imageUrl") and item.get("link")
        ]
        content = "\n".join(
            (
                f"- {item['title']}\n  Image URL: {item['image_url']}\n"
                f"  Source page: {item['source_url']}\n  Source: {item['source']}"
            )
            for item in images
        )
        return ToolResult(
            tool_name="serper_image_search",
            status="succeeded",
            input_summary=query,
            output_summary=f"{len(images)} image result(s).",
            content=content,
            metadata={
                "result_count": len(images),
                "urls": [item["source_url"] for item in images],
                "image_urls": [item["image_url"] for item in images],
                "licensing_note": "Verify usage rights from each source page before publication.",
            },
        )
