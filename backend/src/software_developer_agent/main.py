import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from software_developer_agent.api.routes import (
    explanations,
    health,
    jobs,
    media,
    metrics,
    previews,
    providers,
    workspace,
)
from software_developer_agent.config.settings import get_settings
from software_developer_agent.memory.langgraph_memory import initialize_langgraph_storage
from software_developer_agent.observability.langsmith import (
    configure_langsmith_environment,
    disable_langsmith_runtime_tracing,
    get_langsmith_status,
)
from software_developer_agent.observability.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_langsmith_environment(settings)
    tracing_status = get_langsmith_status(settings)
    if settings.langsmith_tracing:
        logging.getLogger(__name__).info("langsmith.status %s", tracing_status.to_dict())
    if not tracing_status.ready:
        disable_langsmith_runtime_tracing()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        initialize_langgraph_storage(settings)
        yield

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url="/redoc" if settings.app_env != "production" else None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(explanations.router, prefix="/api")
    app.include_router(media.router, prefix="/api")
    app.include_router(previews.router, prefix="/api")
    app.include_router(workspace.router, prefix="/api")
    app.include_router(providers.router, prefix="/api")
    app.include_router(metrics.router, prefix="/api")
    return app


app = create_app()
