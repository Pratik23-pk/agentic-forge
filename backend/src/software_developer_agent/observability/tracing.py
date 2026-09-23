import logging
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter

from software_developer_agent.config.settings import Settings, get_settings
from software_developer_agent.observability.langsmith import (
    get_langsmith_client,
    get_langsmith_status,
)

logger = logging.getLogger(__name__)


@contextmanager
def trace_span(name: str, settings: Settings | None = None, **attributes: object) -> Iterator[None]:
    started_at = perf_counter()
    logger.debug("span.start name=%s attributes=%s", name, attributes)
    langsmith_trace = _langsmith_trace_context(name, attributes, settings)
    try:
        with langsmith_trace:
            yield
    except Exception:
        logger.exception("span.error name=%s attributes=%s", name, attributes)
        raise
    finally:
        elapsed_ms = (perf_counter() - started_at) * 1000
        logger.debug("span.end name=%s elapsed_ms=%.2f", name, elapsed_ms)


@contextmanager
def _langsmith_trace_context(
    name: str,
    attributes: dict[str, object],
    settings: Settings | None,
) -> Iterator[None]:
    active_settings = settings or get_settings()
    if active_settings.app_env == "test":
        yield
        return
    status = get_langsmith_status(active_settings)
    if not status.ready:
        yield
        return

    try:
        from langsmith.run_helpers import trace

        client = get_langsmith_client(active_settings)
        with trace(
            name,
            run_type="chain",
            inputs=attributes,
            project_name=active_settings.langsmith_project,
            client=client,
            metadata=attributes,
        ):
            yield
    except Exception:
        logger.exception("langsmith.span_fallback name=%s", name)
        yield
