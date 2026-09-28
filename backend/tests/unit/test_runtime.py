import json
import zipfile
from pathlib import Path
from unittest.mock import Mock

from software_developer_agent.artifacts.file_manifest import (
    GeneratedFileSpec,
    WorkerFileManifest,
    collect_worker_file_specs,
)
from software_developer_agent.artifacts.validation import (
    ArtifactValidationError,
    ProjectValidationReport,
    ValidationCommandResult,
)
from software_developer_agent.config.settings import Settings
from software_developer_agent.guardrails.release_policy import publication_allowed
from software_developer_agent.memory.langgraph_memory import open_langgraph_resources
from software_developer_agent.models.job_state import (
    ApprovalGate,
    EvaluationResult,
    HumanFeedbackDecision,
    JobArtifact,
    JobRequest,
    JobState,
    JobStatus,
    JobTask,
    ReleaseStatus,
    TaskStatus,
    WorkerKind,
    WorkerResult,
)
from software_developer_agent.orchestration.conditional_router import RouteAction
from software_developer_agent.orchestration.loop_count_interceptor import LoopCountInterceptor
from software_developer_agent.orchestration.state_machine import (
    RETRY_CORRECTION_MARKER,
    AgentRuntime,
)
from software_developer_agent.orchestration.workflow_graph import build_workflow_graph


def test_repair_model_call_limits_are_isolated_per_worker() -> None:
    runtime = AgentRuntime(
        Settings(
            app_env="test",
            enable_llm_calls=True,
            openai_api_key="test-key",
            enable_human_checkpoints=False,
        )
    )

    assert {
        worker_kind: worker._llm_client._node_name
        for worker_kind, worker in runtime._repair_workers_standard.items()
    } == {
        WorkerKind.DATABASE: "repair.terra.database",
        WorkerKind.BACKEND: "repair.terra.backend",
        WorkerKind.FRONTEND: "repair.terra.frontend",
    }


def test_complex_backend_worker_has_full_manifest_output_capacity() -> None:
    runtime = AgentRuntime(
        Settings(
            app_env="test",
            enable_llm_calls=True,
            openai_api_key="test-key",
            enable_human_checkpoints=False,
        )
    )

    assert runtime._planner_llm_client._max_output_tokens == 3_500
    assert runtime._backend_llm_client._max_output_tokens == 10_000
    assert runtime._backend_complex_llm_client._max_output_tokens == 16_000
    assert runtime._repair_standard_llm_clients[WorkerKind.BACKEND]._reasoning_effort == "medium"


def test_runtime_completes_backend_job() -> None:
    settings = Settings(
        app_env="test",
        enable_llm_calls=False,
        enable_human_checkpoints=False,
        max_worker_attempts=2,
        max_total_attempts=4,
    )
    runtime = AgentRuntime(settings=settings)
    job = JobState(request=JobRequest(prompt="Build a backend API route"))

    route = runtime.run_to_completion(job)

    assert job.status == JobStatus.SUCCEEDED
    assert route.action == "success"
    assert job.tasks[0].worker_kind == WorkerKind.BACKEND


def test_runtime_compiles_complete_parent_workflow_graph() -> None:
    settings = Settings(
        app_env="test",
        enable_llm_calls=False,
        enable_human_checkpoints=False,
    )
    runtime = AgentRuntime(settings=settings)

    with open_langgraph_resources(settings) as (checkpointer, store):
        graph = build_workflow_graph(runtime, checkpointer, store)
        graph_nodes = set(graph.get_graph().nodes)

    assert graph_nodes == {"__start__", "__end__", *runtime.workflow_node_names}


def test_runtime_persists_parent_workflow_checkpoint() -> None:
    settings = Settings(
        app_env="test",
        enable_llm_calls=False,
        enable_human_checkpoints=False,
    )
    runtime = AgentRuntime(settings=settings)
    job = JobState(request=JobRequest(prompt="Build a backend API route"))

    route = runtime.run_to_completion(job)

    config = {"configurable": {"thread_id": f"{job.job_id}:workflow"}}
    with open_langgraph_resources(settings) as (checkpointer, _):
        checkpoint = checkpointer.get_tuple(config)
    assert route.action == RouteAction.SUCCESS
    assert checkpoint is not None
    channel_values = checkpoint.checkpoint["channel_values"]
    assert channel_values["phase"] == "complete"
    assert channel_values["job"]["status"] == JobStatus.SUCCEEDED.value


def test_runtime_pauses_and_resumes_for_human_feedback() -> None:
    settings = Settings(
        app_env="test",
        enable_llm_calls=False,
        enable_human_checkpoints=True,
        max_human_checkpoints=2,
        max_worker_attempts=2,
        max_total_attempts=4,
    )
    runtime = AgentRuntime(settings=settings)
    job = JobState(request=JobRequest(prompt="Build a frontend dashboard"))

    first_route = runtime.run_to_completion(job)

    assert first_route.action == RouteAction.HUMAN_FEEDBACK
    assert job.status == JobStatus.AWAITING_HUMAN_FEEDBACK
    assert job.active_feedback_request() is not None
    assert job.active_feedback_request().gate == ApprovalGate.PRODUCT_CONTRACT
    assert job.loop_count == 0

    runtime.apply_human_feedback(job, HumanFeedbackDecision.APPROVE, "Looks aligned.")
    second_route = runtime.run_to_completion(job)

    assert second_route.action == RouteAction.HUMAN_FEEDBACK
    assert job.active_feedback_request() is not None
    assert job.active_feedback_request().gate == ApprovalGate.RELEASE
    assert job.loop_count == 1

    runtime.apply_human_feedback(job, HumanFeedbackDecision.APPROVE, "Release it.")
    third_route = runtime.run_to_completion(job)

    assert third_route.action == RouteAction.SUCCESS
    assert job.status == JobStatus.SUCCEEDED
    assert job.loop_count == 1


def test_human_checkpoints_are_not_published_before_graph_quiescence() -> None:
    settings = Settings(
        app_env="test",
        enable_llm_calls=False,
        enable_human_checkpoints=True,
        max_human_checkpoints=2,
        max_worker_attempts=2,
        max_total_attempts=4,
    )
    runtime = AgentRuntime(settings=settings)
    job = JobState(request=JobRequest(prompt="Build a frontend dashboard"))
    progress: list[dict] = []
    runtime.set_progress_callback(lambda current: progress.append(current.to_dict()))

    runtime.run_to_completion(job)

    assert job.active_feedback_request() is not None
    assert job.active_feedback_request().gate == ApprovalGate.PRODUCT_CONTRACT
    assert all(snapshot["active_feedback_request_id"] is None for snapshot in progress)

    runtime.apply_human_feedback(job, HumanFeedbackDecision.APPROVE)
    progress.clear()
    runtime.run_to_completion(job)

    assert job.active_feedback_request() is not None
    assert job.active_feedback_request().gate == ApprovalGate.RELEASE
    assert all(snapshot["active_feedback_request_id"] is None for snapshot in progress)


def test_release_approval_resumes_at_finalization_without_re_evaluation() -> None:
    settings = Settings(
        app_env="test",
        enable_llm_calls=False,
        enable_human_checkpoints=True,
        max_human_checkpoints=2,
    )
    runtime = AgentRuntime(settings=settings)
    original_evaluate = runtime._evaluator.evaluate
    runtime._evaluator.evaluate = Mock(wraps=original_evaluate)
    job = JobState(request=JobRequest(prompt="Build a frontend dashboard"))

    runtime.run_to_completion(job)
    runtime.apply_human_feedback(job, HumanFeedbackDecision.APPROVE)
    runtime.run_to_completion(job)
    assert runtime._evaluator.evaluate.call_count == 1

    runtime.apply_human_feedback(job, HumanFeedbackDecision.APPROVE)
    job.release_status = ReleaseStatus.QUARANTINED
    job.evaluation = EvaluationResult(
        passed=False,
        retry_targets=[WorkerKind.FRONTEND],
        failure_reason="Stale replay result must not replace the approved release.",
    )
    job.errors.append("Stale replay failure.")
    route = runtime.run_to_completion(job)

    assert route.action == RouteAction.SUCCESS
    assert job.status == JobStatus.SUCCEEDED
    assert job.release_status == ReleaseStatus.VERIFIED
    assert job.evaluation is not None and job.evaluation.passed
    assert job.errors == []
    assert runtime._evaluator.evaluate.call_count == 1


def test_automatic_replan_has_separate_single_use_budget() -> None:
    runtime = AgentRuntime(
        Settings(
            app_env="test",
            enable_persistence=False,
            enable_llm_calls=False,
            max_automatic_replans=1,
        )
    )
    job = JobState(request=JobRequest(prompt="Build a dashboard"), loop_count=5)

    assert runtime._begin_automatic_replan(job)
    assert job.loop_count == 0
    assert job.approval_state["automatic_replans"] == 1
    assert not runtime._begin_automatic_replan(job)


def test_runtime_adds_conditional_privileged_action_gate() -> None:
    settings = Settings(
        app_env="test",
        enable_llm_calls=False,
        enable_human_checkpoints=True,
        max_human_checkpoints=3,
        max_worker_attempts=2,
        max_total_attempts=4,
    )
    runtime = AgentRuntime(settings=settings)
    job = JobState(
        request=JobRequest(prompt="Build a React website and push it to GitHub after validation.")
    )

    runtime.run_to_completion(job)
    runtime.apply_human_feedback(job, HumanFeedbackDecision.APPROVE)
    route = runtime.run_to_completion(job)

    assert route.action == RouteAction.HUMAN_FEEDBACK
    assert job.active_feedback_request() is not None
    assert job.active_feedback_request().gate == ApprovalGate.PRIVILEGED_ACTION
    assert job.loop_count == 0


def test_runtime_preserves_certified_fallback_as_quarantined_artifact(tmp_path) -> None:
    settings = Settings(
        app_env="development",
        enable_persistence=False,
        enable_llm_calls=False,
        enable_human_checkpoints=False,
        artifacts_dir=tmp_path / "artifacts",
        generated_projects_dir=tmp_path / "generated",
        max_worker_attempts=1,
        max_total_attempts=2,
    )
    runtime = AgentRuntime(settings=settings)
    job = JobState(request=JobRequest(prompt="Build a backend API route"))

    route = runtime.run_to_completion(job)

    assert route.action == RouteAction.FAILURE
    assert job.status == JobStatus.FAILED
    assert job.release_status in {ReleaseStatus.PROVISIONAL, ReleaseStatus.QUARANTINED}
    assert any(artifact.kind == "folder" for artifact in job.artifacts)
    assert any(result.used_fallback for result in job.worker_results)
    assert job.warnings


def test_runtime_does_not_assemble_partial_worker_output(tmp_path) -> None:
    class FailedFrontendWorker:
        @staticmethod
        def run(task):
            task.attempt += 1
            task.status = TaskStatus.FAILED
            return WorkerResult(
                task_id=task.task_id,
                worker_kind=WorkerKind.FRONTEND,
                status=TaskStatus.FAILED,
                summary="frontend worker failed",
                errors=["Request timed out."],
                attempt=task.attempt,
            )

    settings = Settings(
        app_env="test",
        enable_llm_calls=False,
        enable_human_checkpoints=False,
        artifacts_dir=tmp_path / "artifacts",
        generated_projects_dir=tmp_path / "generated",
        max_worker_attempts=1,
        max_total_attempts=2,
    )
    runtime = AgentRuntime(settings=settings)
    runtime._workers[WorkerKind.FRONTEND] = FailedFrontendWorker()
    job = JobState(request=JobRequest(prompt="Build a full-stack game webapp"))

    route = runtime.run_to_completion(job)

    assert route.action == RouteAction.FAILURE
    assert job.status == JobStatus.FAILED
    assert job.artifacts == []
    assert not (tmp_path / "generated").exists()


def test_runtime_does_not_charge_manifest_recovery_to_worker_attempt(tmp_path) -> None:
    class MalformedFrontendWorker:
        @staticmethod
        def run(task):
            task.status = TaskStatus.FAILED
            return WorkerResult(
                task_id=task.task_id,
                worker_kind=WorkerKind.FRONTEND,
                status=TaskStatus.FAILED,
                summary="frontend manifest remained invalid",
                errors=["Worker did not return a valid file manifest."],
                attempt=task.attempt + 1,
            )

    settings = Settings(
        app_env="test",
        enable_llm_calls=False,
        enable_human_checkpoints=False,
        artifacts_dir=tmp_path / "artifacts",
        generated_projects_dir=tmp_path / "generated",
        max_worker_attempts=1,
        max_total_attempts=2,
        max_job_loops=2,
    )
    runtime = AgentRuntime(settings=settings)
    runtime._workers[WorkerKind.FRONTEND] = MalformedFrontendWorker()
    job = JobState(request=JobRequest(prompt="Build a frontend gallery"))

    route = runtime.run_to_completion(job)

    assert route.action == RouteAction.FAILURE
    assert job.tasks[0].attempt == 0
    assert job.loop_count == 3
    assert "max loop count of 2" in route.reason


def test_terminal_model_budget_failure_stops_without_looping(tmp_path) -> None:
    class BudgetExhaustedFrontendWorker:
        @staticmethod
        def run(task):
            task.status = TaskStatus.FAILED
            return WorkerResult(
                task_id=task.task_id,
                worker_kind=WorkerKind.FRONTEND,
                status=TaskStatus.FAILED,
                summary="frontend worker could not start",
                errors=["Cost budget exhausted before repair.sol; spent $0.98 of $1.00."],
                attempt=task.attempt,
            )

    settings = Settings(
        app_env="test",
        enable_llm_calls=False,
        enable_human_checkpoints=False,
        artifacts_dir=tmp_path / "artifacts",
        generated_projects_dir=tmp_path / "generated",
        max_worker_attempts=4,
        max_total_attempts=8,
        max_job_loops=12,
    )
    runtime = AgentRuntime(settings=settings)
    runtime._workers[WorkerKind.FRONTEND] = BudgetExhaustedFrontendWorker()
    job = JobState(request=JobRequest(prompt="Build a frontend gallery"))

    route = runtime.run_to_completion(job)

    assert route.action == RouteAction.FAILURE
    assert "Cost budget exhausted" in route.reason
    assert job.loop_count == 1


def test_rejected_candidate_does_not_consume_global_loop_budget() -> None:
    job = JobState(request=JobRequest(prompt="Build a frontend"))
    job.tasks = [
        JobTask(
            worker_kind=WorkerKind.FRONTEND,
            title="Frontend",
            instructions="Build frontend.",
            repair_rejections=1,
        )
    ]
    interceptor = LoopCountInterceptor(max_loops=1)

    assert interceptor.enter_loop(job).allowed
    assert interceptor.enter_loop(job).allowed
    assert not interceptor.enter_loop(job).allowed


def test_runtime_retry_merges_partial_manifest_before_packaging() -> None:
    class RepairingFrontendWorker:
        saw_complete_retry_context = False

        @staticmethod
        def run(task):
            if task.attempt == 1:
                retry_state = json.loads(task.retry_context)
                paths = {file["path"] for file in retry_state["files"]}
                assert "frontend/src/App.tsx" in paths
                assert "frontend/src/App.test.tsx" in paths
                RepairingFrontendWorker.saw_complete_retry_context = True
            task.attempt += 1
            task.status = TaskStatus.SUCCEEDED
            if task.attempt == 1:
                files = [
                    {"path": "frontend/index.html", "content": '<div id="root"></div>\n'},
                    {"path": "frontend/src/main.tsx", "content": "import './App';\n"},
                    {
                        "path": "frontend/src/App.tsx",
                        "content": "export function App() { return <main />; }\n",
                    },
                    {"path": "frontend/src/App.test.tsx", "content": "export {};\n"},
                ]
                operation = "replace"
            else:
                files = [
                    {
                        "path": "frontend/src/theme.css",
                        "content": ":root { color-scheme: dark; }\n",
                    }
                ]
                operation = "patch"
            return WorkerResult(
                task_id=task.task_id,
                worker_kind=WorkerKind.FRONTEND,
                status=TaskStatus.SUCCEEDED,
                summary=f"attempt {task.attempt}",
                output=json.dumps(
                    {
                        "summary": f"attempt {task.attempt}",
                        "operation": operation,
                        "files": files,
                        "deleted_files": [],
                    }
                ),
                attempt=task.attempt,
            )

    class PackagingGate:
        attempts = 0

        def generate(self, job):
            self.attempts += 1
            paths = {file.path for file in collect_worker_file_specs(job)}
            if "frontend/src/theme.css" not in paths:
                raise ArtifactValidationError(
                    ProjectValidationReport(
                        passed=False,
                        retry_targets=[WorkerKind.FRONTEND],
                        failure_reason="Required frontend/src/theme.css is missing.",
                    )
                )
            assert "frontend/package.json" in paths
            assert "frontend/src/App.tsx" in paths
            assert "frontend/src/App.test.tsx" in paths
            metadata = {"validation": {"passed": True, "results": []}}
            return [
                JobArtifact(
                    "project-folder",
                    "folder",
                    "demo",
                    "/tmp/demo",
                    "/files",
                    metadata,
                ),
                JobArtifact(
                    "project-zip",
                    "zip",
                    "demo.zip",
                    "/tmp/demo.zip",
                    "/download",
                    metadata,
                ),
            ]

    settings = Settings(
        app_env="test",
        enable_persistence=False,
        enable_llm_calls=False,
        enable_human_checkpoints=False,
        max_job_loops=3,
        max_worker_attempts=3,
        max_total_attempts=4,
    )
    runtime = AgentRuntime(settings=settings)
    runtime._workers[WorkerKind.FRONTEND] = RepairingFrontendWorker()
    packaging_gate = PackagingGate()
    runtime._artifact_generator = packaging_gate
    job = JobState(request=JobRequest(prompt="Build a React frontend"))

    route = runtime.run_to_completion(job)

    assert route.action == RouteAction.SUCCESS
    assert job.status == JobStatus.SUCCEEDED
    assert job.loop_count == 2
    assert packaging_gate.attempts == 2
    assert len(job.worker_results) == 2
    assert RepairingFrontendWorker.saw_complete_retry_context


def test_parent_graph_allows_complete_four_attempt_repair_cycle() -> None:
    class RepairingFrontendWorker:
        @staticmethod
        def run(task):
            next_attempt = task.attempt + 1
            task.attempt = next_attempt
            task.status = TaskStatus.SUCCEEDED
            operation = "replace" if next_attempt == 1 else "patch"
            files = [
                {
                    "path": "frontend/src/App.tsx",
                    "content": (
                        "export function App() { "
                        f'return <main data-attempt="{next_attempt}" />; }}\n'
                    ),
                }
            ]
            if next_attempt == 1:
                files.extend(
                    [
                        {
                            "path": "frontend/index.html",
                            "content": '<div id="root"></div>\n',
                        },
                        {
                            "path": "frontend/src/main.tsx",
                            "content": "import './App';\n",
                        },
                        {
                            "path": "frontend/src/App.test.tsx",
                            "content": "export {};\n",
                        },
                    ]
                )
            return WorkerResult(
                task_id=task.task_id,
                worker_kind=WorkerKind.FRONTEND,
                status=TaskStatus.SUCCEEDED,
                summary=f"attempt {next_attempt}",
                output=json.dumps(
                    {
                        "summary": f"attempt {next_attempt}",
                        "operation": operation,
                        "files": files,
                        "deleted_files": [],
                    }
                ),
                attempt=next_attempt,
            )

    class EventuallyPassingEvaluator:
        calls = 0

        def evaluate(self, job):
            self.calls += 1
            if self.calls == 4:
                return EvaluationResult(passed=True, decision="pass")
            return EvaluationResult(
                passed=False,
                retry_targets=[WorkerKind.FRONTEND],
                failure_reason=(
                    "frontend/src/App.tsx is missing verified revision "
                    f"{self.calls + 1} of the required four-step repair sequence."
                ),
                decision="repair_required",
            )

    settings = Settings(
        app_env="test",
        enable_persistence=False,
        enable_llm_calls=False,
        enable_human_checkpoints=False,
        enable_artifact_generation=False,
        max_job_loops=4,
        max_worker_attempts=4,
        max_total_attempts=4,
    )
    runtime = AgentRuntime(settings=settings)
    runtime._workers[WorkerKind.FRONTEND] = RepairingFrontendWorker()
    evaluator = EventuallyPassingEvaluator()
    runtime._evaluator = evaluator
    job = JobState(request=JobRequest(prompt="Build a React frontend"))

    route = runtime.run_to_completion(job)

    assert route.action == RouteAction.SUCCESS
    assert job.status == JobStatus.SUCCEEDED
    assert job.loop_count == 4
    assert job.tasks[0].attempt == 4
    assert evaluator.calls == 4


def test_retry_context_replaces_old_failure_and_strips_noisy_output() -> None:
    task = JobTask(
        worker_kind=WorkerKind.FRONTEND,
        title="Frontend",
        instructions="Build the frontend.",
    )
    job = JobState(request=JobRequest(prompt="Build a webapp"), tasks=[task])
    job.evaluation = EvaluationResult(
        passed=False,
        retry_targets=[WorkerKind.FRONTEND],
        failure_reason="\x1b[31mfirst failure\x1b[0m " + ("DOM output " * 500),
    )

    AgentRuntime._reset_retry_targets(job, [WorkerKind.FRONTEND])
    first_instructions = task.instructions

    assert "\x1b[" not in first_instructions
    assert len(first_instructions) < 2_100
    assert first_instructions.count(RETRY_CORRECTION_MARKER) == 1

    job.evaluation.failure_reason = "second concise failure"
    AgentRuntime._reset_retry_targets(job, [WorkerKind.FRONTEND])

    assert "first failure" not in task.instructions
    assert "second concise failure" in task.instructions
    assert task.instructions.count(RETRY_CORRECTION_MARKER) == 1


def test_exhausted_semantic_failure_quarantines_last_runnable_artifact() -> None:
    job = JobState(request=JobRequest(prompt="Build a heritage gallery"))
    validation = {"passed": True, "results": [], "checks": ["frontend_docker_validation:passed"]}
    job.artifacts = [
        JobArtifact(
            artifact_id="project-folder",
            kind="folder",
            name="heritage",
            path="/tmp/heritage",
            url="/files",
            metadata={"validation": validation, "publish_allowed": True},
        )
    ]
    job.release_status = ReleaseStatus.VERIFIED

    runtime = AgentRuntime(Settings(app_env="test", enable_persistence=False))
    runtime._quarantine_runnable_artifacts(job, "Retry budget exhausted for frontend.")

    assert job.release_status == ReleaseStatus.QUARANTINED
    assert job.artifacts[0].metadata["publish_allowed"] is False
    assert job.artifacts[0].metadata["semantic_failure"] == ("Retry budget exhausted for frontend.")


def test_output_guardrails_scan_only_latest_worker_manifest() -> None:
    settings = Settings(
        app_env="test",
        enable_persistence=False,
        enable_human_checkpoints=False,
    )
    runtime = AgentRuntime(settings=settings)
    task = JobTask(worker_kind=WorkerKind.FRONTEND, title="UI", instructions="Build UI")
    job = JobState(request=JobRequest(prompt="Build a frontend"), tasks=[task])
    old_output = json.dumps(
        {
            "summary": "old",
            "files": [
                {
                    "path": "frontend/src/data.ts",
                    "content": "const card = '4111 1111 1111 1111';",
                }
            ],
        }
    )
    latest_output = json.dumps(
        {
            "summary": "fixed",
            "files": [{"path": "frontend/src/data.ts", "content": "export const safe = true;"}],
        }
    )
    job.worker_results = [
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.FRONTEND,
            status=TaskStatus.SUCCEEDED,
            summary="old",
            output=old_output,
            attempt=1,
        ),
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.FRONTEND,
            status=TaskStatus.SUCCEEDED,
            summary="fixed",
            output=latest_output,
            attempt=2,
        ),
    ]

    assert runtime._run_output_guardrails(job)
    assert job.guardrail_reports[-3].passed


def test_output_dlp_ignores_test_fixtures_but_blocks_runtime_pii() -> None:
    runtime = AgentRuntime(
        Settings(app_env="test", enable_persistence=False, enable_human_checkpoints=False)
    )
    task = JobTask(worker_kind=WorkerKind.FRONTEND, title="UI", instructions="Build UI")
    job = JobState(request=JobRequest(prompt="Build a frontend"), tasks=[task])
    job.worker_results = [
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.FRONTEND,
            status=TaskStatus.SUCCEEDED,
            summary="frontend",
            output=json.dumps(
                {
                    "operation": "replace",
                    "files": [
                        {
                            "path": "frontend/src/App.tsx",
                            "content": "export function App() { return <main />; }",
                        },
                        {
                            "path": "frontend/src/App.test.tsx",
                            "content": "const fixture = 'member@gmail.com';",
                        },
                    ],
                }
            ),
        )
    ]

    assert runtime._run_output_guardrails(job)

    job.worker_results[0].output = json.dumps(
        {
            "operation": "replace",
            "files": [
                {
                    "path": "frontend/src/App.tsx",
                    "content": "const leaked = 'jane.doe@gmail.com';",
                }
            ],
        }
    )

    assert not runtime._run_output_guardrails(job)


def test_final_attempt_uses_stronger_worker_patch_and_never_replaces_product() -> None:
    runtime = AgentRuntime(
        Settings(
            app_env="test",
            enable_persistence=False,
            enable_llm_calls=True,
            openai_api_key="test-key",
            enable_human_checkpoints=False,
        )
    )
    task = JobTask(
        worker_kind=WorkerKind.FRONTEND,
        title="Heritage gallery",
        instructions="Show heritage images",
        capability_id="react-vite",
        attempt=3,
        max_attempts=4,
    )
    job = JobState(request=JobRequest(prompt="Show heritage images"), tasks=[task])
    runtime._manifest_checkpoints.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Heritage",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.tsx", "export const title = 'Heritage';", WorkerKind.FRONTEND
                ),
                GeneratedFileSpec(
                    "frontend/src/styles.css", "body { color: navy; }", WorkerKind.FRONTEND
                ),
            ],
        ),
    )
    runtime._repair_kernel.register_evaluation_failure(
        job,
        EvaluationResult(
            passed=False,
            retry_targets=[WorkerKind.FRONTEND],
            failure_reason="frontend/src/App.tsx omits heritage images.",
        ),
    )
    default_worker = Mock()
    repair_worker = Mock()
    repair_worker.run.return_value = WorkerResult(
        task_id=task.task_id,
        worker_kind=task.worker_kind,
        status=TaskStatus.SUCCEEDED,
        summary="Add real image",
        attempt=99,
        output=json.dumps(
            {
                "operation": "patch",
                "files": [
                    {
                        "path": "frontend/src/App.tsx",
                        "content": 'export function App() { return <img src="/heritage.svg" alt="Heritage" />; }',
                    }
                ],
            }
        ),
    )
    runtime._workers[WorkerKind.FRONTEND] = default_worker
    runtime._repair_workers_final[WorkerKind.FRONTEND] = repair_worker

    route = runtime._run_worker_batch(job, [WorkerKind.FRONTEND])

    assert route is None
    default_worker.run.assert_not_called()
    repair_worker.run.assert_called_once()
    assert task.attempt == 4
    files = {file.path: file.content for file in collect_worker_file_specs(job)}
    assert "Heritage" in files["frontend/src/App.tsx"]
    assert files["frontend/src/styles.css"] == "body { color: navy; }"

    exhausted_route = runtime._run_worker_batch(job, [WorkerKind.FRONTEND])

    assert exhausted_route.action == RouteAction.FAILURE
    repair_worker.run.assert_called_once()


def test_targeted_patch_uses_repair_worker_from_first_retry() -> None:
    runtime = AgentRuntime(
        Settings(
            app_env="test",
            enable_persistence=False,
            enable_llm_calls=True,
            openai_api_key="test-key",
            enable_human_checkpoints=False,
        )
    )
    task = JobTask(
        worker_kind=WorkerKind.FRONTEND,
        title="Frontend",
        instructions="Build frontend.",
        capability_id="react-vite",
        attempt=1,
        max_attempts=4,
    )
    job = JobState(request=JobRequest(prompt="Build frontend"), tasks=[task])
    runtime._manifest_checkpoints.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Initial",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.tsx",
                    "export function App() { return <main />; }",
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )
    runtime._repair_kernel.register_evaluation_failure(
        job,
        EvaluationResult(
            passed=False,
            retry_targets=[WorkerKind.FRONTEND],
            failure_reason="frontend/src/App.tsx lacks the requested heading.",
        ),
    )
    default_worker = Mock()
    repair_worker = Mock()
    repair_worker.run.return_value = WorkerResult(
        task_id=task.task_id,
        worker_kind=task.worker_kind,
        status=TaskStatus.SUCCEEDED,
        summary="Add heading",
        output=json.dumps(
            {
                "operation": "patch",
                "files": [
                    {
                        "path": "frontend/src/App.tsx",
                        "content": "export function App() { return <h1>Ready</h1>; }",
                    }
                ],
            }
        ),
    )
    runtime._workers[WorkerKind.FRONTEND] = default_worker
    runtime._repair_workers_standard[WorkerKind.FRONTEND] = repair_worker

    route = runtime._run_worker_batch(job, [WorkerKind.FRONTEND])

    assert route is None
    default_worker.run.assert_not_called()
    repair_worker.run.assert_called_once()
    assert task.attempt == 2


def test_quarantine_updates_downloaded_report_without_replacing_code(tmp_path) -> None:
    settings = Settings(
        app_env="test",
        enable_persistence=False,
        generated_projects_dir=tmp_path / "generated",
        artifacts_dir=tmp_path / "artifacts",
    )
    runtime = AgentRuntime(settings)
    job = JobState(
        request=JobRequest(prompt="Build a React frontend"),
        tasks=[
            JobTask(
                worker_kind=WorkerKind.FRONTEND,
                title="Frontend",
                instructions="Build UI",
                capability_id="react-vite",
            )
        ],
    )
    job.artifacts = runtime._artifact_generator.generate(job)
    folder = next(artifact for artifact in job.artifacts if artifact.kind == "folder")
    archive = next(artifact for artifact in job.artifacts if artifact.kind == "zip")
    source_path = Path(folder.path) / "frontend/src/App.tsx"
    original_source = source_path.read_text()

    runtime._quarantine_runnable_artifacts(job, "Requested media is missing.")

    report_path = Path(folder.path) / "artifacts/risk-report.json"
    report = json.loads(report_path.read_text())
    assert report["release_status"] == "quarantined"
    assert report["publish_allowed"] is False
    assert report["findings"][-1]["name"] == "semantic_release_gate"
    with zipfile.ZipFile(archive.path) as download:
        assert json.loads(download.read("artifacts/risk-report.json")) == report
        assert download.read("frontend/src/App.tsx").decode() == original_source
    assert source_path.read_text() == original_source


def test_publication_requires_completed_semantic_evaluation() -> None:
    job = JobState(request=JobRequest(prompt="Build UI"), release_status=ReleaseStatus.VERIFIED)
    job.status = JobStatus.RUNNING
    assert not publication_allowed(job)
    job.status = JobStatus.FAILED
    assert not publication_allowed(job)
    job.status = JobStatus.SUCCEEDED
    assert publication_allowed(job)
    job.release_status = ReleaseStatus.QUARANTINED
    assert not publication_allowed(job)


def test_infrastructure_validation_failure_does_not_consume_worker_retry() -> None:
    class InfrastructureLimitedGenerator:
        @staticmethod
        def generate(job):
            validation = ProjectValidationReport(
                passed=False,
                release_ready=False,
                checks=["frontend_dependency_audit:infrastructure_advisory"],
                failure_reason="Package registry timed out.",
                failure_kind="infrastructure",
            ).to_dict()
            job.release_status = ReleaseStatus.PROVISIONAL
            return [
                JobArtifact(
                    artifact_id="project-folder",
                    kind="folder",
                    name="project",
                    path="/tmp/project",
                    url="/files",
                    metadata={"validation": validation},
                ),
                JobArtifact(
                    artifact_id="project-zip",
                    kind="zip",
                    name="project.zip",
                    path="/tmp/project.zip",
                    url="/download",
                    metadata={"validation": validation},
                ),
            ]

    runtime = AgentRuntime(
        Settings(
            app_env="test",
            enable_persistence=False,
            enable_llm_calls=False,
            enable_human_checkpoints=False,
            max_worker_attempts=4,
            max_total_attempts=8,
        )
    )
    runtime._artifact_generator = InfrastructureLimitedGenerator()
    job = JobState(request=JobRequest(prompt="Build a React frontend"))

    route = runtime.run_to_completion(job)

    assert route.action == RouteAction.SUCCESS
    assert job.status == JobStatus.SUCCEEDED
    assert job.tasks[0].attempt == 1
    assert job.tasks[0].transport_attempts == 1
    assert job.evaluation is not None
    assert job.evaluation.decision == "warning"
    assert "infrastructure_failure:no_worker_retry" in job.evaluation.checks


def test_deterministic_final_patch_keeps_standard_repair_model() -> None:
    runtime = AgentRuntime(
        Settings(
            app_env="test",
            enable_persistence=False,
            enable_llm_calls=True,
            openai_api_key="test-key",
            enable_human_checkpoints=False,
        )
    )
    task = JobTask(
        worker_kind=WorkerKind.FRONTEND,
        title="Gaming frontend",
        instructions="Build the gaming frontend.",
        capability_id="react-vite",
        attempt=3,
        max_attempts=4,
    )
    job = JobState(request=JobRequest(prompt="Build a gaming website"), tasks=[task])
    runtime._repair_kernel.register_validation_failure(
        job,
        ProjectValidationReport(
            passed=False,
            retry_targets=[WorkerKind.FRONTEND],
            failure_reason="getByRole heading does not match the rendered accessible name.",
            results=[
                ValidationCommandResult(
                    name="frontend_tests",
                    worker_kind=WorkerKind.FRONTEND,
                    command="npm test",
                    cwd="/tmp/frontend",
                    passed=False,
                    exit_code=1,
                    duration_seconds=1,
                    stderr_excerpt="TestingLibraryElementError: getByRole heading",
                )
            ],
        ),
    )

    assert runtime._repair_kernel.active_strategy(job, WorkerKind.FRONTEND) == "final_patch"
    assert not runtime._premium_repair_is_justified(job, task)


def test_complex_backend_final_patch_uses_premium_repair_model() -> None:
    runtime = AgentRuntime(
        Settings(
            app_env="test",
            enable_persistence=False,
            enable_llm_calls=True,
            openai_api_key="test-key",
            enable_human_checkpoints=False,
        )
    )
    task = JobTask(
        worker_kind=WorkerKind.BACKEND,
        title="Subscription backend",
        instructions="Build authenticated subscription checkout.",
        capability_id="react-fastapi",
        adapter_ids=["core", "commerce", "auth-rbac", "persistence"],
        attempt=3,
        max_attempts=4,
    )
    job = JobState(request=JobRequest(prompt="Build subscription commerce"), tasks=[task])
    runtime._repair_kernel.register_validation_failure(
        job,
        ProjectValidationReport(
            passed=False,
            retry_targets=[WorkerKind.BACKEND],
            failure_reason="Checkout response does not satisfy its response model.",
        ),
    )

    assert runtime._repair_kernel.active_strategy(job, WorkerKind.BACKEND) == "final_patch"
    assert runtime._premium_repair_is_justified(job, task)


def test_semantic_requirement_gap_uses_premium_repair_model() -> None:
    runtime = AgentRuntime(
        Settings(
            app_env="test",
            enable_persistence=False,
            enable_llm_calls=True,
            openai_api_key="test-key",
            enable_human_checkpoints=False,
        )
    )
    task = JobTask(
        worker_kind=WorkerKind.BACKEND,
        title="Commerce backend",
        instructions="Build the commerce backend.",
        capability_id="react-fastapi",
        attempt=1,
        max_attempts=4,
    )
    job = JobState(request=JobRequest(prompt="Build wallet checkout"), tasks=[task])
    runtime._repair_kernel.register_evaluation_failure(
        job,
        EvaluationResult(
            passed=False,
            retry_targets=[WorkerKind.BACKEND],
            failure_reason="The requested idempotent checkout flow is absent.",
            evidence=[
                {
                    "requirement": "Idempotent checkout",
                    "observation": "No idempotency key is stored",
                    "location": "backend/app/main.py:40",
                    "verification": "Submit the same checkout request twice",
                }
            ],
        ),
    )

    assert runtime._premium_repair_is_justified(job, task)


def test_repeated_validation_failure_uses_premium_final_repair_model() -> None:
    runtime = AgentRuntime(
        Settings(
            app_env="test",
            enable_persistence=False,
            enable_llm_calls=True,
            openai_api_key="test-key",
            enable_human_checkpoints=False,
        )
    )
    task = JobTask(
        worker_kind=WorkerKind.FRONTEND,
        title="Game frontend",
        instructions="Build the game frontend.",
        capability_id="react-vite",
        attempt=3,
        max_attempts=4,
    )
    job = JobState(request=JobRequest(prompt="Build a browser game"), tasks=[task])
    report = ProjectValidationReport(
        passed=False,
        retry_targets=[WorkerKind.FRONTEND],
        failure_reason="Expected checkmate but received check.",
        results=[
            ValidationCommandResult(
                name="frontend_tests",
                worker_kind=WorkerKind.FRONTEND,
                command="npm test",
                cwd="/tmp/frontend",
                passed=False,
                exit_code=1,
                duration_seconds=1,
                stderr_excerpt="Expected: checkmate\nReceived: check",
            )
        ],
    )

    runtime._repair_kernel.register_validation_failure(job, report)
    runtime._repair_kernel.register_validation_failure(job, report)

    assert runtime._premium_repair_is_justified(job, task)


def test_complex_backend_reasoning_requires_multiple_high_risk_adapters() -> None:
    simple = JobTask(
        worker_kind=WorkerKind.BACKEND,
        title="Health API",
        instructions="Build a health API.",
        capability_id="fastapi-api",
        adapter_ids=["core", "stack:fastapi-api"],
    )
    complex_task = JobTask(
        worker_kind=WorkerKind.BACKEND,
        title="Commerce API",
        instructions="Build authenticated checkout.",
        capability_id="react-fastapi",
        adapter_ids=["core", "stack:react-fastapi", "commerce", "auth-rbac", "persistence"],
    )

    assert not AgentRuntime._complex_backend_reasoning_is_justified(simple)
    assert AgentRuntime._complex_backend_reasoning_is_justified(complex_task)


def test_database_integration_repair_uses_standard_model_until_rejected_twice() -> None:
    runtime = AgentRuntime(
        Settings(
            app_env="test",
            enable_persistence=False,
            enable_llm_calls=True,
            openai_api_key="test-key",
            enable_human_checkpoints=False,
        )
    )
    task = JobTask(
        worker_kind=WorkerKind.BACKEND,
        title="Persistent backend",
        instructions="Connect the backend to PostgreSQL.",
        capability_id="react-fastapi",
        attempt=2,
        max_attempts=4,
    )
    job = JobState(request=JobRequest(prompt="Build a database app"), tasks=[task])
    runtime._repair_kernel.register_validation_failure(
        job,
        ProjectValidationReport(
            passed=False,
            retry_targets=[WorkerKind.BACKEND],
            failure_reason="The backend does not open the requested database connection.",
        ),
    )

    assert not runtime._premium_repair_is_justified(job, task)
    task.repair_rejections = 2
    assert runtime._premium_repair_is_justified(job, task)


def test_premium_repair_is_used_at_most_once_per_component() -> None:
    runtime = AgentRuntime(
        Settings(
            app_env="test",
            enable_persistence=False,
            enable_llm_calls=True,
            openai_api_key="test-key",
            enable_human_checkpoints=False,
        )
    )
    task = JobTask(
        worker_kind=WorkerKind.BACKEND,
        title="Commerce backend",
        instructions="Repair authenticated checkout.",
        capability_id="react-fastapi",
        adapter_ids=["commerce", "auth-rbac", "persistence"],
        attempt=3,
        max_attempts=4,
    )
    job = JobState(request=JobRequest(prompt="Build commerce"), tasks=[task])
    runtime._repair_kernel.register_evaluation_failure(
        job,
        EvaluationResult(
            passed=False,
            retry_targets=[WorkerKind.BACKEND],
            failure_reason="Checkout response violates the requested contract.",
            evidence=[
                {
                    "requirement": "Checkout contract",
                    "observation": "Response omits the balance",
                    "location": "backend/app/main.py:40",
                    "verification": "Submit a valid checkout",
                }
            ],
        ),
    )

    assert runtime._premium_repair_is_justified(job, task)
    job.cost_ledger = {
        "calls": [{"node": "repair.sol.backend", "model": "gpt-5.6-sol"}]
    }
    assert not runtime._premium_repair_is_justified(job, task)
