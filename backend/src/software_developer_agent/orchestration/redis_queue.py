from __future__ import annotations

import json
from collections import deque
from threading import Lock
from typing import Protocol

from software_developer_agent.config.settings import Settings, get_settings
from software_developer_agent.integrations.redis_client import create_redis_client
from software_developer_agent.models.job_state import JobState, job_state_from_dict


class JobQueue(Protocol):
    def submit(self, job: JobState) -> str: ...

    def pop_next(self) -> JobState | None: ...

    def get(self, job_id: str) -> JobState | None: ...

    def update(self, job: JobState) -> None: ...

    def list_jobs(self) -> list[JobState]: ...


class InMemoryJobQueue:
    """Queue implementation for local development and tests."""

    def __init__(self) -> None:
        self._job_ids: deque[str] = deque()
        self._jobs: dict[str, JobState] = {}
        self._lock = Lock()

    def submit(self, job: JobState) -> str:
        with self._lock:
            self._jobs[job.job_id] = job
            self._job_ids.append(job.job_id)
        return job.job_id

    def pop_next(self) -> JobState | None:
        with self._lock:
            if not self._job_ids:
                return None
            return self._jobs[self._job_ids.popleft()]

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job: JobState) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def list_jobs(self) -> list[JobState]:
        with self._lock:
            return list(self._jobs.values())


class RedisJobQueue:
    """Redis-compatible queue using JSON job snapshots."""

    queue_key = "software_developer_agent:jobs"
    recent_jobs_key = "software_developer_agent:recent_jobs"
    job_key_prefix = "software_developer_agent:job:"

    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    def submit(self, job: JobState) -> str:
        self.update(job)
        self._redis.rpush(self.queue_key, job.job_id)
        self._remember_recent(job.job_id)
        return job.job_id

    def pop_next(self) -> JobState | None:
        job_id = self._redis.lpop(self.queue_key)
        if job_id is None:
            return None
        return self.get(str(job_id))

    def get(self, job_id: str) -> JobState | None:
        payload = self._redis.get(self.job_key_prefix + job_id)
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return job_state_from_dict(json.loads(payload))

    def update(self, job: JobState) -> None:
        self._redis.set(self.job_key_prefix + job.job_id, json.dumps(job.to_dict()))
        self._remember_recent(job.job_id)

    def list_jobs(self) -> list[JobState]:
        job_ids = self._redis.lrange(self.recent_jobs_key, 0, 49)
        jobs: list[JobState] = []
        for raw_job_id in job_ids:
            job_id = (
                raw_job_id.decode("utf-8") if isinstance(raw_job_id, bytes) else str(raw_job_id)
            )
            job = self.get(job_id)
            if job is not None:
                jobs.append(job)
        return jobs

    def _remember_recent(self, job_id: str) -> None:
        self._redis.lrem(self.recent_jobs_key, 0, job_id)
        self._redis.lpush(self.recent_jobs_key, job_id)
        self._redis.ltrim(self.recent_jobs_key, 0, 49)


_memory_queue = InMemoryJobQueue()
_redis_queue: RedisJobQueue | None = None


def get_job_queue(settings: Settings | None = None) -> JobQueue:
    global _redis_queue
    resolved = settings or get_settings()
    if not resolved.enable_redis:
        return _memory_queue
    if _redis_queue is None:
        _redis_queue = RedisJobQueue(create_redis_client(resolved))
    return _redis_queue


job_queue = _memory_queue
