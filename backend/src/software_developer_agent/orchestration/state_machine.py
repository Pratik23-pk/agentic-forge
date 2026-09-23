import json
import logging
import re
from collections.abc import Callable
from dataclasses import fields
from typing import Any

from software_developer_agent.agents.design_director_agent import DesignDirectorAgent
from software_developer_agent.agents.evaluator_agent import EvaluatorAgent
from software_developer_agent.agents.planner_agent import PlannerAgent
from software_developer_agent.agents.workers.backend_developer_agent import BackendDeveloperAgent
from software_developer_agent.agents.workers.database_worker import DatabaseWorker
from software_developer_agent.agents.workers.frontend_developer_agent import FrontendDeveloperAgent
from software_developer_agent.artifacts.file_manifest import (
    WORKER_MANIFEST_JSON_SCHEMA,
    collect_worker_file_manifests,
    extract_worker_file_manifest,
    has_worker_file_specs,
    normalize_worker_manifest,
    validate_worker_manifest_contract,
    validate_worker_manifest_scope,
    worker_file_manifest_json,
)
from software_developer_agent.artifacts.project_generator import (
    ProjectArtifactGenerator,
    refresh_artifact_release_report,
)
from software_developer_agent.artifacts.validation import (
    ArtifactValidationError,
    ProjectValidationReport,
)
from software_developer_agent.config.settings import Settings, get_settings
from software_developer_agent.guardrails.input.acceptable_use import (
    GUARDRAIL_NAME as ACCEPTABLE_USE_GUARDRAIL,
)
from software_developer_agent.guardrails.input.acceptable_use import (
    check_acceptable_use,
    prohibited_use_reason,
)
from software_developer_agent.guardrails.input.prompt_injection import check_prompt_injection
from software_developer_agent.guardrails.input.token_limits import check_input_token_limit
from software_developer_agent.guardrails.output.api_key_detection import scan_api_keys
from software_developer_agent.guardrails.output.dlp_scan import scan_dlp
from software_developer_agent.guardrails.output.vulnerability_scan import scan_vulnerabilities
from software_developer_agent.integrations.llm_client import create_llm_client
from software_developer_agent.memory.langgraph_memory import open_langgraph_resources
from software_developer_agent.memory.manifest_checkpoint import ManifestCheckpointManager
from software_developer_agent.memory.project_context_manager import ProjectContextManager
from software_developer_agent.models.job_state import (
    EvaluationResult,
    GuardrailReport,
    HumanFeedbackDecision,
    JobState,
    JobStatus,
    JobTask,
    ReleaseStatus,
    TaskStatus,
    WorkerKind,
    job_state_from_dict,
)
from software_developer_agent.observability.cost_ledger import GlobalCostLedger
from software_developer_agent.observability.cost_tracker import TokenUsage
from software_developer_agent.observability.metrics import metrics
from software_developer_agent.observability.tracing import trace_span
from software_developer_agent.orchestration.conditional_router import (
    ConditionalRouter,
    RouteAction,
    RouteDecision,
)
from software_developer_agent.orchestration.human_feedback import HumanFeedbackCoordinator
from software_developer_agent.orchestration.loop_count_interceptor import LoopCountInterceptor
from software_developer_agent.orchestration.repair_kernel import (
    CandidateVerification,
    UniversalRepairKernel,
)
from software_developer_agent.orchestration.retry_policy import StrictRetryPolicy
from software_developer_agent.orchestration.workflow_graph import (
    WORKFLOW_NODE_NAMES,
    WorkflowGraphState,
    build_workflow_graph,
)
from software_developer_agent.tools.registry import ToolRegistry

RETRY_CORRECTION_MARKER = "\nValidation failure to correct:\n"
INPUT_GUARDRAIL_NAMES = frozenset(
    {ACCEPTABLE_USE_GUARDRAIL, "input_token_limit", "prompt_injection"}
)
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TERMINAL_MODEL_FAILURE_MARKERS = (
    "cost budget exhausted",
    "insufficient budget for a safe",
    "model-call limit exhausted",
)
logger = logging.getLogger(__name__)
_UNSET = object()


class AgentRuntime:
    """Runs a job through guardrails, planner, workers, evaluator, and router."""

    def __init__(
        self,
        settings: Settings | None = None,
        progress_callback: Callable[[JobState], None] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._progress_callback = progress_callback
        self._active_job: JobState | None = None
        self._cost_ledger = GlobalCostLedger(self._settings)
        self._planner_llm_client = self._create_llm_client(
            "planner", self._settings.openai_planner_model, "medium", 3_500
        )
        self._design_llm_client = self._create_llm_client(
            "design", self._settings.openai_design_model, "high", 1_800
        )
        self._frontend_llm_client = self._create_llm_client(
            "worker.frontend",
            self._settings.openai_frontend_model,
            "medium",
            12_000,
            WORKER_MANIFEST_JSON_SCHEMA,
        )
        self._backend_llm_client = self._create_llm_client(
            "worker.backend",
            self._settings.openai_backend_model,
            "low",
            10_000,
            WORKER_MANIFEST_JSON_SCHEMA,
        )
        self._backend_complex_llm_client = self._create_llm_client(
            "worker.backend",
            self._settings.openai_backend_model,
            "medium",
            16_000,
            WORKER_MANIFEST_JSON_SCHEMA,
        )
        self._database_llm_client = self._create_llm_client(
            "worker.database",
            self._settings.openai_database_model,
            "low",
            7_000,
            WORKER_MANIFEST_JSON_SCHEMA,
        )
        self._repair_standard_llm_clients = {
            worker_kind: self._create_llm_client(
                f"repair.terra.{worker_kind.value}",
                self._settings.openai_repair_standard_model,
                "medium" if worker_kind == WorkerKind.BACKEND else "low",
                6_000,
                WORKER_MANIFEST_JSON_SCHEMA,
            )
            for worker_kind in WorkerKind
        }
        self._repair_final_llm_clients = {
            worker_kind: self._create_llm_client(
                f"repair.sol.{worker_kind.value}",
                self._settings.openai_repair_model,
                "medium",
                8_000,
                WORKER_MANIFEST_JSON_SCHEMA,
            )
            for worker_kind in WorkerKind
        }
        self._evaluator_llm_client = self._create_llm_client(
            "evaluator", self._settings.openai_evaluator_model, "low", 1_400
        )
        self._context_manager = ProjectContextManager(settings=self._settings)
        self._manifest_checkpoints = ManifestCheckpointManager(self._settings)
        self._planner = PlannerAgent(self._settings, self._planner_llm_client)
        self._design_director = DesignDirectorAgent(
            self._settings,
            self._design_llm_client,
        )
        self._evaluator = EvaluatorAgent(self._settings, self._evaluator_llm_client)
        self._loop_interceptor = LoopCountInterceptor(self._settings.max_job_loops)
        retry_policy = StrictRetryPolicy(
            max_worker_attempts=self._settings.max_worker_attempts,
            max_total_attempts=self._settings.max_total_attempts,
        )
        self._router = ConditionalRouter(retry_policy)
        self._artifact_generator = ProjectArtifactGenerator(self._settings)
        self._repair_kernel = UniversalRepairKernel(self._settings)
        tool_registry = ToolRegistry(self._settings)
        self._feedback = HumanFeedbackCoordinator(self._settings, tool_registry)
        self._workers = {
            WorkerKind.DATABASE: DatabaseWorker(
                tool_registry, self._settings, self._database_llm_client
            ),
            WorkerKind.BACKEND: BackendDeveloperAgent(
                tool_registry, self._settings, self._backend_llm_client
            ),
            WorkerKind.FRONTEND: FrontendDeveloperAgent(
                tool_registry, self._settings, self._frontend_llm_client
            ),
        }
        self._complex_backend_worker = BackendDeveloperAgent(
            tool_registry,
            self._settings,
            self._backend_complex_llm_client,
        )
        self._repair_workers_standard = {
            WorkerKind.DATABASE: DatabaseWorker(
                tool_registry,
                self._settings,
                self._repair_standard_llm_clients[WorkerKind.DATABASE],
            ),
            WorkerKind.BACKEND: BackendDeveloperAgent(
                tool_registry,
                self._settings,
                self._repair_standard_llm_clients[WorkerKind.BACKEND],
            ),
            WorkerKind.FRONTEND: FrontendDeveloperAgent(
                tool_registry,
                self._settings,
                self._repair_standard_llm_clients[WorkerKind.FRONTEND],
            ),
        }
        self._repair_workers_final = {
            WorkerKind.DATABASE: DatabaseWorker(
                tool_registry,
                self._settings,
                self._repair_final_llm_clients[WorkerKind.DATABASE],
            ),
            WorkerKind.BACKEND: BackendDeveloperAgent(
                tool_registry,
                self._settings,
                self._repair_final_llm_clients[WorkerKind.BACKEND],
            ),
            WorkerKind.FRONTEND: FrontendDeveloperAgent(
                tool_registry,
                self._settings,
                self._repair_final_llm_clients[WorkerKind.FRONTEND],
            ),
        }

    def _create_llm_client(
        self,
        node_name,
        model,
        reasoning_effort,
        max_output_tokens,
        response_schema=None,
    ):
        return create_llm_client(
            self._settings,
            model=model,
            node_name=node_name,
            reasoning_effort=reasoning_effort,
            max_output_tokens=max_output_tokens,
            response_schema=response_schema,
            budget_authorizer=self._authorize_llm_call,
            usage_recorder=self._record_llm_usage,
        )

    def _authorize_llm_call(
        self,
        node: str,
        model: str,
        estimated_prompt_tokens: int,
        requested_output_tokens: int,
    ) -> int:
        if self._active_job is None:
            return requested_output_tokens
        return self._cost_ledger.authorize(
            self._active_job,
            node=node,
            model=model,
            estimated_prompt_tokens=estimated_prompt_tokens,
            requested_output_tokens=requested_output_tokens,
        )

    def _record_llm_usage(self, node: str, model: str, usage: TokenUsage) -> None:
        if self._active_job is not None:
            self._cost_ledger.record(
                self._active_job,
                node=node,
                model=model,
                usage=usage,
            )

    def apply_human_feedback(
        self,
        job: JobState,
        decision: HumanFeedbackDecision,
        message: str | None = None,
    ) -> None:
        self._feedback.apply_feedback(job, decision, message)

    def set_progress_callback(self, callback: Callable[[JobState], None] | None) -> None:
        self._progress_callback = callback

    def run_to_completion(self, job: JobState) -> RouteDecision:
        self._active_job = job
        self._cost_ledger.initialize(job)
        initial_state: WorkflowGraphState = {
            "job": job.to_dict(),
            "retry_targets": None,
            "repair_registered": False,
            "next_action": "continue",
            "route": None,
            "phase": "start",
        }
        configured_cycles = max(
            self._settings.max_job_loops,
            self._settings.max_total_attempts,
        )
        config = {
            "configurable": {"thread_id": f"{job.job_id}:workflow"},
            "recursion_limit": max(50, (configured_cycles + 3) * 8),
        }
        with (
            trace_span("job.run", settings=self._settings, job_id=job.job_id),
            open_langgraph_resources(self._settings) as (checkpointer, store),
        ):
            graph = build_workflow_graph(self, checkpointer, store)
            final_state = dict(graph.invoke(initial_state, config))

        restored = job_state_from_dict(final_state["job"])
        _sync_job_state(job, restored)
        self._active_job = job
        route_payload = final_state.get("route")
        if not isinstance(route_payload, dict):
            reason = "Workflow graph ended without a route decision."
            if reason not in job.errors:
                job.errors.append(reason)
            job.set_status(JobStatus.FAILED)
            return RouteDecision(RouteAction.FAILURE, reason)
        return _route_from_payload(route_payload)

    @property
    def workflow_node_names(self) -> tuple[str, ...]:
        return WORKFLOW_NODE_NAMES

    def graph_guardrails(self, state: WorkflowGraphState) -> dict[str, Any]:
        job = self._graph_job(state)
        active_feedback = job.active_feedback_request()
        if active_feedback is not None:
            job.set_status(JobStatus.AWAITING_HUMAN_FEEDBACK)
            return self._graph_update(
                job,
                phase="human_feedback",
                route=RouteDecision(RouteAction.HUMAN_FEEDBACK, active_feedback.prompt),
                next_action="end",
            )
        if not self._input_guardrails_completed(job):
            self._run_input_guardrails(job)
        if not self._input_guardrails_passed(job):
            route = self._block_on_input_guardrails(job)
            return self._graph_update(
                job,
                phase="guardrails",
                route=route,
                next_action="end",
            )
        self._manifest_checkpoints.restore(job)
        return self._graph_update(job, phase="guardrails", next_action="continue")

    def graph_plan(self, state: WorkflowGraphState) -> dict[str, Any]:
        job = self._graph_job(state)
        if not job.tasks:
            context = self._context_manager.load_context(job.request.project_id)
            with trace_span(
                "planner.plan",
                settings=self._settings,
                job_id=job.job_id,
                project_id=job.request.project_id,
            ):
                planning = self._planner.create_plan(job.request, context)
                job.tasks = planning.tasks
                job.api_contract = planning.api_contract
                job.request_policy = planning.request_policy.to_dict()
                job.project_spec = planning.project_spec.to_dict()
                job.warnings.extend(
                    warning for warning in planning.warnings if warning not in job.warnings
                )
                self._record_planning_memory(job)
                self._publish_progress(job)
        return self._graph_update(job, phase="planning")

    def graph_design(self, state: WorkflowGraphState) -> dict[str, Any]:
        job = self._graph_job(state)
        if not job.design_spec:
            with trace_span(
                "design.contract",
                settings=self._settings,
                job_id=job.job_id,
                project_id=job.request.project_id,
            ):
                job.design_spec = self._design_director.create_spec(job)
                self._apply_design_spec(job)
                self._publish_progress(job)
        return self._graph_update(job, phase="design")

    def graph_product_approval(self, state: WorkflowGraphState) -> dict[str, Any]:
        job = self._graph_job(state)
        checkpoint = self._feedback.ensure_product_contract(job)
        if checkpoint is not None:
            self._publish_progress(job)
            return self._graph_update(
                job,
                phase="product_approval",
                route=RouteDecision(RouteAction.HUMAN_FEEDBACK, checkpoint.prompt),
                next_action="end",
            )
        return self._graph_update(job, phase="product_approval", next_action="continue")

    def graph_privileged_approval(self, state: WorkflowGraphState) -> dict[str, Any]:
        job = self._graph_job(state)
        checkpoint = self._feedback.ensure_privileged_actions(job)
        if checkpoint is not None:
            self._publish_progress(job)
            return self._graph_update(
                job,
                phase="privileged_approval",
                route=RouteDecision(RouteAction.HUMAN_FEEDBACK, checkpoint.prompt),
                next_action="end",
            )
        return self._graph_update(job, phase="privileged_approval", next_action="continue")

    def graph_execute_workers(self, state: WorkflowGraphState) -> dict[str, Any]:
        job = self._graph_job(state)
        retry_targets = _worker_kinds(state.get("retry_targets"))
        if self._worker_execution_pending(job, retry_targets):
            loop_decision = self._loop_interceptor.enter_loop(job)
            if not loop_decision.allowed:
                return self._graph_update(
                    job,
                    phase="workers",
                    route=RouteDecision(RouteAction.FAILURE, loop_decision.message),
                    next_action="failure",
                )
        job.set_status(JobStatus.RUNNING)
        self._publish_progress(job)
        route = self._run_worker_batch(job, retry_targets)
        if route is not None:
            return self._graph_update(
                job,
                phase="workers",
                route=route,
                next_action=("failure" if route.action == RouteAction.FAILURE else "continue"),
            )
        return self._graph_update(job, phase="workers", next_action="continue")

    def graph_output_guardrails(self, state: WorkflowGraphState) -> dict[str, Any]:
        job = self._graph_job(state)
        with trace_span("guardrails.output", settings=self._settings, job_id=job.job_id):
            self._run_output_guardrails(job)
        job.evaluation = None
        return self._graph_update(
            job,
            phase="output_guardrails",
            repair_registered=False,
        )

    def graph_assemble_validate(self, state: WorkflowGraphState) -> dict[str, Any]:
        job = self._graph_job(state)
        repair_registered = False
        workers_ready = bool(job.tasks) and all(
            task.status == TaskStatus.SUCCEEDED for task in job.tasks
        )
        if (
            self._settings.enable_artifact_generation
            and workers_ready
            and has_worker_file_specs(job)
        ):
            try:
                with trace_span(
                    "artifacts.assemble_validate",
                    settings=self._settings,
                    job_id=job.job_id,
                ):
                    for artifact in self._artifact_generator.generate(job):
                        job.add_artifact(artifact)
                job.artifact_errors = []
                validation_report = self._artifact_validation_report(job)
                if validation_report is not None and validation_report.passed:
                    self._manifest_checkpoints.mark_verified(job, validation_report.to_dict())
                if validation_report is not None and not validation_report.passed:
                    if validation_report.failure_kind == "internal":
                        reason = (
                            validation_report.failure_reason
                            or "Artifact validation failed inside the validator."
                        )
                        job.evaluation = EvaluationResult(
                            passed=False,
                            failure_reason=reason,
                            checks=validation_report.checks,
                            decision="repair_required",
                        )
                    elif (
                        validation_report.failure_kind == "infrastructure"
                        and not _has_current_fallback(job)
                    ):
                        job.evaluation = _infrastructure_validation_warning(validation_report)
                    else:
                        tickets = self._repair_kernel.register_validation_failure(
                            job,
                            validation_report,
                        )
                        self._manifest_checkpoints.rollback_repeated_failure(job, tickets)
                        repair_registered = bool(tickets)
                        job.evaluation = EvaluationResult(
                            passed=False,
                            retry_targets=validation_report.retry_targets,
                            replan_required=not bool(validation_report.retry_targets),
                            failure_reason="; ".join(ticket.summary for ticket in tickets)
                            or validation_report.failure_reason,
                            checks=validation_report.checks,
                            context_pruned=True,
                            decision="repair_required",
                            evidence=[
                                {
                                    "source": "adapter_validation",
                                    "advisories": validation_report.advisories,
                                }
                            ],
                        )
            except ArtifactValidationError as exc:
                report = exc.report
                job.artifact_errors = [str(exc)]
                job.validation_results = [result.to_dict() for result in report.results]
                if report.failure_kind == "infrastructure" and not _has_current_fallback(job):
                    job.evaluation = _infrastructure_validation_warning(report)
                else:
                    tickets = self._repair_kernel.register_validation_failure(job, report)
                    self._manifest_checkpoints.rollback_repeated_failure(job, tickets)
                    repair_registered = bool(tickets)
                    job.evaluation = EvaluationResult(
                        passed=False,
                        retry_targets=report.retry_targets,
                        replan_required=False,
                        failure_reason="; ".join(ticket.summary for ticket in tickets)
                        or report.failure_reason,
                        checks=report.checks,
                        context_pruned=True,
                        decision="repair_required",
                    )
        return self._graph_update(
            job,
            phase="assembly_validation",
            repair_registered=repair_registered,
        )

    def graph_evaluate(self, state: WorkflowGraphState) -> dict[str, Any]:
        job = self._graph_job(state)
        job.set_status(JobStatus.EVALUATING)
        self._publish_progress(job)
        if job.evaluation is None:
            with trace_span("evaluator.evaluate", settings=self._settings, job_id=job.job_id):
                job.evaluation = self._evaluator.evaluate(job)
        return self._graph_update(job, phase="evaluation")

    def graph_route(self, state: WorkflowGraphState) -> dict[str, Any]:
        job = self._graph_job(state)
        if (
            job.evaluation is not None
            and not job.evaluation.passed
            and job.evaluation.retry_targets
            and not state.get("repair_registered", False)
        ):
            tickets = self._repair_kernel.register_evaluation_failure(job, job.evaluation)
            if tickets:
                self._manifest_checkpoints.rollback_repeated_failure(job, tickets)
                job.evaluation.failure_reason = "; ".join(ticket.summary for ticket in tickets)
        route = self._router.route(job)
        if route.action == RouteAction.SUCCESS:
            self._manifest_checkpoints.complete_repair_transaction(job)
            job.resolve_repair_tickets()
            if self._settings.enable_artifact_generation and not job.artifacts:
                with trace_span(
                    "artifacts.generate",
                    settings=self._settings,
                    job_id=job.job_id,
                ):
                    for artifact in self._artifact_generator.generate(job):
                        job.add_artifact(artifact)
            next_action = "success"
        elif route.action == RouteAction.REPLAN:
            next_action = "replan"
        elif route.action == RouteAction.RETRY:
            next_action = "retry"
        else:
            next_action = "failure"
        return self._graph_update(
            job,
            phase="routing",
            route=route,
            retry_targets=[target.value for target in route.retry_targets],
            next_action=next_action,
        )

    def graph_prepare_retry(self, state: WorkflowGraphState) -> dict[str, Any]:
        job = self._graph_job(state)
        retry_targets = _worker_kinds(state.get("retry_targets")) or []
        metrics.increment("retries_scheduled")
        job.set_status(JobStatus.RETRYING)
        self._reset_retry_targets(job, retry_targets)
        self._publish_progress(job)
        return self._graph_update(
            job,
            phase="retry",
            retry_targets=[target.value for target in retry_targets],
            repair_registered=False,
            route=None,
            next_action="continue",
        )

    def graph_replan(self, state: WorkflowGraphState) -> dict[str, Any]:
        job = self._graph_job(state)
        if not self._begin_automatic_replan(job):
            reason = (
                "Automatic replan budget exhausted after "
                f"{self._settings.max_automatic_replans} replans."
            )
            return self._graph_update(
                job,
                phase="replan",
                route=RouteDecision(RouteAction.FAILURE, reason),
                next_action="failure",
            )
        context = self._context_manager.load_context(job.request.project_id)
        with trace_span(
            "planner.replan",
            settings=self._settings,
            job_id=job.job_id,
            project_id=job.request.project_id,
        ):
            planning = self._planner.create_plan(job.request, context)
            job.tasks = planning.tasks
            job.api_contract = planning.api_contract
            job.request_policy = planning.request_policy.to_dict()
            job.project_spec = planning.project_spec.to_dict()
            job.warnings.extend(
                warning for warning in planning.warnings if warning not in job.warnings
            )
            self._record_planning_memory(job)
        job.design_spec = {}
        job.worker_results = []
        self._manifest_checkpoints.reset(job)
        job.artifacts = []
        job.artifact_errors = []
        job.validation_results = []
        job.evaluation = None
        job.set_status(JobStatus.RETRYING)
        return self._graph_update(
            job,
            phase="replan",
            retry_targets=None,
            repair_registered=False,
            route=None,
            next_action="continue",
        )

    def graph_release_approval(self, state: WorkflowGraphState) -> dict[str, Any]:
        job = self._graph_job(state)
        checkpoint = self._feedback.ensure_release(job)
        if checkpoint is not None:
            self._publish_progress(job)
            return self._graph_update(
                job,
                phase="release_approval",
                route=RouteDecision(RouteAction.HUMAN_FEEDBACK, checkpoint.prompt),
                next_action="end",
            )
        return self._graph_update(job, phase="release_approval", next_action="continue")

    def graph_finalize_success(self, state: WorkflowGraphState) -> dict[str, Any]:
        job = self._graph_job(state)
        job.set_status(JobStatus.SUCCEEDED)
        metrics.increment("jobs_succeeded")
        route = _route_from_state(
            state,
            RouteDecision(RouteAction.SUCCESS, "Evaluator passed all checks."),
        )
        return self._graph_update(
            job,
            phase="complete",
            route=route,
            next_action="end",
        )

    def graph_finalize_failure(self, state: WorkflowGraphState) -> dict[str, Any]:
        job = self._graph_job(state)
        route = _route_from_state(
            state,
            RouteDecision(RouteAction.FAILURE, "Workflow graph failed without a route reason."),
        )
        self._restore_last_verified_artifact(job)
        self._quarantine_runnable_artifacts(job, route.reason)
        if route.reason not in job.errors:
            job.errors.append(route.reason)
        job.set_status(JobStatus.FAILED)
        metrics.increment("jobs_failed")
        return self._graph_update(
            job,
            phase="failed",
            route=route,
            next_action="end",
        )

    def _graph_job(self, state: WorkflowGraphState) -> JobState:
        job = job_state_from_dict(state["job"])
        self._active_job = job
        return job

    @staticmethod
    def _graph_update(
        job: JobState,
        *,
        phase: str,
        route: RouteDecision | None | object = _UNSET,
        next_action: str | None = None,
        retry_targets: list[str] | None | object = _UNSET,
        repair_registered: bool | None = None,
    ) -> dict[str, Any]:
        update: dict[str, Any] = {"job": job.to_dict(), "phase": phase}
        if route is not _UNSET:
            update["route"] = _route_payload(route) if isinstance(route, RouteDecision) else None
        if next_action is not None:
            update["next_action"] = next_action
        if retry_targets is not _UNSET:
            update["retry_targets"] = retry_targets
        if repair_registered is not None:
            update["repair_registered"] = repair_registered
        return update

    def _run_input_guardrails(self, job: JobState) -> bool:
        with trace_span("guardrails.input", settings=self._settings, job_id=job.job_id):
            reports = [
                check_acceptable_use(job.request.prompt),
                check_input_token_limit(job.request.prompt, self._settings.max_input_tokens),
                check_prompt_injection(job.request.prompt),
            ]
        for report in reports:
            job.add_guardrail_report(report)
        return all(report.passed for report in reports)

    def _block_on_input_guardrails(self, job: JobState) -> RouteDecision:
        reason = _input_guardrail_failure_reason(job)
        if reason not in job.errors:
            job.errors.append(reason)
        job.set_status(JobStatus.BLOCKED)
        metrics.increment("guardrail_blocks")
        if _prohibited_use_blocked(job):
            metrics.increment("prohibited_requests")
        return RouteDecision(RouteAction.FAILURE, reason)

    def _record_planning_memory(self, job: JobState) -> None:
        capability = str(job.project_spec.get("capability_id", "unknown"))
        application_type = str(job.project_spec.get("application_type", "unknown"))
        exclusions = [str(item) for item in job.request_policy.get("excluded_capabilities", [])]
        self._context_manager.record_plan(
            job.request.project_id,
            summary=job.request.prompt,
            decisions=[f"capability:{capability}", f"application_type:{application_type}"],
            constraints=[f"excluded:{item}" for item in exclusions],
        )

    @staticmethod
    def _input_guardrails_completed(job: JobState) -> bool:
        names = {report.name for report in job.guardrail_reports}
        return INPUT_GUARDRAIL_NAMES.issubset(names)

    @staticmethod
    def _input_guardrails_passed(job: JobState) -> bool:
        reports = _input_guardrail_reports(job)
        return bool(reports) and all(report.passed for report in reports)

    def _run_output_guardrails(self, job: JobState) -> bool:
        files = [file for manifest in collect_worker_file_manifests(job) for file in manifest.files]
        output = "\n\n".join(file.content for file in files)
        runtime_output = "\n\n".join(
            file.content for file in files if _is_runtime_security_path(file.path)
        )
        reports = [
            scan_dlp(runtime_output),
            scan_api_keys(output),
            scan_vulnerabilities(runtime_output),
        ]
        for report in reports:
            job.add_guardrail_report(report)
        return all(report.passed for report in reports)

    def _run_worker_batch(
        self,
        job: JobState,
        targets: list[WorkerKind] | None,
    ) -> RouteDecision | None:
        target_set = set(targets or [])
        if targets is not None:
            self._manifest_checkpoints.begin_repair_transaction(job, target_set)
        execution_order = {
            WorkerKind.DATABASE: 0,
            WorkerKind.BACKEND: 1,
            WorkerKind.FRONTEND: 2,
        }
        for task in sorted(job.tasks, key=lambda item: execution_order[item.worker_kind]):
            should_run_initial = targets is None and task.status == TaskStatus.PENDING
            should_run_retry = targets is not None and task.worker_kind in target_set
            if not should_run_initial and not should_run_retry:
                continue
            if task.attempt >= task.max_attempts:
                return RouteDecision(
                    RouteAction.FAILURE,
                    f"Retry budget exhausted for {task.worker_kind.value}.",
                )

            task.retry_context = (
                self._manifest_checkpoints.repair_context(job, task)
                if should_run_retry
                else self._manifest_checkpoints.upstream_generation_context(job, task)
            )
            worker = self._workers[task.worker_kind]
            if (
                targets is None
                and task.worker_kind == WorkerKind.BACKEND
                and self._complex_backend_reasoning_is_justified(task)
            ):
                worker = self._complex_backend_worker
            strategy = self._repair_kernel.active_strategy(job, task.worker_kind)
            if should_run_retry and self._settings.enable_llm_calls:
                if strategy == "final_patch":
                    repair_pool = (
                        self._repair_workers_final
                        if self._premium_repair_is_justified(job, task)
                        else self._repair_workers_standard
                    )
                    worker = repair_pool[task.worker_kind]
                else:
                    worker = self._repair_workers_standard[task.worker_kind]
            task.status = TaskStatus.RUNNING
            self._publish_progress(job)
            with trace_span(
                "worker.run",
                settings=self._settings,
                job_id=job.job_id,
                worker_kind=task.worker_kind.value,
                task_id=task.task_id,
                attempt=task.attempt + 1,
            ):
                previous_attempt = task.attempt
                result = worker.run(task)
            if result.status == TaskStatus.SUCCEEDED:
                manifest = extract_worker_file_manifest(result.output, task.worker_kind)
                try:
                    manifest = normalize_worker_manifest(manifest, task.capability_id)
                    validate_worker_manifest_scope(manifest)
                    if previous_attempt == 0 and manifest.operation == "patch":
                        raise ValueError(
                            "Initial candidate must be a complete replacement manifest."
                        )
                    validate_worker_manifest_contract(manifest, task.capability_id)
                    verification = self._repair_kernel.verify_candidate(job, task, manifest)
                except ValueError as exc:
                    verification = CandidateVerification(
                        False,
                        f"Worker candidate contract rejected: {exc}",
                    )
                if not verification.accepted:
                    task.attempt = previous_attempt
                    task.repair_rejections += 1
                    task.status = TaskStatus.FAILED
                    result.status = TaskStatus.FAILED
                    result.summary = f"{task.worker_kind.value} repair candidate rejected."
                    result.errors.append(verification.reason)
                    result.attempt = previous_attempt
                else:
                    task.attempt = previous_attempt + 1
                    task.status = TaskStatus.SUCCEEDED
                    canonical = self._manifest_checkpoints.commit(job, task, manifest)
                    result.output = worker_file_manifest_json(canonical)
                    result.artifacts = [file.path for file in canonical.files]
                    result.attempt = task.attempt
            else:
                task.attempt = previous_attempt
                result.attempt = previous_attempt
            task.retry_context = None
            job.add_worker_result(result)
            if result.status != TaskStatus.SUCCEEDED and _terminal_model_failure(result.errors):
                terminal_error = next(
                    error
                    for error in reversed(result.errors)
                    if any(marker in error.lower() for marker in TERMINAL_MODEL_FAILURE_MARKERS)
                )
                return RouteDecision(
                    RouteAction.FAILURE,
                    _terminal_failure_reason(job, task, terminal_error),
                )
            if result.used_fallback:
                warning = (
                    f"{task.worker_kind.value.title()} generation used a certified runnable "
                    "checkpoint after the model response failed. A targeted repair was scheduled."
                )
                if warning not in job.warnings:
                    job.warnings.append(warning)
            self._publish_progress(job)
        return None

    def _publish_progress(self, job: JobState) -> None:
        if self._progress_callback is None:
            return
        try:
            self._progress_callback(job)
        except Exception:
            logger.warning("job.progress_checkpoint_failed", exc_info=True)

    def _begin_automatic_replan(self, job: JobState) -> bool:
        completed = int(job.approval_state.get("automatic_replans", 0))
        if completed >= self._settings.max_automatic_replans:
            return False
        job.approval_state["automatic_replans"] = completed + 1
        job.loop_count = 0
        job.touch()
        return True

    @staticmethod
    def _premium_repair_is_justified(job: JobState, task: JobTask) -> bool:
        ticket = job.active_repair_ticket(task.worker_kind)
        if ticket is None:
            return False
        premium_node = f"repair.sol.{task.worker_kind.value}"
        if any(
            call.get("node") == premium_node
            for call in job.cost_ledger.get("calls", [])
            if isinstance(call, dict)
        ):
            return False
        return (
            task.repair_rejections >= 2
            or ticket.category == "requirement_gap"
            or ticket.occurrence >= 2
            or ticket.strategy == "final_patch"
            and task.worker_kind == WorkerKind.BACKEND
            and AgentRuntime._complex_backend_reasoning_is_justified(task)
        )

    @staticmethod
    def _complex_backend_reasoning_is_justified(task: JobTask) -> bool:
        complex_domains = {
            "auth-rbac",
            "commerce",
            "file-upload",
            "multi-tenant",
            "realtime",
            "scheduling",
            "video-platform",
        }
        return len(complex_domains.intersection(task.adapter_ids)) >= 2

    @staticmethod
    def _apply_design_spec(job: JobState) -> None:
        if not job.design_spec:
            return
        design_contract = json.dumps(job.design_spec, sort_keys=True)
        marker = "\nVisual product contract:\n"
        for task in job.tasks:
            if task.worker_kind != WorkerKind.FRONTEND or marker in task.instructions:
                continue
            task.instructions += marker + design_contract
        job.touch()

    @staticmethod
    def _artifact_validation_report(job: JobState) -> ProjectValidationReport | None:
        folder = next(
            (artifact for artifact in job.artifacts if artifact.kind == "folder"),
            None,
        )
        if folder is None:
            return None
        payload = folder.metadata.get("validation")
        if not isinstance(payload, dict):
            return None
        return ProjectValidationReport.from_dict(payload)

    def _quarantine_runnable_artifacts(self, job: JobState, reason: str) -> None:
        if not job.artifacts:
            return
        validation = AgentRuntime._artifact_validation_report(job)
        if validation is None or not validation.passed:
            return
        job.release_status = ReleaseStatus.QUARANTINED
        finding = {
            "source": "evaluator",
            "name": "semantic_release_gate",
            "severity": "high",
            "message": reason,
            "blocking": True,
            "publish_allowed": False,
        }
        if finding not in job.risk_findings:
            job.risk_findings.append(finding)
        for artifact in job.artifacts:
            artifact.metadata["release_status"] = ReleaseStatus.QUARANTINED.value
            artifact.metadata["publish_allowed"] = False
            artifact.metadata["semantic_failure"] = reason
            artifact.metadata["risk_findings"] = list(job.risk_findings)
        try:
            refresh_artifact_release_report(job, self._settings)
        except (OSError, ValueError) as exc:
            job.errors.append(f"Could not refresh quarantined artifact report: {exc}")
        job.touch()

    def _restore_last_verified_artifact(self, job: JobState) -> bool:
        validation = self._artifact_validation_report(job)
        if validation is not None and validation.passed:
            return False
        if not self._manifest_checkpoints.restore_verified(job):
            return False
        try:
            restored = self._artifact_generator.generate(job)
        except (ArtifactValidationError, OSError, RuntimeError, TypeError, ValueError):
            logger.warning("job.verified_checkpoint_restore_failed", exc_info=True)
            return False
        restored_validation = next(
            (
                ProjectValidationReport.from_dict(artifact.metadata["validation"])
                for artifact in restored
                if artifact.kind == "folder"
                and isinstance(artifact.metadata.get("validation"), dict)
            ),
            None,
        )
        if restored_validation is None or not restored_validation.passed:
            return False
        job.artifacts = []
        for artifact in restored:
            job.add_artifact(artifact)
        job.artifact_errors = []
        job.validation_results = [result.to_dict() for result in restored_validation.results]
        job.errors.append(
            "The final repair was rejected; the last executable checkpoint was restored "
            "without consuming another worker attempt."
        )
        return True

    @staticmethod
    def _worker_execution_pending(
        job: JobState,
        targets: list[WorkerKind] | None,
    ) -> bool:
        if targets is not None:
            target_set = set(targets)
            return any(task.worker_kind in target_set for task in job.tasks)
        return any(task.status == TaskStatus.PENDING for task in job.tasks)

    @staticmethod
    def _reset_retry_targets(job: JobState, targets: list[WorkerKind]) -> None:
        target_set = set(targets)
        failure_reason = (
            job.evaluation.failure_reason
            if job.evaluation and job.evaluation.failure_reason
            else "Previous output failed validation."
        )
        for task in job.tasks:
            if task.worker_kind in target_set:
                task.status = TaskStatus.PENDING
                base_instructions = task.instructions.split(
                    RETRY_CORRECTION_MARKER,
                    maxsplit=1,
                )[0]
                task.instructions = (
                    base_instructions
                    + RETRY_CORRECTION_MARKER
                    + _retry_failure_context(failure_reason)
                )
        job.touch()


def _sync_job_state(target: JobState, source: JobState) -> None:
    for field in fields(JobState):
        setattr(target, field.name, getattr(source, field.name))


def _route_payload(route: RouteDecision) -> dict[str, Any]:
    return {
        "action": route.action.value,
        "reason": route.reason,
        "retry_targets": [target.value for target in route.retry_targets],
    }


def _route_from_payload(payload: dict[str, Any]) -> RouteDecision:
    return RouteDecision(
        action=RouteAction(str(payload["action"])),
        reason=str(payload.get("reason", "")),
        retry_targets=_worker_kinds(payload.get("retry_targets")) or [],
    )


def _route_from_state(
    state: WorkflowGraphState,
    fallback: RouteDecision,
) -> RouteDecision:
    payload = state.get("route")
    if not isinstance(payload, dict):
        return fallback
    return _route_from_payload(payload)


def _worker_kinds(values: list[str] | None) -> list[WorkerKind] | None:
    if values is None:
        return None
    return [WorkerKind(value) for value in values]


def _input_guardrail_reports(job: JobState) -> list[GuardrailReport]:
    return [report for report in job.guardrail_reports if report.name in INPUT_GUARDRAIL_NAMES]


def _prohibited_use_blocked(job: JobState) -> bool:
    return any(
        report.name == ACCEPTABLE_USE_GUARDRAIL and not report.passed
        for report in job.guardrail_reports
    )


def _input_guardrail_failure_reason(job: JobState) -> str:
    for report in _input_guardrail_reports(job):
        if report.name != ACCEPTABLE_USE_GUARDRAIL or report.passed:
            continue
        reason = prohibited_use_reason(report)
        if reason:
            return reason
    messages = [
        finding.message
        for report in _input_guardrail_reports(job)
        if not report.passed
        for finding in report.failed_findings
    ]
    return "; ".join(dict.fromkeys(messages)) or "Input guardrails blocked the job."


def _retry_failure_context(failure_reason: str, limit: int = 2_000) -> str:
    cleaned = ANSI_ESCAPE_PATTERN.sub("", failure_reason).strip()
    if len(cleaned) <= limit:
        return cleaned
    head_limit = (limit * 3) // 5
    tail_limit = limit - head_limit
    return f"{cleaned[:head_limit]}\n...[truncated]...\n{cleaned[-tail_limit:]}"


def _terminal_failure_reason(job: JobState, task: JobTask, terminal_error: str) -> str:
    """Name the unresolved defect when a budget or call ceiling ends the job.

    A bare ceiling message tells an operator which limit tripped but never why the
    repair loop failed to converge, which is the only actionable part.
    """

    ticket = job.active_repair_ticket(task.worker_kind)
    if ticket is None:
        return terminal_error
    return (
        f"{terminal_error} The {task.worker_kind.value} worker stopped with an unresolved "
        f"{ticket.category} repair after {task.attempt} accepted attempt(s) and "
        f"{task.repair_rejections} rejected candidate(s). Outstanding defect: "
        f"{ticket.summary[:600]}"
    )


def _terminal_model_failure(errors: list[str]) -> bool:
    return any(
        marker in error.lower() for error in errors for marker in TERMINAL_MODEL_FAILURE_MARKERS
    )


def _infrastructure_validation_warning(
    report: ProjectValidationReport,
) -> EvaluationResult:
    message = report.failure_reason or (
        "Executable validation could not complete because validation infrastructure was unavailable."
    )
    return EvaluationResult(
        passed=True,
        retry_targets=[],
        replan_required=False,
        failure_reason=None,
        checks=[*report.checks, "infrastructure_failure:no_worker_retry"],
        context_pruned=True,
        decision="warning",
        warnings=[message],
        evidence=[
            {
                "source": "validation_infrastructure",
                "failure_kind": "infrastructure",
                "worker_attempt_consumed": False,
                "advisories": report.advisories,
            }
        ],
    )


def _is_runtime_security_path(path: str) -> bool:
    normalized = path.lower()
    name = normalized.rsplit("/", maxsplit=1)[-1]
    return not (
        normalized.startswith(("artifacts/", "docs/"))
        or normalized == "readme.md"
        or "/tests/" in f"/{normalized}"
        or "/test/" in f"/{normalized}"
        or "/fixtures/" in f"/{normalized}"
        or name.startswith(("seed.", "fixture."))
        or name.startswith("test_")
        and name.endswith(".py")
        or name.endswith("_test.py")
        or any(marker in name for marker in (".test.", ".spec.", "_test."))
    )


def _has_current_fallback(job: JobState) -> bool:
    return any(
        result.used_fallback
        and result.status == TaskStatus.SUCCEEDED
        and result.attempt == task.attempt
        for task in job.tasks
        for result in reversed(job.worker_results)
        if result.task_id == task.task_id
    )
