from dataclasses import dataclass

from software_developer_agent.config.settings import Settings


@dataclass(slots=True)
class DatabaseHealth:
    configured: bool
    message: str


def check_database_configuration(settings: Settings) -> DatabaseHealth:
    if not settings.database_url:
        return DatabaseHealth(configured=False, message="DATABASE_URL is not configured.")
    return DatabaseHealth(configured=True, message="DATABASE_URL is configured.")


def get_database_dsn(settings: Settings) -> str:
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is required for Postgres persistence.")
    return settings.database_url.get_secret_value()
