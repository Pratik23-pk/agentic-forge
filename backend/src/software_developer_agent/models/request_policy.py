from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

CAPABILITY_TERMS: dict[str, tuple[str, ...]] = {
    "analytics": ("analytics", "telemetry", "tracking"),
    "authentication": ("authentication", "auth", "login", "sign in", "signup", "session"),
    "ci": ("ci/cd", "continuous integration", "github actions", "pipeline"),
    "cloud": ("cloud", "aws", "azure", "gcp", "supabase", "firebase"),
    "database": (
        "database",
        "db",
        "postgres",
        "postgresql",
        "mysql",
        "sqlite",
        "sql",
        "supabase",
    ),
    "backend": ("backend",),
    "deployment": ("deployment", "deploy", "hosting", "hosted"),
    "docker": ("docker", "container", "docker compose", "docker-compose"),
    "external_apis": ("external api", "external APIs", "third-party api", "remote api"),
    "frontend": ("frontend", "interface", "ui", "website"),
    "github": ("github", "repository", "repo"),
    "payments": ("payment", "payments", "billing", "stripe"),
    "persistence": (
        "persistence",
        "persistent storage",
        "durable storage",
        "store data",
        "saved data",
    ),
}

_NEGATIVE_LEAD = re.compile(
    r"\b(?:no|without|excluding|exclude|avoid|do not|don't|does not need|"
    r"is not required|are not required)\b",
    re.IGNORECASE,
)
_CONTRAST = re.compile(r"\b(?:but|however|instead|except)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RequestPolicy:
    requested_capabilities: frozenset[str]
    excluded_capabilities: frozenset[str]

    def requests(self, capability: str) -> bool:
        return capability in self.requested_capabilities

    def excludes(self, capability: str) -> bool:
        return capability in self.excluded_capabilities

    def allows(self, capability: str) -> bool:
        return self.requests(capability) and not self.excludes(capability)

    @property
    def requires_configuration(self) -> bool:
        return bool(
            self.requested_capabilities
            & {
                "authentication",
                "cloud",
                "database",
                "deployment",
                "external_apis",
                "payments",
                "persistence",
            }
        )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "requested_capabilities": sorted(self.requested_capabilities),
            "excluded_capabilities": sorted(self.excluded_capabilities),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RequestPolicy:
        return cls(
            requested_capabilities=frozenset(
                str(item) for item in payload.get("requested_capabilities", [])
            ),
            excluded_capabilities=frozenset(
                str(item) for item in payload.get("excluded_capabilities", [])
            ),
        )

    def forbidden_path_reason(self, path: str) -> str | None:
        normalized = PurePosixPath(path.replace("\\", "/")).as_posix().lower()
        parts = PurePosixPath(normalized).parts

        if not self.allows("docker") and (
            "dockerfile" in parts
            or normalized.endswith("dockerfile")
            or "docker-compose" in normalized
            or "compose.yaml" in normalized
            or "compose.yml" in normalized
        ):
            return "Docker was not positively requested."
        if not (self.allows("github") or self.allows("ci")) and normalized.startswith(".github/"):
            return "GitHub files were not positively requested."
        if not self.allows("deployment") and (
            normalized.startswith(".netlify/")
            or normalized.endswith(
                (
                    "fly.toml",
                    "netlify.toml",
                    "render.yaml",
                    "render.yml",
                )
            )
        ):
            return "Deployment configuration was not positively requested."
        if not (self.allows("database") or self.allows("persistence")) and (
            normalized.startswith("database/")
            or "/migrations/" in f"/{normalized}"
            or normalized.endswith((".db", ".sqlite", ".sqlite3", ".sql"))
        ):
            return "Database files were not positively requested."
        if not self.allows("authentication") and any(
            marker in parts for marker in ("auth", "authentication", "sessions")
        ):
            return "Authentication was not positively requested."
        return None

    def forbidden_content_reasons(self, path: str, content: str) -> list[str]:
        normalized = path.lower()
        if not _is_configuration_file(normalized):
            return []

        lowered = content.lower()
        reasons: list[str] = []
        if not (self.allows("database") or self.allows("persistence")) and any(
            marker in lowered
            for marker in (
                "database_url",
                "postgresql://",
                "postgres://",
                "sqlite://",
                "sqlite3",
                "supabase_url",
            )
        ):
            reasons.append("Database configuration was not positively requested.")
        if not (self.allows("github") or self.allows("ci")) and any(
            marker in lowered
            for marker in ("github_token", "github_repository", "actions/checkout")
        ):
            reasons.append("GitHub configuration was not positively requested.")
        if not self.allows("docker") and any(
            marker in lowered for marker in ("docker compose", "docker-compose", "from python:")
        ):
            reasons.append("Docker configuration was not positively requested.")
        if not self.allows("cloud") and any(
            marker in lowered
            for marker in ("aws_access_key", "azure_", "gcp_", "firebase_", "supabase_")
        ):
            reasons.append("Cloud configuration was not positively requested.")
        return reasons


def derive_request_policy(prompt: str) -> RequestPolicy:
    normalized = _normalize(prompt)
    negative_spans = _negative_spans(normalized)
    positive_text = normalized
    for span in negative_spans:
        positive_text = positive_text.replace(span, " ")

    excluded = {
        capability
        for capability, terms in CAPABILITY_TERMS.items()
        if any(_contains_term(span, term) for span in negative_spans for term in terms)
        or any(_negative_suffix(normalized, term) for term in terms)
    }
    if re.search(r"\b(?:in-memory|in memory)\s+only\b", normalized):
        excluded.update({"database", "persistence"})
    if "database" in excluded or "persistence" in excluded:
        excluded.update({"database", "persistence"})

    requested = {
        capability
        for capability, terms in CAPABILITY_TERMS.items()
        if any(_contains_term(positive_text, term) for term in terms)
    }
    if "database" in requested:
        requested.add("persistence")
    requested.difference_update(excluded)

    return RequestPolicy(
        requested_capabilities=frozenset(requested),
        excluded_capabilities=frozenset(excluded),
    )


def _negative_spans(prompt: str) -> list[str]:
    spans: list[str] = []
    for clause in re.split(r"[.;\n]+", prompt):
        for match in _NEGATIVE_LEAD.finditer(clause):
            tail = clause[match.start() :]
            contrast = _CONTRAST.search(tail)
            if contrast is not None:
                tail = tail[: contrast.start()]
            spans.append(tail.strip())
    return spans


def _negative_suffix(prompt: str, term: str) -> bool:
    escaped = _term_pattern(term)
    return (
        re.search(
            rf"{escaped}\s+(?:is\s+|are\s+)?not\s+(?:required|needed|wanted|necessary)\b",
            prompt,
            re.IGNORECASE,
        )
        is not None
    )


def _contains_term(text: str, term: str) -> bool:
    return re.search(_term_pattern(term), text, re.IGNORECASE) is not None


def _term_pattern(term: str) -> str:
    escaped = re.escape(term.lower()).replace(r"\ ", r"\s+")
    return rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"


def _normalize(text: str) -> str:
    return text.replace("’", "'").replace("“", '"').replace("”", '"').lower()


def _is_configuration_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return (
        name.startswith(".env")
        or name
        in {
            "dockerfile",
            "package.json",
            "pyproject.toml",
            "requirements.txt",
            "requirements-dev.txt",
        }
        or path.endswith((".toml", ".yaml", ".yml"))
        or "/config" in f"/{path}"
    )
