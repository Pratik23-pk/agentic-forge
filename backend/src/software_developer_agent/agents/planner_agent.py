import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from software_developer_agent.capabilities.models import ProjectSpec
from software_developer_agent.capabilities.registry import (
    required_workers,
    resolve_capability,
    resolve_project_spec,
)
from software_developer_agent.config.settings import Settings
from software_developer_agent.integrations.llm_client import LLMClient
from software_developer_agent.memory.project_context_manager import ProjectContext
from software_developer_agent.models.job_state import JobRequest, JobTask, WorkerKind
from software_developer_agent.models.request_policy import RequestPolicy, derive_request_policy
from software_developer_agent.prompts.system_prompts import PLANNER_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PlanningResult:
    tasks: list[JobTask]
    api_contract: dict[str, Any]
    request_policy: RequestPolicy
    project_spec: ProjectSpec
    warnings: list[str] = field(default_factory=list)


class PlannerAgent:
    """Creates targeted worker tasks from the user request and project context."""

    def __init__(self, settings: Settings, llm_client: LLMClient | None = None) -> None:
        self._settings = settings
        self._llm_client = llm_client

    def plan(self, request: JobRequest, context: ProjectContext) -> list[JobTask]:
        return self.create_plan(request, context).tasks

    def create_plan(self, request: JobRequest, context: ProjectContext) -> PlanningResult:
        policy = derive_request_policy(request.prompt)
        project_spec = resolve_project_spec(request.prompt, request.metadata, policy)
        if self._settings.enable_llm_calls and self._llm_client is not None:
            try:
                planned = self._plan_with_llm(request, context, policy, project_spec)
                planned.tasks = self._ensure_required_scopes(
                    request,
                    context,
                    planned.tasks,
                    policy,
                    planned.api_contract,
                    project_spec,
                )
                return planned
            except Exception as exc:
                logger.exception("planner.llm_invalid")
                tasks = self._plan_with_keywords(request, context, policy, project_spec)
                api_contract = _default_api_contract(project_spec)
                return PlanningResult(
                    tasks=self._ensure_required_scopes(
                        request,
                        context,
                        tasks,
                        policy,
                        api_contract,
                        project_spec,
                    ),
                    api_contract=api_contract,
                    request_policy=policy,
                    project_spec=project_spec,
                    warnings=[
                        (
                            f"{_planner_failure_message(exc)} A deterministic capability plan was "
                            "used instead, so implementation can continue safely."
                        )
                    ],
                )

        tasks = self._plan_with_keywords(request, context, policy, project_spec)
        api_contract = _default_api_contract(project_spec)
        return PlanningResult(
            tasks=self._ensure_required_scopes(
                request,
                context,
                tasks,
                policy,
                api_contract,
                project_spec,
            ),
            api_contract=api_contract,
            request_policy=policy,
            project_spec=project_spec,
        )

    def _plan_with_keywords(
        self,
        request: JobRequest,
        context: ProjectContext,
        policy: RequestPolicy,
        project_spec: ProjectSpec,
    ) -> list[JobTask]:
        tasks: list[JobTask] = []
        for worker_kind in required_workers(project_spec, policy):
            tasks.append(
                JobTask(
                    worker_kind=worker_kind,
                    title=f"{worker_kind.value.title()} implementation",
                    instructions=self._compose_instructions(
                        request,
                        context,
                        worker_kind,
                        policy=policy,
                        api_contract=_default_api_contract(project_spec),
                        project_spec=project_spec,
                    ),
                    max_attempts=self._settings.max_worker_attempts,
                    capability_id=project_spec.capability_id,
                )
            )
        return tasks

    def _ensure_required_scopes(
        self,
        request: JobRequest,
        context: ProjectContext,
        tasks: list[JobTask],
        policy: RequestPolicy,
        api_contract: dict[str, Any],
        project_spec: ProjectSpec,
    ) -> list[JobTask]:
        if policy.excludes("database"):
            tasks = [task for task in tasks if task.worker_kind != WorkerKind.DATABASE]
        allowed = set(required_workers(project_spec, policy))
        tasks = [task for task in tasks if task.worker_kind in allowed]
        for task in tasks:
            task.capability_id = project_spec.capability_id
            task.adapter_ids = list(project_spec.adapter_ids)
        tasks = self._deduplicate_tasks(tasks)
        existing = {task.worker_kind for task in tasks}
        required = required_workers(project_spec, policy)
        for worker_kind in required:
            if worker_kind in existing:
                continue
            tasks.append(
                JobTask(
                    worker_kind=worker_kind,
                    title=f"{worker_kind.value.title()} implementation",
                    instructions=self._compose_instructions(
                        request,
                        context,
                        worker_kind,
                        policy=policy,
                        api_contract=api_contract,
                        project_spec=project_spec,
                    ),
                    max_attempts=self._settings.max_worker_attempts,
                    capability_id=project_spec.capability_id,
                    adapter_ids=list(project_spec.adapter_ids),
                )
            )
        return self._deduplicate_tasks(tasks)

    @staticmethod
    def _infer_required_workers(prompt: str) -> list[WorkerKind]:
        policy = derive_request_policy(prompt)
        return required_workers(resolve_project_spec(prompt, policy=policy), policy)

    @staticmethod
    def _prompt_has_any(prompt: str, keywords: tuple[str, ...]) -> bool:
        return any(_has_prompt_term(prompt, keyword) for keyword in keywords)

    def _plan_with_llm(
        self,
        request: JobRequest,
        context: ProjectContext,
        policy: RequestPolicy,
        project_spec: ProjectSpec,
    ) -> PlanningResult:
        default_contract = _default_api_contract(project_spec)
        user = (
            "Return JSON shape: "
            '{"api_contract":{"backend_port":8000,"frontend_port":5173,'
            '"runtime_connectivity":{"api_base_strategy":"same_origin_proxy",'
            '"frontend_api_env":"VITE_API_BASE_URL",'
            '"backend_cors_env":"CORS_ORIGINS","credentials_mode":"same-origin",'
            '"protocols":["http"]},"shared_limits":{},"routes":[]},'
            '"tasks":[{"worker_kind":"backend","title":"...","instructions":"...",'
            '"depends_on":[]}]}\n'
            f"Project: {context.project_id}\n"
            f"Request: {request.prompt}\n"
            f"Request policy: {json.dumps(policy.to_dict())}\n"
            f"Resolved project specification: {json.dumps(project_spec.to_dict())}\n"
            f"Use only these worker kinds: {[item.value for item in required_workers(project_spec, policy)]}\n"
            f"Default ports: {json.dumps(default_contract)}\n"
            f"Human planning feedback: {json.dumps(_human_planning_feedback(request))}\n"
            f"Constraints: {context.constraints[:6]}\n"
            f"Decisions: {context.decisions[-6:]}"
        )
        assert self._llm_client is not None
        response = self._llm_client.complete(PLANNER_SYSTEM_PROMPT, user)
        payload = json.loads(_extract_json(response.text))
        api_contract = payload.get("api_contract", {})
        if not isinstance(api_contract, dict):
            raise TypeError("Planner returned an invalid API contract.")
        api_contract = _normalize_api_contract(api_contract, project_spec)
        _validate_api_contract(api_contract)
        tasks: list[JobTask] = []
        for item in payload.get("tasks", []):
            worker_kind = WorkerKind(item["worker_kind"])
            planner_instructions = str(item["instructions"]).strip()
            tasks.append(
                JobTask(
                    worker_kind=worker_kind,
                    title=item["title"],
                    instructions=(
                        self._compose_instructions(
                            request,
                            context,
                            worker_kind,
                            policy=policy,
                            api_contract=api_contract,
                            project_spec=project_spec,
                        )
                        + f"\nPlanner task:\n{planner_instructions}"
                    ),
                    max_attempts=self._settings.max_worker_attempts,
                    depends_on=list(item.get("depends_on", [])),
                    capability_id=project_spec.capability_id,
                    adapter_ids=list(project_spec.adapter_ids),
                )
            )
        if not tasks:
            raise ValueError("Planner returned no tasks.")
        worker_kinds = {task.worker_kind for task in tasks}
        if {WorkerKind.BACKEND, WorkerKind.FRONTEND}.issubset(worker_kinds):
            routes = api_contract.get("routes", [])
            if not isinstance(routes, list) or not routes:
                raise ValueError("Full-stack plans require a non-empty shared API contract.")
        return PlanningResult(
            tasks=tasks,
            api_contract=api_contract,
            request_policy=policy,
            project_spec=project_spec,
        )

    @staticmethod
    def _compose_instructions(
        request: JobRequest,
        context: ProjectContext,
        worker: WorkerKind,
        *,
        policy: RequestPolicy | None = None,
        api_contract: dict[str, Any] | None = None,
        project_spec: ProjectSpec | None = None,
    ) -> str:
        constraints = "\n".join(f"- {constraint}" for constraint in context.constraints) or "- None"
        decisions = "\n".join(f"- {decision}" for decision in context.decisions[-5:]) or "- None"
        resolved_policy = policy or derive_request_policy(request.prompt)
        resolved_spec = project_spec or resolve_project_spec(
            request.prompt,
            request.metadata,
            resolved_policy,
        )
        capability = resolve_capability(resolved_spec.capability_id)
        user_media = _user_media_context(request)
        return (
            f"Worker: {worker.value}\n"
            f"Project: {context.project_id}\n"
            f"Request: {request.prompt}\n"
            f"Request policy: {json.dumps(resolved_policy.to_dict(), sort_keys=True)}\n"
            f"Capability: {resolved_spec.capability_id}\n"
            f"Project specification: {json.dumps(resolved_spec.to_dict(), sort_keys=True)}\n"
            f"Human planning feedback: {json.dumps(_human_planning_feedback(request))}\n"
            f"Stack: {capability.display_name}\n"
            f"Shared API contract: {json.dumps(api_contract or {}, sort_keys=True)}\n"
            f"Generation profile: {request.metadata.get('effective_generation_profile', 'standard')}\n"
            f"User media manifest: {json.dumps(user_media, sort_keys=True)}\n"
            "Media policy: User-provided, permitted downloaded, and verified embedded media may be "
            "combined when that best satisfies the request. User media never disables web media "
            "research. Reference only supplied web_path or verified tool URLs; never invent paths.\n"
            f"Known constraints:\n{constraints}\n"
            f"Recent decisions:\n{decisions}"
        )

    @staticmethod
    def _deduplicate_tasks(tasks: list[JobTask]) -> list[JobTask]:
        merged: dict[WorkerKind, JobTask] = {}
        order: list[WorkerKind] = []
        for task in tasks:
            existing = merged.get(task.worker_kind)
            if existing is None:
                merged[task.worker_kind] = task
                order.append(task.worker_kind)
                continue
            if task.instructions not in existing.instructions:
                existing.instructions += (
                    f"\nAdditional planner requirement ({task.title}):\n{task.instructions}"
                )
            existing.depends_on = list(dict.fromkeys([*existing.depends_on, *task.depends_on]))
        return [merged[worker_kind] for worker_kind in order]


def _extract_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.removeprefix("json").strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found.")
    return stripped[start : end + 1]


def _human_planning_feedback(request: JobRequest) -> list[str]:
    return [
        str(request.metadata[key]).strip()
        for key in (
            "product_contract_feedback",
            "privileged_action_feedback",
            "release_feedback",
        )
        if request.metadata.get(key)
    ]


def _user_media_context(request: JobRequest) -> list[dict[str, Any]]:
    assets = request.metadata.get("uploaded_assets", [])
    if not isinstance(assets, list):
        return []
    context: list[dict[str, Any]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        downloaded = asset.get("download")
        if not isinstance(downloaded, dict):
            continue
        context.append(
            {
                "asset_id": asset.get("asset_id"),
                "kind": asset.get("kind"),
                "title": asset.get("title"),
                "web_path": downloaded.get("web_path"),
                "mime_type": downloaded.get("mime_type"),
                "rights_status": asset.get("rights_status"),
            }
        )
    return context


def _has_prompt_term(prompt: str, term: str) -> bool:
    if "/" in term or "-" in term or " " in term:
        return term in prompt
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", prompt) is not None


def _validate_api_contract(contract: dict[str, Any]) -> None:
    for port_name in ("backend_port", "frontend_port"):
        port = contract.get(port_name)
        if port is not None and (
            isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535
        ):
            raise ValueError(f"Planner returned an invalid {port_name}.")

    routes = contract.get("routes", [])
    if not isinstance(routes, list):
        raise TypeError("Planner API contract routes must be a list.")
    seen: set[tuple[str, str]] = set()
    for route in routes:
        if not isinstance(route, dict):
            raise TypeError("Planner API contract route must be an object.")
        method = str(route.get("method", "")).upper()
        path = str(route.get("path", ""))
        status = route.get("success_status")
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError(f"Planner returned unsupported HTTP method {method!r}.")
        if not path.startswith("/") or " " in path:
            raise ValueError(f"Planner returned invalid route path {path!r}.")
        route_key = (method, path)
        if route_key in seen:
            raise ValueError(f"Planner returned duplicate route {method} {path}.")
        seen.add(route_key)
        if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
            raise ValueError(f"Planner returned invalid status for {method} {path}.")
        for example_name in ("request_example", "response_example"):
            example = route.get(example_name)
            try:
                json.dumps(example)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Planner returned non-JSON {example_name} for {method} {path}."
                ) from exc

    shared_limits = contract.get("shared_limits", {})
    if not isinstance(shared_limits, dict):
        raise TypeError("Planner API contract shared_limits must be an object.")
    for name, value in shared_limits.items():
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"Planner returned invalid shared limit {name!r}.")

    connectivity = contract.get("runtime_connectivity")
    if connectivity is not None:
        if not isinstance(connectivity, dict):
            raise TypeError("Planner runtime_connectivity must be an object.")
        if connectivity.get("api_base_strategy") != "same_origin_proxy":
            raise ValueError("Planner must use the certified same_origin_proxy API strategy.")
        if connectivity.get("frontend_api_env") not in {
            "VITE_API_BASE_URL",
            "NEXT_PUBLIC_API_BASE_URL",
        }:
            raise ValueError("Planner returned an unsupported frontend API environment variable.")
        if connectivity.get("backend_cors_env") != "CORS_ORIGINS":
            raise ValueError("Planner must use CORS_ORIGINS for backend origin configuration.")
        if connectivity.get("credentials_mode") not in {"omit", "same-origin", "include"}:
            raise ValueError("Planner returned an unsupported browser credentials mode.")
        protocols = connectivity.get("protocols")
        if (
            not isinstance(protocols, list)
            or not protocols
            or any(protocol not in {"http", "websocket"} for protocol in protocols)
        ):
            raise ValueError("Planner returned unsupported runtime protocols.")


def _normalize_api_contract(
    contract: dict[str, Any],
    project_spec: ProjectSpec,
) -> dict[str, Any]:
    normalized = dict(contract)
    shared_limits = dict(normalized.get("shared_limits") or {})
    if "file-upload" in project_spec.adapter_ids:
        shared_limits.setdefault("max_upload_bytes", 100 * 1024 * 1024)
    if shared_limits:
        normalized["shared_limits"] = shared_limits
    if _uses_separate_frontend_and_backend(project_spec):
        protocols = ["http"]
        if "realtime" in project_spec.adapter_ids:
            protocols.append("websocket")
        normalized["runtime_connectivity"] = {
            "api_base_strategy": "same_origin_proxy",
            "frontend_api_env": (
                "NEXT_PUBLIC_API_BASE_URL"
                if project_spec.frontend_framework == "Next.js"
                else "VITE_API_BASE_URL"
            ),
            "backend_cors_env": "CORS_ORIGINS",
            "credentials_mode": (
                "include" if "auth-rbac" in project_spec.adapter_ids else "same-origin"
            ),
            "protocols": protocols,
        }
    return normalized


def _default_api_contract(project_spec: ProjectSpec) -> dict[str, Any]:
    return _normalize_api_contract({
        "backend_port": project_spec.ports.get("backend"),
        "frontend_port": project_spec.ports.get(
            "frontend",
            project_spec.ports.get("application"),
        ),
        "routes": [],
    }, project_spec)


def _uses_separate_frontend_and_backend(project_spec: ProjectSpec) -> bool:
    return (
        project_spec.frontend_framework is not None
        and project_spec.backend_framework is not None
        and "frontend" in project_spec.ports
        and "backend" in project_spec.ports
    )


def _planner_failure_message(exc: Exception) -> str:
    message = str(exc).lower()
    if "insufficient_quota" in message or "exceeded your current quota" in message:
        return "OpenAI quota is exhausted; update API billing or use a key with available quota."
    if "authentication" in message or "incorrect api key" in message:
        return "OpenAI rejected the configured API key."
    if "rate limit" in message or "too many requests" in message:
        return "OpenAI rate-limited the planner after automatic retries."
    return "Planner model did not return a valid implementation plan."


def _explicitly_excludes_database(prompt: str) -> bool:
    return derive_request_policy(prompt).excludes("database")
