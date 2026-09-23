import re

UNTRUSTED_INSTRUCTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)ignore (all )?(previous|prior) instructions"),
    re.compile(r"(?i)reveal .*?(secret|token|api key|system prompt)"),
    re.compile(r"(?i)you are now .*?(system|developer|admin)"),
)


def sanitize_untrusted_web_text(text: str, max_chars: int = 4_000) -> str:
    sanitized = text[:max_chars]
    for pattern in UNTRUSTED_INSTRUCTION_PATTERNS:
        sanitized = pattern.sub("[removed untrusted instruction]", sanitized)
    return sanitized
