from functools import lru_cache
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_project_root() -> Path:
    """Resolve the repository root even when the package is imported from a venv."""

    override = os.getenv("AGENTIC_FORGE_HOME") or os.getenv("SOFTWARE_DEVELOPER_AGENT_HOME")
    if override:
        return Path(override).expanduser().resolve()

    candidates = [Path.cwd(), *Path(__file__).resolve().parents]
    seen: set[Path] = set()
    for start in candidates:
        for candidate in (start, *start.parents):
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if (
                (candidate / ".env").exists()
                and (candidate / "backend").is_dir()
                and (candidate / "frontend").is_dir()
            ):
                return resolved
            if (
                (candidate / "backend" / "pyproject.toml").exists()
                and (candidate / "frontend" / "package.json").exists()
            ):
                return resolved

    return Path(__file__).resolve().parents[4]


PROJECT_ROOT = _find_project_root()


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Software Developer Agent"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.6-luna"
    openai_router_model: str = "gpt-5.6-luna"
    openai_planner_model: str = "gpt-5.6-terra"
    openai_design_model: str = "gpt-5.6-sol"
    openai_worker_model: str = "gpt-5.6-terra"
    openai_frontend_model: str = "gpt-5.6-terra"
    openai_backend_model: str = "gpt-5.6-terra"
    openai_database_model: str = "gpt-5.6-luna"
    openai_repair_model: str = "gpt-5.6-sol"
    openai_repair_standard_model: str = "gpt-5.6-terra"
    openai_evaluator_model: str = "gpt-5.6-luna"
    openai_visual_evaluator_model: str = "gpt-5.6-terra"
    openai_artifact_model: str = "gpt-5.6-luna"
    openai_explainer_model: str = "gpt-6-luna"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_transcription_model: str = "gpt-4o-mini-transcribe"
    transcription_cost_per_minute_usd: float = Field(default=0.003, ge=0)
    normal_run_budget_usd: float = Field(default=0.25, gt=0)
    maximum_run_budget_usd: float = Field(default=1.0, gt=0, le=1.0)
    default_advanced_run_budget_usd: float = Field(default=1.5, gt=0)
    maximum_advanced_run_budget_usd: float = Field(default=5.0, gt=1.0, le=25.0)

    supabase_url: str | None = None
    supabase_anon_key: SecretStr | None = None
    supabase_service_role_key: SecretStr | None = None
    redis_url: str = "redis://localhost:6379/0"
    database_url: SecretStr | None = None

    serper_api_key: SecretStr | None = None

    github_token: SecretStr | None = None
    github_api_url: str = "https://api.github.com"
    github_api_version: str = "2026-03-10"
    supabase_management_access_token: SecretStr | None = None
    supabase_management_api_url: str = "https://api.supabase.com"
    provider_timeout_seconds: int = Field(default=60, ge=5, le=300)

    langsmith_api_key: SecretStr | None = None
    langsmith_tracing: bool = False
    langsmith_project: str = "software-developer-agent"
    langsmith_endpoint: str | None = None
    langsmith_workspace_id: str | None = None

    max_input_tokens: int = Field(default=25_000, ge=1)
    max_job_loops: int = Field(default=12, ge=1)
    max_automatic_replans: int = Field(default=1, ge=0, le=2)
    max_worker_attempts: int = Field(default=4, ge=1)
    max_total_attempts: int = Field(default=12, ge=1)
    max_manifest_recovery_attempts: int = Field(default=2, ge=0, le=4)
    max_llm_calls_per_node: int = Field(default=6, ge=1, le=20)
    request_timeout_seconds: int = Field(default=180, ge=1)
    openai_transport_retries: int = Field(default=0, ge=0, le=2)
    tool_timeout_seconds: int = Field(default=20, ge=1)
    artifact_validation_timeout_seconds: int = Field(default=240, ge=10)
    artifact_audit_timeout_seconds: int = Field(default=15, ge=10, le=300)
    artifact_infrastructure_retry_attempts: int = Field(default=1, ge=0, le=4)
    artifact_validation_memory_limit_mb: int = Field(default=2048, ge=512, le=8192)
    artifact_validation_sandbox_mode: Literal["local", "docker"] = "docker"
    max_search_results: int = Field(default=5, ge=1, le=10)
    max_browser_pages: int = Field(default=3, ge=0, le=10)
    max_media_assets: int = Field(default=3, ge=1, le=8)
    max_image_download_bytes: int = Field(default=12_000_000, ge=100_000, le=50_000_000)
    max_video_download_bytes: int = Field(
        default=64_000_000,
        ge=1_000_000,
        le=250_000_000,
    )
    max_user_media_assets: int = Field(default=8, ge=1, le=24)
    max_user_image_upload_bytes: int = Field(
        default=20_000_000,
        ge=100_000,
        le=100_000_000,
    )
    max_user_video_upload_bytes: int = Field(
        default=250_000_000,
        ge=1_000_000,
        le=1_000_000_000,
    )
    max_voice_recording_bytes: int = Field(
        default=25_000_000,
        ge=100_000,
        le=100_000_000,
    )
    max_voice_recording_seconds: int = Field(default=600, ge=5, le=3600)
    explainer_max_input_chars: int = Field(default=60_000, ge=10_000, le=200_000)
    explainer_chat_context_chars: int = Field(default=6_000, ge=3_000, le=20_000)
    explainer_max_question_chars: int = Field(default=2_000, ge=200, le=10_000)
    explainer_max_output_tokens: int = Field(default=500, ge=96, le=1_000)
    explainer_prompt_limit: int = Field(default=10, ge=1, le=10)
    explainer_budget_usd: float = Field(default=0.01, gt=0, le=0.01)
    explainer_per_prompt_budget_usd: float = Field(default=0.001, gt=0, le=0.001)
    max_human_checkpoints: int = Field(default=4, ge=0, le=8)
    artifacts_dir: Path = PROJECT_ROOT / "artifacts"
    generated_projects_dir: Path = PROJECT_ROOT / "generated-projects"
    preview_cache_dir: Path = PROJECT_ROOT / ".agentic-forge" / "previews"
    media_cache_dir: Path = PROJECT_ROOT / ".agentic-forge" / "media-cache"
    upload_cache_dir: Path = PROJECT_ROOT / ".agentic-forge" / "upload-cache"
    preview_host: str = "127.0.0.1"
    preview_port_start: int = Field(default=4100, ge=1024, le=65_000)
    preview_port_end: int = Field(default=4199, ge=1024, le=65_535)
    preview_startup_timeout_seconds: int = Field(default=30, ge=1, le=300)
    preview_install_timeout_seconds: int = Field(default=240, ge=10, le=1800)
    preview_memory_limit_mb: int = Field(default=1024, ge=128, le=8192)
    preview_cpu_limit_seconds: int = Field(default=300, ge=10, le=3600)
    preview_sandbox_mode: Literal["local", "docker"] = "docker"
    preview_docker_network: str = "agentic-forge-quarantine"
    enable_auto_preview: bool = True

    enable_llm_calls: bool = False
    enable_mcp_tools: bool = True
    enable_human_checkpoints: bool = True
    enable_redis: bool = False
    enable_persistence: bool = False
    enable_langgraph_checkpointing: bool = True
    enable_web_search: bool = False
    enable_browser: bool = False
    enable_media_downloads: bool = True
    enable_artifact_generation: bool = True
    enable_artifact_validation: bool = True
    enable_domain_adapter_validation: bool = True
    enable_guaranteed_artifact_fallback: bool = True
    enable_live_preview: bool = True
    enable_browser_editor: bool = True
    enable_collaboration: bool = True
    enable_provider_actions: bool = False
    enable_project_explainer: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
