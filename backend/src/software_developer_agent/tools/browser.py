import re

from software_developer_agent.config.settings import Settings
from software_developer_agent.tools.policy import ToolPolicy
from software_developer_agent.tools.types import ToolResult
from software_developer_agent.tools.web_content import sanitize_untrusted_web_text

URL_PATTERN = re.compile(r"https?://[^\s)>\]\"']+")


def extract_urls(text: str) -> list[str]:
    return URL_PATTERN.findall(text)


class PlaywrightBrowserTool:
    def __init__(self, settings: Settings, policy: ToolPolicy) -> None:
        self._settings = settings
        self._policy = policy

    def inspect(self, url: str) -> ToolResult:
        if not self._settings.enable_browser or not self._policy.allow_browser:
            return ToolResult("playwright_browser", "skipped", url, "Browser use is disabled.")
        if not self._policy.is_url_allowed(url):
            return ToolResult(
                "playwright_browser", "skipped", url, "URL is blocked by tool policy."
            )

        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            return ToolResult(
                "playwright_browser", "failed", url, f"Playwright is not installed: {exc}"
            )

        try:
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.launch(channel="chrome", headless=True)
                except PlaywrightError:
                    browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self._settings.tool_timeout_seconds * 1000,
                )
                title = page.title()
                text = sanitize_untrusted_web_text(page.locator("body").inner_text(timeout=5_000))
                browser.close()
        except PlaywrightError as exc:
            return ToolResult(
                "playwright_browser", "failed", url, f"Browser inspection failed: {exc}"
            )

        content = f"Title: {title}\nURL: {url}\nText:\n{text}"
        return ToolResult(
            tool_name="playwright_browser",
            status="succeeded",
            input_summary=url,
            output_summary=f"Inspected page: {title}",
            content=content,
            metadata={"url": url, "title": title},
        )
