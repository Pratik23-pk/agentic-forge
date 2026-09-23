from __future__ import annotations

import json
from threading import Lock
from typing import Protocol

from software_developer_agent.config.settings import Settings, get_settings
from software_developer_agent.integrations.database_client import get_database_dsn
from software_developer_agent.models.job_state import JobState, job_state_from_dict


class JobStore(Protocol):
    def save(self, job: JobState) -> None: ...

    def get(self, job_id: str) -> JobState | None: ...

    def list_recent(self, limit: int = 50) -> list[JobState]: ...


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}
        self._lock = Lock()

    def save(self, job: JobState) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_recent(self, limit: int = 50) -> list[JobState]:
        with self._lock:
            return sorted(
                self._jobs.values(),
                key=lambda job: job.updated_at,
                reverse=True,
            )[:limit]


class PostgresJobStore:
    """Supabase/Postgres-backed job snapshots.

    The normalized tables in migrations are available for analytics, but the
    snapshot keeps state restoration simple and resilient while the schema evolves.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def save(self, job: JobState) -> None:
        payload = job.to_dict()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                    insert into agent_jobs (
                        job_id, project_id, prompt, status, loop_count, snapshot,
                        created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    on conflict (job_id) do update set
                        project_id = excluded.project_id,
                        prompt = excluded.prompt,
                        status = excluded.status,
                        loop_count = excluded.loop_count,
                        snapshot = excluded.snapshot,
                        updated_at = excluded.updated_at
                """,
                (
                    job.job_id,
                    job.request.project_id,
                    job.request.prompt,
                    job.status.value,
                    job.loop_count,
                    json.dumps(payload),
                    job.created_at,
                    job.updated_at,
                ),
            )

    def get(self, job_id: str) -> JobState | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("select snapshot from agent_jobs where job_id = %s", (job_id,))
            row = cursor.fetchone()
        if row is None:
            return None
        return job_state_from_dict(row[0])

    def list_recent(self, limit: int = 50) -> list[JobState]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                    select snapshot
                    from agent_jobs
                    order by updated_at desc
                    limit %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()
        return [job_state_from_dict(row[0]) for row in rows]

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("Install psycopg to enable Supabase/Postgres persistence.") from exc
        return psycopg.connect(get_database_dsn(self._settings))


_memory_store = InMemoryJobStore()
_postgres_store: PostgresJobStore | None = None


def get_job_store(settings: Settings | None = None) -> JobStore:
    global _postgres_store
    resolved = settings or get_settings()
    if not resolved.enable_persistence:
        return _memory_store
    if resolved.database_url is None:
        raise RuntimeError("ENABLE_PERSISTENCE=true requires DATABASE_URL.")
    if _postgres_store is None:
        _postgres_store = PostgresJobStore(resolved)
    return _postgres_store
