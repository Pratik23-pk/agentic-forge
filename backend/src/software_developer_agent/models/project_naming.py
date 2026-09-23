from __future__ import annotations

import re
import secrets

PLACEHOLDER_PROJECT_NAMES = (
    re.compile(r"^default$", re.IGNORECASE),
    re.compile(r"^build[-_ ]?[a-z0-9]+$", re.IGNORECASE),
    re.compile(r"^(?:new|generated)[-_ ]?project$", re.IGNORECASE),
)
PROJECT_WORDS_TO_SKIP = {
    "a",
    "an",
    "and",
    "app",
    "application",
    "build",
    "create",
    "for",
    "make",
    "me",
    "of",
    "please",
    "software",
    "that",
    "the",
    "this",
    "to",
    "using",
    "web",
    "website",
    "with",
}
FALLBACK_PREFIXES = (
    "Aurora Studio",
    "Cobalt Works",
    "Nova Project",
    "Orbit Foundry",
    "Pixel Workshop",
)


def resolve_project_name(requested_name: str | None, prompt: str) -> tuple[str, bool]:
    normalized = _normalize_requested_name(requested_name)
    if normalized and not any(
        pattern.fullmatch(normalized) for pattern in PLACEHOLDER_PROJECT_NAMES
    ):
        return normalized, False
    return generate_project_name(prompt), True


def generate_project_name(prompt: str) -> str:
    words = [
        word
        for word in re.findall(r"[A-Za-z][A-Za-z0-9']*", prompt)
        if word.lower() not in PROJECT_WORDS_TO_SKIP
    ]
    meaningful = list(dict.fromkeys(word.lower() for word in words))[:3]
    if meaningful:
        prefix = " ".join(_display_word(word) for word in meaningful)
    else:
        prefix = secrets.choice(FALLBACK_PREFIXES)
    return f"{prefix} {secrets.token_hex(3).upper()}"


def _normalize_requested_name(value: str | None) -> str:
    normalized = re.sub(r"\s+", " ", (value or "").strip())
    normalized = re.sub(r"[^A-Za-z0-9 ._'-]", "", normalized)
    return normalized[:80].strip(" ._-")


def _display_word(word: str) -> str:
    return word[:1].upper() + word[1:].lower()
