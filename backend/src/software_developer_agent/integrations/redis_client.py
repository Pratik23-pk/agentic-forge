from typing import Any

from software_developer_agent.config.settings import Settings


def create_redis_client(settings: Settings) -> Any:
    try:
        from redis import Redis
    except ImportError as exc:
        raise RuntimeError("Install the redis package to enable Redis-backed queues.") from exc

    return Redis.from_url(settings.redis_url, decode_responses=True)
