from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from software_developer_agent.models.job_state import JobState


@dataclass(frozen=True, slots=True)
class PrivilegedAction:
    action_id: str
    title: str
    reason: str
    scope: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


_ACTION_RULES: tuple[tuple[re.Pattern[str], PrivilegedAction, frozenset[str]], ...] = (
    (
        re.compile(
            r"\b(?:push|publish|sync|commit|open)\b.{0,50}\b(?:github|repository|pull request)\b",
            re.IGNORECASE,
        ),
        PrivilegedAction(
            "github_write",
            "Write to GitHub",
            "The workflow would modify a remote repository or create a pull request.",
            "Selected repository and generated branch only",
        ),
        frozenset({"github"}),
    ),
    (
        re.compile(
            r"\b(?:deploy|publish|release)\b.{0,70}\b(?:production|aws|cloud|vercel|netlify)\b",
            re.IGNORECASE,
        ),
        PrivilegedAction(
            "production_deploy",
            "Deploy production resources",
            "The workflow would create or update externally reachable infrastructure.",
            "Named project and deployment environment only",
        ),
        frozenset({"deployment", "cloud"}),
    ),
    (
        re.compile(
            r"\b(?:create|provision)\b.{0,60}\b(?:supabase|database|bucket|aws|cloud resource)\b",
            re.IGNORECASE,
        ),
        PrivilegedAction(
            "resource_provision",
            "Provision managed resources",
            "The workflow may create billable database, storage, or cloud resources.",
            "Explicitly listed resources only",
        ),
        frozenset({"database", "cloud"}),
    ),
    (
        re.compile(
            r"\b(?:drop|delete|truncate|alter|migrate)\b.{0,60}\b(?:production|database|schema|table|bucket)\b",
            re.IGNORECASE,
        ),
        PrivilegedAction(
            "destructive_data_change",
            "Modify persistent data",
            "The workflow would change or remove persistent records or schema objects.",
            "Named migration and target environment only",
        ),
        frozenset({"database"}),
    ),
    (
        re.compile(
            r"\b(?:activate|charge|refund|capture)\b.{0,50}\b(?:stripe|payment|card|subscription)\b",
            re.IGNORECASE,
        ),
        PrivilegedAction(
            "live_payment_action",
            "Execute a payment action",
            "The workflow would perform a live billing operation.",
            "Named test or live transaction only",
        ),
        frozenset({"billing"}),
    ),
)


def privileged_actions_for_job(job: JobState) -> list[dict[str, str]]:
    explicit = job.request.metadata.get("privileged_actions", [])
    actions: list[PrivilegedAction] = []
    if isinstance(explicit, list):
        for item in explicit:
            if not isinstance(item, dict) or not item.get("action_id"):
                continue
            actions.append(
                PrivilegedAction(
                    action_id=str(item["action_id"]),
                    title=str(item.get("title", item["action_id"])),
                    reason=str(item.get("reason", "The action changes an external system.")),
                    scope=str(item.get("scope", "Explicitly approved target only")),
                )
            )

    excluded = {str(item).lower() for item in job.request_policy.get("excluded_capabilities", [])}
    denied = {str(item) for item in job.request.metadata.get("denied_privileged_actions", [])}
    for pattern, action, related_capabilities in _ACTION_RULES:
        if action.action_id in denied:
            continue
        if related_capabilities.intersection(excluded):
            continue
        if pattern.search(job.request.prompt):
            actions.append(action)

    unique: dict[str, PrivilegedAction] = {}
    for action in actions:
        if action.action_id not in denied:
            unique[action.action_id] = action
    return [action.to_dict() for action in unique.values()]


def approval_contract(job: JobState) -> dict[str, Any]:
    public_preflight = {
        key: value
        for key, value in job.preflight.items()
        if key not in {"authorized_budget_usd", "estimated_cost_usd"}
    }
    return {
        "project_id": job.request.project_id,
        "request": job.request.prompt,
        "generation_preflight": public_preflight,
        "stack": job.project_spec,
        "design": job.design_spec,
        "workers": [
            {
                "worker_kind": task.worker_kind.value,
                "title": task.title,
                "depends_on": task.depends_on,
            }
            for task in job.tasks
        ],
        "api_contract": job.api_contract,
        "privileged_actions": privileged_actions_for_job(job),
    }
