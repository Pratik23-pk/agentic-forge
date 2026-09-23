import logging
import re
from collections.abc import Iterable

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s]+"),
)


class SecretRedactionFilter(logging.Filter):
    """Redacts common secret shapes from log messages."""

    redaction = "[REDACTED]"

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(str(record.msg))
        if record.args:
            record.args = tuple(redact_secrets(str(arg)) for arg in record.args)
        return True


def redact_secrets(value: str, patterns: Iterable[re.Pattern[str]] = SECRET_PATTERNS) -> str:
    redacted = value
    for pattern in patterns:
        redacted = pattern.sub(SecretRedactionFilter.redaction, redacted)
    return redacted


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    root_logger = logging.getLogger()
    if not any(isinstance(filter_, SecretRedactionFilter) for filter_ in root_logger.filters):
        root_logger.addFilter(SecretRedactionFilter())
