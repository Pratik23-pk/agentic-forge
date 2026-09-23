from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from threading import Lock
from typing import Any

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from software_developer_agent.config.settings import Settings, get_settings
from software_developer_agent.integrations.database_client import get_database_dsn


@dataclass(slots=True)
class MemoryCheckpoint:
    project_id: str
    summary: str
    decisions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


_memory_checkpointer = InMemorySaver()
_memory_store = InMemoryStore()
_setup_lock = Lock()
_configured_postgres: set[str] = set()


@contextmanager
def open_langgraph_resources(
    settings: Settings,
) -> Iterator[tuple[BaseCheckpointSaver, BaseStore]]:
    """Open checkpoint and long-term memory resources for one durable operation."""

    if settings.app_env == "test" or not settings.enable_persistence:
        yield _memory_checkpointer, _memory_store
        return

    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.store.postgres import PostgresStore

    dsn = get_database_dsn(settings)
    fingerprint = sha256(dsn.encode("utf-8")).hexdigest()
    with (
        PostgresSaver.from_conn_string(dsn) as checkpointer,
        PostgresStore.from_conn_string(dsn) as store,
    ):
        with _setup_lock:
            if fingerprint not in _configured_postgres:
                checkpointer.setup()
                store.setup()
                _configured_postgres.add(fingerprint)
        yield checkpointer, store


class LangGraphProjectMemory:
    """Project-scoped long-term memory backed by the LangGraph Store interface."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def checkpoint(self, project_id: str) -> MemoryCheckpoint:
        with open_langgraph_resources(self._settings) as (_, store):
            item = store.get(_project_namespace(project_id), "context")
        value = item.value if item is not None else {}
        return MemoryCheckpoint(
            project_id=project_id,
            summary=str(value.get("summary", "")),
            decisions=[str(item) for item in value.get("decisions", [])],
            constraints=[str(item) for item in value.get("constraints", [])],
        )

    def remember_decision(self, project_id: str, decision: str) -> None:
        checkpoint = self.checkpoint(project_id)
        decisions = [*checkpoint.decisions]
        if decision not in decisions:
            decisions.append(decision)
        self._put(
            project_id,
            {
                "summary": checkpoint.summary,
                "decisions": decisions,
                "constraints": checkpoint.constraints,
            },
        )

    def remember_constraint(self, project_id: str, constraint: str) -> None:
        checkpoint = self.checkpoint(project_id)
        constraints = [*checkpoint.constraints]
        if constraint not in constraints:
            constraints.append(constraint)
        self._put(
            project_id,
            {
                "summary": checkpoint.summary,
                "decisions": checkpoint.decisions,
                "constraints": constraints,
            },
        )

    def remember_plan(
        self,
        project_id: str,
        *,
        summary: str,
        decisions: list[str],
        constraints: list[str],
    ) -> None:
        checkpoint = self.checkpoint(project_id)
        merged_decisions = list(dict.fromkeys([*checkpoint.decisions, *decisions]))
        merged_constraints = list(dict.fromkeys([*checkpoint.constraints, *constraints]))
        self._put(
            project_id,
            {
                "summary": summary.strip()[:4_000],
                "decisions": merged_decisions,
                "constraints": merged_constraints,
            },
        )

    def _put(self, project_id: str, value: dict[str, Any]) -> None:
        with open_langgraph_resources(self._settings) as (_, store):
            store.put(_project_namespace(project_id), "context", value)


def _project_namespace(project_id: str) -> tuple[str, str]:
    digest = sha256(project_id.encode("utf-8")).hexdigest()
    return ("agentic-forge-projects", digest)


project_memory = LangGraphProjectMemory()


def initialize_langgraph_storage(settings: Settings) -> None:
    """Run idempotent checkpoint and Store migrations before serving jobs."""

    if not settings.enable_langgraph_checkpointing and not settings.enable_persistence:
        return
    with open_langgraph_resources(settings):
        return
