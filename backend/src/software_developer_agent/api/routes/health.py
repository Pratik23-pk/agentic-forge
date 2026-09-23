from fastapi import APIRouter

from software_developer_agent.config.settings import get_settings
from software_developer_agent.observability.langsmith import get_langsmith_status

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health_check() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "environment": settings.app_env}


@router.get("/tracing")
def tracing_health_check() -> dict[str, str | bool]:
    settings = get_settings()
    return get_langsmith_status(settings).to_dict()
