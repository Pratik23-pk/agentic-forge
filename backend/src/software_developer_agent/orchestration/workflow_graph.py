from __future__ import annotations

from typing import Any, Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph


class WorkflowGraphState(TypedDict, total=False):
    job: dict[str, Any]
    retry_targets: list[str] | None
    repair_registered: bool
    next_action: str
    route: dict[str, Any] | None
    phase: str


class WorkflowGraphHandlers(Protocol):
    def graph_guardrails(self, state: WorkflowGraphState) -> dict[str, Any]: ...

    def graph_plan(self, state: WorkflowGraphState) -> dict[str, Any]: ...

    def graph_design(self, state: WorkflowGraphState) -> dict[str, Any]: ...

    def graph_product_approval(self, state: WorkflowGraphState) -> dict[str, Any]: ...

    def graph_privileged_approval(self, state: WorkflowGraphState) -> dict[str, Any]: ...

    def graph_execute_workers(self, state: WorkflowGraphState) -> dict[str, Any]: ...

    def graph_output_guardrails(self, state: WorkflowGraphState) -> dict[str, Any]: ...

    def graph_assemble_validate(self, state: WorkflowGraphState) -> dict[str, Any]: ...

    def graph_evaluate(self, state: WorkflowGraphState) -> dict[str, Any]: ...

    def graph_route(self, state: WorkflowGraphState) -> dict[str, Any]: ...

    def graph_prepare_retry(self, state: WorkflowGraphState) -> dict[str, Any]: ...

    def graph_replan(self, state: WorkflowGraphState) -> dict[str, Any]: ...

    def graph_release_approval(self, state: WorkflowGraphState) -> dict[str, Any]: ...

    def graph_finalize_success(self, state: WorkflowGraphState) -> dict[str, Any]: ...

    def graph_finalize_failure(self, state: WorkflowGraphState) -> dict[str, Any]: ...


WORKFLOW_NODE_NAMES = (
    "guardrails",
    "plan",
    "design",
    "product_approval",
    "privileged_approval",
    "execute_workers",
    "output_guardrails",
    "assemble_validate",
    "evaluate",
    "route",
    "prepare_retry",
    "replan",
    "release_approval",
    "finalize_success",
    "finalize_failure",
)


def build_workflow_graph(handlers: WorkflowGraphHandlers, checkpointer, store):
    builder = StateGraph(WorkflowGraphState)
    builder.add_node("guardrails", handlers.graph_guardrails)
    builder.add_node("plan", handlers.graph_plan)
    builder.add_node("design", handlers.graph_design)
    builder.add_node("product_approval", handlers.graph_product_approval)
    builder.add_node("privileged_approval", handlers.graph_privileged_approval)
    builder.add_node("execute_workers", handlers.graph_execute_workers)
    builder.add_node("output_guardrails", handlers.graph_output_guardrails)
    builder.add_node("assemble_validate", handlers.graph_assemble_validate)
    builder.add_node("evaluate", handlers.graph_evaluate)
    builder.add_node("route", handlers.graph_route)
    builder.add_node("prepare_retry", handlers.graph_prepare_retry)
    builder.add_node("replan", handlers.graph_replan)
    builder.add_node("release_approval", handlers.graph_release_approval)
    builder.add_node("finalize_success", handlers.graph_finalize_success)
    builder.add_node("finalize_failure", handlers.graph_finalize_failure)

    builder.add_edge(START, "guardrails")
    builder.add_conditional_edges(
        "guardrails",
        _continue_or_end,
        {"continue": "plan", "end": END},
    )
    builder.add_edge("plan", "design")
    builder.add_edge("design", "product_approval")
    builder.add_conditional_edges(
        "product_approval",
        _continue_or_end,
        {"continue": "privileged_approval", "end": END},
    )
    builder.add_conditional_edges(
        "privileged_approval",
        _continue_or_end,
        {"continue": "execute_workers", "end": END},
    )
    builder.add_conditional_edges(
        "execute_workers",
        _continue_or_failure,
        {"continue": "output_guardrails", "failure": "finalize_failure"},
    )
    builder.add_edge("output_guardrails", "assemble_validate")
    builder.add_edge("assemble_validate", "evaluate")
    builder.add_edge("evaluate", "route")
    builder.add_conditional_edges(
        "route",
        _route_action,
        {
            "retry": "prepare_retry",
            "replan": "replan",
            "success": "release_approval",
            "failure": "finalize_failure",
        },
    )
    builder.add_edge("prepare_retry", "execute_workers")
    builder.add_conditional_edges(
        "replan",
        _continue_or_failure,
        {"continue": "design", "failure": "finalize_failure"},
    )
    builder.add_conditional_edges(
        "release_approval",
        _continue_or_end,
        {"continue": "finalize_success", "end": END},
    )
    builder.add_edge("finalize_success", END)
    builder.add_edge("finalize_failure", END)
    return builder.compile(checkpointer=checkpointer, store=store)


def _continue_or_end(state: WorkflowGraphState) -> Literal["continue", "end"]:
    return "end" if state.get("next_action") == "end" else "continue"


def _continue_or_failure(
    state: WorkflowGraphState,
) -> Literal["continue", "failure"]:
    return "failure" if state.get("next_action") == "failure" else "continue"


def _route_action(
    state: WorkflowGraphState,
) -> Literal["retry", "replan", "success", "failure"]:
    action = state.get("next_action", "failure")
    if action in {"retry", "replan", "success", "failure"}:
        return action
    return "failure"
