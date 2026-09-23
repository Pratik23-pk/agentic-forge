from dataclasses import dataclass, field
from urllib.parse import urlparse

from software_developer_agent.config.settings import Settings


@dataclass(slots=True)
class ToolPolicy:
    allow_web_search: bool = False
    allow_browser: bool = False
    allowed_domains: set[str] = field(default_factory=set)
    blocked_domains: set[str] = field(default_factory=set)
    max_search_results: int = 5
    max_browser_pages: int = 3

    @classmethod
    def from_settings(cls, settings: Settings) -> "ToolPolicy":
        return cls(
            allow_web_search=settings.enable_web_search,
            allow_browser=settings.enable_browser,
            max_search_results=settings.max_search_results,
            max_browser_pages=settings.max_browser_pages,
        )

    def is_url_allowed(self, url: str) -> bool:
        domain = urlparse(url).netloc.lower()
        if not domain:
            return False
        if any(
            domain == blocked or domain.endswith(f".{blocked}") for blocked in self.blocked_domains
        ):
            return False
        if not self.allowed_domains:
            return True
        return any(
            domain == allowed or domain.endswith(f".{allowed}") for allowed in self.allowed_domains
        )
