from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from software_developer_agent.config.settings import Settings

logger = logging.getLogger(__name__)

_langsmith_client = None
_langsmith_client_key: tuple[object, ...] | None = None
_langsmith_status: LangSmithStatus | None = None
_langsmith_status_key: tuple[object, ...] | None = None


@dataclass(slots=True)
class LangSmithStatus:
    enabled: bool
    ready: bool
    project: str
    endpoint: str
    workspace_id_configured: bool
    api_key_configured: bool
    message: str

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "enabled": self.enabled,
            "ready": self.ready,
            "project": self.project,
            "endpoint": self.endpoint,
            "workspace_id_configured": self.workspace_id_configured,
            "api_key_configured": self.api_key_configured,
            "message": self.message,
        }


def configure_langsmith_environment(settings: Settings) -> None:
    if not settings.langsmith_tracing:
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        _clear_langsmith_env_cache()
        return
    endpoint = settings.langsmith_endpoint or "https://api.smith.langchain.com"
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    os.environ["LANGSMITH_ENDPOINT"] = endpoint
    if settings.langsmith_api_key is not None:
        api_key = settings.langsmith_api_key.get_secret_value()
        os.environ["LANGSMITH_API_KEY"] = api_key
        os.environ["LANGCHAIN_API_KEY"] = api_key
    if settings.langsmith_workspace_id:
        os.environ["LANGSMITH_WORKSPACE_ID"] = settings.langsmith_workspace_id
    _clear_langsmith_env_cache()


def disable_langsmith_runtime_tracing() -> None:
    """Prevent SDK auto-tracing when configured credentials fail readiness checks."""

    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    _clear_langsmith_env_cache()


def get_langsmith_status(settings: Settings) -> LangSmithStatus:
    global _langsmith_status, _langsmith_status_key
    key = _settings_key(settings)
    if _langsmith_status is None or _langsmith_status_key != key:
        _langsmith_status = validate_langsmith_configuration(settings)
        _langsmith_status_key = key
    return _langsmith_status


def get_langsmith_client(settings: Settings):
    global _langsmith_client, _langsmith_client_key
    key = _settings_key(settings)
    if _langsmith_client is None or _langsmith_client_key != key:
        configure_langsmith_environment(settings)
        try:
            from langsmith import Client
        except ImportError as exc:
            raise RuntimeError("Install langsmith to enable tracing.") from exc

        _langsmith_client = Client(
            api_url=settings.langsmith_endpoint or None,
            api_key=(
                settings.langsmith_api_key.get_secret_value()
                if settings.langsmith_api_key is not None
                else None
            ),
            workspace_id=settings.langsmith_workspace_id,
            tracing_error_callback=_log_tracing_error,
        )
        _langsmith_client_key = key
    return _langsmith_client


def validate_langsmith_configuration(settings: Settings) -> LangSmithStatus:
    configure_langsmith_environment(settings)
    endpoint = settings.langsmith_endpoint or "https://api.smith.langchain.com"
    if not settings.langsmith_tracing:
        return LangSmithStatus(
            enabled=False,
            ready=False,
            project=settings.langsmith_project,
            endpoint=endpoint,
            workspace_id_configured=bool(settings.langsmith_workspace_id),
            api_key_configured=bool(settings.langsmith_api_key),
            message="LangSmith tracing is disabled.",
        )
    if settings.langsmith_api_key is None:
        return LangSmithStatus(
            enabled=True,
            ready=False,
            project=settings.langsmith_project,
            endpoint=endpoint,
            workspace_id_configured=bool(settings.langsmith_workspace_id),
            api_key_configured=False,
            message="LANGSMITH_API_KEY is required when LANGSMITH_TRACING=true.",
        )

    try:
        client = get_langsmith_client(settings)
        client.has_project(settings.langsmith_project)
    except Exception as exc:
        message = str(exc)
        if "403" in message or "Forbidden" in message:
            message = (
                "LangSmith rejected tracing with 403 Forbidden. Verify the API key and set "
                "LANGSMITH_WORKSPACE_ID when the key belongs to, or can access, multiple workspaces."
            )
        return LangSmithStatus(
            enabled=True,
            ready=False,
            project=settings.langsmith_project,
            endpoint=endpoint,
            workspace_id_configured=bool(settings.langsmith_workspace_id),
            api_key_configured=True,
            message=message,
        )

    return LangSmithStatus(
        enabled=True,
        ready=True,
        project=settings.langsmith_project,
        endpoint=endpoint,
        workspace_id_configured=bool(settings.langsmith_workspace_id),
        api_key_configured=True,
        message="LangSmith tracing is ready.",
    )


def reset_langsmith_state() -> None:
    global _langsmith_client, _langsmith_client_key, _langsmith_status, _langsmith_status_key
    _langsmith_client = None
    _langsmith_client_key = None
    _langsmith_status = None
    _langsmith_status_key = None
    _clear_langsmith_env_cache()


def _settings_key(settings: Settings) -> tuple[object, ...]:
    return (
        settings.app_env,
        settings.langsmith_tracing,
        settings.langsmith_project,
        settings.langsmith_endpoint,
        settings.langsmith_workspace_id,
        bool(settings.langsmith_api_key),
    )


def _clear_langsmith_env_cache() -> None:
    try:
        from langsmith import utils
    except ImportError:
        return
    cache_clear = getattr(utils.get_env_var, "cache_clear", None)
    if cache_clear is not None:
        cache_clear()


def _log_tracing_error(exc: Exception) -> None:
    logger.error("langsmith.trace_error %s", exc)
