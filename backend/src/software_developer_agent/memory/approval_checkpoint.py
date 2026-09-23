from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from software_developer_agent.config.settings import Settings
from software_developer_agent.memory.langgraph_memory import open_langgraph_resources
from software_developer_agent.models.job_state import ApprovalGate, JobState


def merge_gate_records(
    current: dict[str, dict[str, Any]] | None,
    updates: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    merged = dict(current or {})
    for gate, candidate in (updates or {}).items():
        existing = merged.get(gate, {})
        if int(candidate.get("revision", 0)) >= int(existing.get("revision", 0)):
            merged[gate] = dict(candidate)
    return merged


class ApprovalGraphState(TypedDict, total=False):
    job_id: str
    revision: int
    gates: Annotated[dict[str, dict[str, Any]], merge_gate_records]


def _checkpoint_node(_: ApprovalGraphState) -> dict[str, Any]:
    return {}


def _build_graph(checkpointer, store):
    builder = StateGraph(ApprovalGraphState)
    builder.add_node("checkpoint_approval", _checkpoint_node)
    builder.add_edge(START, "checkpoint_approval")
    builder.add_edge("checkpoint_approval", END)
    return builder.compile(checkpointer=checkpointer, store=store)


class ApprovalCheckpointManager:
    """Persists HITL requests and decisions independently from execution attempts."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def restore(self, job: JobState) -> dict[str, Any]:
        if not self._settings.enable_langgraph_checkpointing:
            return job.approval_state
        with open_langgraph_resources(self._settings) as (checkpointer, store):
            graph = _build_graph(checkpointer, store)
            snapshot = graph.get_state(_thread_config(job))
            checkpoint = dict(snapshot.values) if snapshot.values else {}
            if job.approval_state and int(job.approval_state.get("revision", 0)) > int(
                checkpoint.get("revision", 0)
            ):
                checkpoint = dict(graph.invoke(job.approval_state, _thread_config(job)))
            if checkpoint:
                job.approval_state = checkpoint
            return job.approval_state

    def record(
        self,
        job: JobState,
        gate: ApprovalGate,
        status: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        previous = self.restore(job)
        revision = int(previous.get("revision", 0)) + 1
        update: ApprovalGraphState = {
            "job_id": job.job_id,
            "revision": revision,
            "gates": {
                gate.value: {
                    "revision": revision,
                    "status": status,
                    "payload": dict(payload or {}),
                }
            },
        }
        if self._settings.enable_langgraph_checkpointing:
            with open_langgraph_resources(self._settings) as (checkpointer, store):
                graph = _build_graph(checkpointer, store)
                state = dict(graph.invoke(update, _thread_config(job)))
        else:
            state = {
                "job_id": job.job_id,
                "revision": revision,
                "gates": merge_gate_records(previous.get("gates"), update["gates"]),
            }
        job.approval_state = state
        job.touch()
        return state

    def status(self, job: JobState, gate: ApprovalGate) -> str | None:
        state = self.restore(job)
        record = state.get("gates", {}).get(gate.value, {})
        value = record.get("status")
        return str(value) if value is not None else None


def _thread_config(job: JobState) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": f"{job.job_id}:approvals"}}
