import json

from software_developer_agent.agents.workers.base import DeveloperWorker
from software_developer_agent.artifacts.file_manifest import (
    GeneratedFileSpec,
    WorkerFileManifest,
)
from software_developer_agent.artifacts.validation import (
    ProjectValidationReport,
    ValidationCommandResult,
)
from software_developer_agent.capabilities.registry import resolve_project_spec
from software_developer_agent.config.settings import Settings
from software_developer_agent.memory.manifest_checkpoint import ManifestCheckpointManager
from software_developer_agent.models.job_state import (
    EvaluationResult,
    JobRequest,
    JobState,
    JobTask,
    TaskStatus,
    WorkerKind,
    WorkerResult,
)
from software_developer_agent.orchestration.repair_kernel import UniversalRepairKernel
from software_developer_agent.tools.registry import ToolContext


def _frontend_job() -> tuple[JobState, JobTask]:
    spec = resolve_project_spec("Build a React frontend", {"capability_id": "react-vite"})
    task = JobTask(
        worker_kind=WorkerKind.FRONTEND,
        title="Frontend",
        instructions="Build the frontend.",
        max_attempts=4,
        capability_id=spec.capability_id,
        adapter_ids=spec.adapter_ids,
    )
    return (
        JobState(
            request=JobRequest(prompt="Build a React frontend", project_id="repair-test"),
            project_spec=spec.to_dict(),
            tasks=[task],
        ),
        task,
    )


def _failed_report() -> ProjectValidationReport:
    return ProjectValidationReport(
        passed=False,
        checks=["frontend_tests:failed"],
        results=[
            ValidationCommandResult(
                name="frontend_docker_validation",
                worker_kind=WorkerKind.FRONTEND,
                command="npm test -- --run",
                cwd="/tmp/project/frontend",
                passed=False,
                exit_code=1,
                duration_seconds=1.2,
                stderr_excerpt=(
                    "frontend/src/App.test.tsx:10:5 getByRole('heading', "
                    "{ name: /india heritage gallery/i })\nExpected: heading\nActual: paragraph"
                ),
            )
        ],
        retry_targets=[WorkerKind.FRONTEND],
        failure_reason="Frontend test assertion failed.",
    )


def test_repeated_failure_escalates_then_reserves_final_patch() -> None:
    job, task = _frontend_job()
    task.attempt = 1
    kernel = UniversalRepairKernel(
        Settings(
            app_env="test",
            enable_persistence=False,
            enable_llm_calls=True,
            openai_api_key="test-key",
        )
    )

    first = kernel.register_validation_failure(job, _failed_report())[0]
    second = kernel.register_validation_failure(job, _failed_report())[0]
    task.attempt = 3
    third = kernel.register_validation_failure(job, _failed_report())[0]

    assert first.fingerprint == second.fingerprint == third.fingerprint
    assert first.strategy == "targeted_patch"
    assert second.strategy == "escalated_patch"
    assert third.strategy == "final_patch"
    assert job.failure_fingerprints[first.fingerprint] == 3


def test_test_failure_fingerprint_ignores_transient_runner_output() -> None:
    job, task = _frontend_job()
    task.attempt = 1
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))

    first_report = _failed_report()
    second_report = _failed_report()
    first_report.results[0].stderr_excerpt += "\nDuration 1.01s\nStart at 08:41:22"
    second_report.results[0].stderr_excerpt += "\nDuration 1.38s\nStart at 08:44:57"

    first = kernel.register_validation_failure(job, first_report)[0]
    second = kernel.register_validation_failure(job, second_report)[0]

    assert first.fingerprint == second.fingerprint
    assert second.occurrence == 2
    assert second.strategy == "escalated_patch"


def test_collection_error_fingerprint_ignores_install_and_timing_noise() -> None:
    job, task = _frontend_job()
    task.attempt = 1
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))

    def report(version: str, duration: str) -> ProjectValidationReport:
        return ProjectValidationReport(
            passed=False,
            results=[
                ValidationCommandResult(
                    name="frontend_docker_execution",
                    worker_kind=WorkerKind.FRONTEND,
                    command="npm test",
                    cwd="/tmp/frontend",
                    passed=False,
                    exit_code=1,
                    duration_seconds=1,
                    stderr_excerpt=(
                        f"added 124 packages with npm {version}\n"
                        "ERROR tests/App.test.tsx - AssertionError: invalid response model\n"
                        "E   AssertionError: Status code 204 must not have a response body\n"
                        f"Duration {duration}"
                    ),
                )
            ],
            retry_targets=[WorkerKind.FRONTEND],
            failure_reason="Frontend test collection failed.",
        )

    first = kernel.register_validation_failure(job, report("10.8.2", "1.1s"))[0]
    second = kernel.register_validation_failure(job, report("12.0.2", "1.8s"))[0]

    assert first.fingerprint == second.fingerprint
    assert second.occurrence == 2


def test_typescript_build_error_takes_priority_over_passing_test_output() -> None:
    job, task = _frontend_job()
    task.attempt = 2
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))
    report = ProjectValidationReport(
        passed=False,
        results=[
            ValidationCommandResult(
                name="frontend_docker_execution",
                worker_kind=WorkerKind.FRONTEND,
                command="npm test && npm run build",
                cwd="/tmp/frontend",
                passed=False,
                exit_code=2,
                duration_seconds=1,
                stderr_excerpt=(
                    "Test Files 2 passed (2)\n"
                    "tsc && vite build\n"
                    "src/App.tsx(119,9): error TS2345: Argument of type '{}' is not assignable"
                ),
            )
        ],
        retry_targets=[WorkerKind.FRONTEND],
        failure_reason="Frontend build failed after tests passed.",
    )

    ticket = kernel.register_validation_failure(job, report)[0]

    assert ticket.category == "build"


def test_unchanged_repair_candidate_is_rejected_without_advancing_attempt() -> None:
    job, task = _frontend_job()
    task.attempt = 1
    manager = ManifestCheckpointManager(Settings(app_env="test", enable_persistence=False))
    initial = WorkerFileManifest(
        worker_kind=WorkerKind.FRONTEND,
        summary="Initial",
        operation="replace",
        files=[
            GeneratedFileSpec(
                "frontend/src/App.tsx",
                "export function App() { return <main />; }\n",
                WorkerKind.FRONTEND,
            )
        ],
    )
    manager.commit(job, task, initial)
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))

    verification = kernel.verify_candidate(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Claimed fix",
            operation="patch",
            files=initial.files,
        ),
    )

    assert not verification.accepted
    assert "no material file change" in verification.reason
    assert task.attempt == 1


def test_python_syntax_error_is_rejected_before_execution_attempt() -> None:
    spec = resolve_project_spec("Build a FastAPI backend", {"capability_id": "fastapi-api"})
    task = JobTask(
        worker_kind=WorkerKind.BACKEND,
        title="Backend",
        instructions="Build the backend.",
        attempt=1,
        max_attempts=4,
        capability_id=spec.capability_id,
        adapter_ids=spec.adapter_ids,
    )
    job = JobState(
        request=JobRequest(prompt="Build a FastAPI backend", project_id="syntax-repair"),
        project_spec=spec.to_dict(),
        tasks=[task],
    )
    manager = ManifestCheckpointManager(Settings(app_env="test", enable_persistence=False))
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.BACKEND,
            summary="Initial backend",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "backend/app/main.py",
                    "def health():\n    return {'status': 'ok'}\n",
                    WorkerKind.BACKEND,
                )
            ],
        ),
    )
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))

    verification = kernel.verify_candidate(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.BACKEND,
            summary="Malformed repair",
            operation="patch",
            files=[
                GeneratedFileSpec(
                    "backend/app/main.py",
                    "def health(:\n    return {'status': 'ok'}\n",
                    WorkerKind.BACKEND,
                )
            ],
        ),
    )

    assert not verification.accepted
    assert "invalid Python syntax" in verification.reason
    assert "before consuming an execution attempt" in verification.reason
    assert task.attempt == 1


def test_destructive_repair_candidate_is_rejected_without_explicit_request() -> None:
    job, task = _frontend_job()
    task.attempt = 1
    manager = ManifestCheckpointManager(Settings(app_env="test", enable_persistence=False))
    original_content = "\n".join(
        f"export const destination{index} = 'preserved destination {index}';" for index in range(30)
    )
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Initial",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "frontend/src/places.ts",
                    original_content,
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))

    verification = kernel.verify_candidate(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Changed one image but dropped most destinations",
            operation="patch",
            files=[
                GeneratedFileSpec(
                    "frontend/src/places.ts",
                    "export const destination0 = 'replacement image';\n",
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )

    assert not verification.accepted
    assert "unexpectedly shrinks frontend/src/places.ts" in verification.reason
    assert "smallest sufficient patch" in verification.reason


def test_broad_rewrite_is_rejected_even_when_candidate_is_not_smaller() -> None:
    job, task = _frontend_job()
    task.attempt = 1
    manager = ManifestCheckpointManager(Settings(app_env="test", enable_persistence=False))
    original_content = "\n".join(
        f"export function destination{index}() {{ return 'heritage-{index}'; }}"
        for index in range(30)
    )
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Initial",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.tsx",
                    original_content,
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))
    unrelated_rewrite = "\n".join(
        f"interface Tournament{index} {{ score: number; player: string; arena: boolean }}"
        for index in range(40)
    )

    verification = kernel.verify_candidate(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Rebuilt the whole component during a targeted repair",
            operation="patch",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.tsx",
                    unrelated_rewrite,
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )

    assert not verification.accepted
    assert "rewrites too much unrelated content" in verification.reason
    assert "smallest evidence-driven change" in verification.reason


def test_nonshrinking_test_expansion_can_change_broadly() -> None:
    job, task = _frontend_job()
    task.attempt = 1
    manager = ManifestCheckpointManager(Settings(app_env="test", enable_persistence=False))
    original_content = "\n".join(
        f"test('legacy {index}', () => expect({index}).toBe({index}));" for index in range(20)
    )
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Initial tests",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.test.tsx",
                    original_content,
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )
    replacement = "\n".join(
        f"it('rbac scenario {index}', () => expect(screen).toBeDefined());" for index in range(30)
    )
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))

    verification = kernel.verify_candidate(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Expand requirement coverage",
            operation="patch",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.test.tsx",
                    replacement,
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )

    assert verification.accepted


def test_certified_fallback_can_be_replaced_by_real_product_code() -> None:
    job, task = _frontend_job()
    task.attempt = 1
    manager = ManifestCheckpointManager(Settings(app_env="test", enable_persistence=False))
    fallback_content = "\n".join(
        f"export const fallbackLine{index} = 'certified placeholder';" for index in range(40)
    )
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Certified fallback",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.tsx",
                    fallback_content,
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )
    job.add_worker_result(
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.FRONTEND,
            status=TaskStatus.SUCCEEDED,
            summary="Certified runnable checkpoint",
            attempt=task.attempt,
            used_fallback=True,
        )
    )
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))
    product_content = "\n".join(
        f"export function GameArena{index}() {{ return <section>Round {index}</section>; }}"
        for index in range(40)
    )

    verification = kernel.verify_candidate(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Replace fallback with requested product",
            operation="patch",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.tsx",
                    product_content,
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )

    assert verification.accepted


def test_fallback_lineage_allows_broad_followup_semantic_repair() -> None:
    job, task = _frontend_job()
    task.attempt = 2
    manager = ManifestCheckpointManager(Settings(app_env="test", enable_persistence=False))
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Partially upgraded fallback",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.tsx",
                    "\n".join(
                        f"export const scaffoldLine{index} = 'partial';" for index in range(40)
                    ),
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )
    job.add_worker_result(
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.FRONTEND,
            status=TaskStatus.SUCCEEDED,
            summary="Certified runnable checkpoint",
            attempt=1,
            used_fallback=True,
        )
    )
    job.add_worker_result(
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.FRONTEND,
            status=TaskStatus.SUCCEEDED,
            summary="Partial product repair",
            attempt=2,
            used_fallback=False,
        )
    )
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))
    kernel.register_evaluation_failure(
        job,
        EvaluationResult(
            passed=False,
            retry_targets=[WorkerKind.FRONTEND],
            failure_reason="The requested product interactions are still incomplete.",
        ),
    )
    complete_product = "\n".join(
        f"export function ProductFeature{index}() {{ return <section>Feature {index}</section>; }}"
        for index in range(40)
    )

    verification = kernel.verify_candidate(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Complete the requested product",
            operation="patch",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.tsx",
                    complete_product,
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )

    assert verification.accepted


def test_semantic_preflight_rejects_repair_that_keeps_heading_contract_broken() -> None:
    job, task = _frontend_job()
    task.attempt = 1
    manager = ManifestCheckpointManager(Settings(app_env="test", enable_persistence=False))
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Initial",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.tsx",
                    (
                        "export function App() { return <main><p>India Heritage Gallery</p>"
                        "<h1>Beautiful places</h1></main>; }\n"
                    ),
                    WorkerKind.FRONTEND,
                ),
                GeneratedFileSpec(
                    "frontend/src/App.test.tsx",
                    ("screen.getByRole('heading', { name: /india heritage gallery/i });\n"),
                    WorkerKind.FRONTEND,
                ),
            ],
        ),
    )
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))
    kernel.register_validation_failure(job, _failed_report())

    verification = kernel.verify_candidate(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Changed an unrelated assertion",
            operation="patch",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.test.tsx",
                    (
                        "// repaired punctuation only\n"
                        "screen.getByRole('heading', "
                        "{ name: /india heritage gallery/i });\n"
                    ),
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )

    assert not verification.accepted
    assert "still fails deterministic capability preflight" in verification.reason


def test_candidate_is_not_rejected_for_another_workers_adapter_failure() -> None:
    spec = resolve_project_spec(
        "Build a React and FastAPI video platform without a database.",
        {"capability_id": "react-fastapi"},
    )
    task = JobTask(
        worker_kind=WorkerKind.BACKEND,
        title="Backend",
        instructions="Build the backend.",
        max_attempts=4,
        capability_id=spec.capability_id,
        adapter_ids=spec.adapter_ids,
    )
    job = JobState(
        request=JobRequest(
            prompt="Build a React and FastAPI video platform without a database.",
            project_id="video-repair-test",
        ),
        project_spec=spec.to_dict(),
        tasks=[task],
    )
    manager = ManifestCheckpointManager(Settings(app_env="test", enable_persistence=False))
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.BACKEND,
            summary="Initial backend",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "backend/app.py",
                    "def health():\n    return {'status': 'starting'}\n",
                    WorkerKind.BACKEND,
                )
            ],
        ),
    )
    task.attempt = 1
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))
    kernel.register_evaluation_failure(
        job,
        EvaluationResult(
            passed=False,
            retry_targets=[WorkerKind.BACKEND],
            failure_reason="Backend health response is incomplete.",
        ),
    )

    verification = kernel.verify_candidate(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.BACKEND,
            summary="Repair backend health response",
            operation="patch",
            files=[
                GeneratedFileSpec(
                    "backend/app.py",
                    "def health():\n    return {'status': 'ok'}\n",
                    WorkerKind.BACKEND,
                )
            ],
        ),
    )

    assert verification.accepted


def test_adapter_validated_integration_repair_may_restructure_owned_runtime() -> None:
    spec = resolve_project_spec(
        "Build a FastAPI application with PostgreSQL persistence.",
        {"capability_id": "fastapi-api"},
    )
    task = JobTask(
        worker_kind=WorkerKind.BACKEND,
        title="Backend",
        instructions="Build the persistent backend.",
        max_attempts=4,
        capability_id=spec.capability_id,
        adapter_ids=spec.adapter_ids,
    )
    job = JobState(
        request=JobRequest(prompt="Build a FastAPI application with PostgreSQL persistence."),
        project_spec=spec.to_dict(),
        tasks=[task],
    )
    manager = ManifestCheckpointManager(Settings(app_env="test", enable_persistence=False))
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.BACKEND,
            summary="Initial backend",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "backend/app.py",
                    "from fastapi import FastAPI\n" + "value = 'legacy'\n" * 80,
                    WorkerKind.BACKEND,
                )
            ],
        ),
    )
    task.attempt = 1
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))
    kernel.register_validation_failure(
        job,
        ProjectValidationReport(
            passed=False,
            retry_targets=[WorkerKind.BACKEND],
            failure_reason="The backend runtime does not configure a database connection.",
        ),
    )
    replacement = (
        "from fastapi import FastAPI\n"
        "from sqlalchemy import create_engine\n"
        "database_url = 'postgresql://configured-at-runtime'\n"
        "engine = create_engine(database_url)\n"
        + "value = 'preserved behavior'\n" * 65
    )

    verification = kernel.verify_candidate(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.BACKEND,
            summary="Wire the requested database",
            operation="patch",
            files=[GeneratedFileSpec("backend/app.py", replacement, WorkerKind.BACKEND)],
        ),
    )

    assert verification.accepted


def test_rejected_candidates_escalate_strategy_without_consuming_attempt() -> None:
    job, task = _frontend_job()
    task.attempt = 1
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))
    kernel.register_validation_failure(job, _failed_report())

    task.repair_rejections = 1
    assert kernel.active_strategy(job, WorkerKind.FRONTEND) == "escalated_patch"
    task.repair_rejections = 2
    assert kernel.active_strategy(job, WorkerKind.FRONTEND) == "final_patch"
    assert task.attempt == 1


class _ManifestRecoveryWorker(DeveloperWorker):
    worker_kind = WorkerKind.FRONTEND

    def __init__(self, outputs: list[str], settings: Settings) -> None:
        super().__init__(settings=settings)
        self._outputs = iter(outputs)

    def execute(self, task: JobTask, tool_context: str = "") -> str:
        return next(self._outputs)


class _BackendManifestRecoveryWorker(_ManifestRecoveryWorker):
    worker_kind = WorkerKind.BACKEND


class _ToolRegistryStub:
    def __init__(self) -> None:
        self.call_count = 0

    def collect_context(self, task: JobTask) -> ToolContext:
        self.call_count += 1
        return ToolContext(
            content="Stable media evidence.",
            calls=[{"tool": "media_asset_acquisition", "status": "success"}],
        )


class _ToolContextWorker(_ManifestRecoveryWorker):
    def __init__(self, outputs: list[str], settings: Settings, registry: _ToolRegistryStub) -> None:
        DeveloperWorker.__init__(self, settings=settings, tool_registry=registry)
        self._outputs = iter(outputs)
        self.seen_contexts: list[str] = []

    def execute(self, task: JobTask, tool_context: str = "") -> str:
        self.seen_contexts.append(tool_context)
        return next(self._outputs)


def test_worker_reuses_checkpointed_tool_context_across_repairs() -> None:
    task = JobTask(
        worker_kind=WorkerKind.FRONTEND,
        title="Frontend",
        instructions="Build frontend.",
        capability_id="react-vite",
    )
    candidate = json.dumps(
        {
            "summary": "valid candidate",
            "operation": "replace",
            "files": [
                {"path": "frontend/index.html", "content": '<div id="root"></div>\n'},
                {"path": "frontend/src/main.tsx", "content": "import './App';\n"},
                {"path": "frontend/src/App.tsx", "content": "export {};\n"},
                {"path": "frontend/src/App.test.tsx", "content": "export {};\n"},
            ],
        }
    )
    registry = _ToolRegistryStub()
    worker = _ToolContextWorker(
        [candidate, candidate],
        Settings(app_env="test", enable_persistence=False),
        registry,
    )

    worker.run(task)
    worker.run(task)

    assert registry.call_count == 1
    assert worker.seen_contexts == ["Stable media evidence.", "Stable media evidence."]
    assert task.tool_calls == [{"tool": "media_asset_acquisition", "status": "success"}]


def test_malformed_manifest_recovery_does_not_consume_official_attempt() -> None:
    task = JobTask(
        worker_kind=WorkerKind.FRONTEND,
        title="Frontend",
        instructions="Build frontend.",
        capability_id="react-vite",
    )
    valid = json.dumps(
        {
            "summary": "valid candidate",
            "operation": "replace",
            "files": [
                {"path": "frontend/index.html", "content": '<div id="root"></div>\n'},
                {"path": "frontend/src/main.tsx", "content": "import './App';\n"},
                {"path": "frontend/src/App.tsx", "content": "export {};\n"},
                {"path": "frontend/src/App.test.tsx", "content": "export {};\n"},
            ],
        }
    )
    worker = _ManifestRecoveryWorker(
        ["not json", valid],
        Settings(
            app_env="test",
            enable_persistence=False,
            max_manifest_recovery_attempts=1,
        ),
    )

    result = worker.run(task)

    assert result.status == TaskStatus.SUCCEEDED
    assert result.attempt == 1
    assert task.attempt == 0
    assert task.transport_attempts == 2


def test_invalid_initial_python_is_corrected_before_checkpoint_acceptance() -> None:
    task = JobTask(
        worker_kind=WorkerKind.BACKEND,
        title="Backend",
        instructions="Build backend.",
        capability_id="fastapi-api",
    )

    def candidate(source: str) -> str:
        return json.dumps(
            {
                "summary": "backend candidate",
                "operation": "replace",
                "files": [
                    {"path": "backend/requirements.txt", "content": "fastapi\n"},
                    {"path": "backend/app/main.py", "content": source},
                    {
                        "path": "backend/tests/test_main.py",
                        "content": "def test_health(): assert True\n",
                    },
                ],
            }
        )

    worker = _BackendManifestRecoveryWorker(
        [candidate("def health(:\n    return {'status': 'ok'}\n"), candidate("def health():\n    return {'status': 'ok'}\n")],
        Settings(
            app_env="test",
            enable_persistence=False,
            max_manifest_recovery_attempts=1,
        ),
    )

    result = worker.run(task)

    assert result.status == TaskStatus.SUCCEEDED
    assert task.transport_attempts == 2
    assert task.attempt == 0
    assert "def health():" in result.output


def test_initial_manifest_failure_creates_certified_runnable_checkpoint() -> None:
    task = JobTask(
        worker_kind=WorkerKind.FRONTEND,
        title="Frontend",
        instructions="Project: reliable-ui\nRequest: Build a React frontend.",
        capability_id="react-vite",
    )
    worker = _ManifestRecoveryWorker(
        ["not json", "still not json"],
        Settings(
            app_env="development",
            enable_persistence=False,
            max_manifest_recovery_attempts=1,
            enable_guaranteed_artifact_fallback=True,
        ),
    )

    result = worker.run(task)

    assert result.status == TaskStatus.SUCCEEDED
    assert result.used_fallback
    assert result.errors
    assert task.transport_attempts == 2
    assert "frontend/package.json" in result.artifacts


class _TerminalManifestRecoveryWorker(DeveloperWorker):
    worker_kind = WorkerKind.FRONTEND

    def execute(self, task: JobTask, tool_context: str = "") -> str:
        raise RuntimeError("OpenAI response did not complete: max_output_tokens.")


def test_terminal_output_limit_failure_is_not_retried_with_less_budget() -> None:
    task = JobTask(
        worker_kind=WorkerKind.FRONTEND,
        title="Frontend",
        instructions="Project: reliable-ui\nRequest: Build a React frontend.",
        capability_id="react-vite",
    )
    worker = _TerminalManifestRecoveryWorker(
        settings=Settings(
            app_env="development",
            enable_persistence=False,
            max_manifest_recovery_attempts=2,
            enable_guaranteed_artifact_fallback=True,
        )
    )

    result = worker.run(task)

    assert result.status == TaskStatus.SUCCEEDED
    assert result.used_fallback
    assert task.transport_attempts == 1


def test_missing_react_contract_files_are_injected_without_project_retry() -> None:
    task = JobTask(
        worker_kind=WorkerKind.FRONTEND,
        title="Heritage gallery",
        instructions="Build the heritage gallery.",
        capability_id="react-vite",
    )
    candidate = json.dumps(
        {
            "summary": "heritage gallery",
            "operation": "replace",
            "files": [
                {"path": "frontend/index.html", "content": '<div id="root"></div>\n'},
                {"path": "frontend/src/main.tsx", "content": "import './App';\n"},
                {
                    "path": "frontend/src/App.tsx",
                    "content": "export function App() { return <h1>India Heritage</h1>; }\n",
                },
                {"path": "frontend/src/App.test.tsx", "content": "export {};\n"},
                {
                    "path": "frontend/vite.config.ts",
                    "content": "import { defineConfig } from 'vite'; export default defineConfig({});\n",
                },
            ],
        }
    )
    worker = _ManifestRecoveryWorker(
        [candidate],
        Settings(app_env="test", enable_persistence=False),
    )

    result = worker.run(task)
    manifest = json.loads(result.output)
    paths = {file["path"] for file in manifest["files"]}

    assert result.status == TaskStatus.SUCCEEDED
    assert task.transport_attempts == 1
    assert task.attempt == 0
    assert "frontend/package.json" in paths
    assert "frontend/tsconfig.json" in paths
    assert "frontend/src/vite-env.d.ts" in paths


def test_evaluator_requirement_gap_keeps_full_typescript_paths() -> None:
    job, task = _frontend_job()
    task.attempt = 1
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))
    evaluation = EvaluationResult(
        passed=False,
        retry_targets=[WorkerKind.FRONTEND],
        failure_reason=(
            "The website requested no database, but frontend/src/App.tsx does not render "
            "the requested heritage images."
        ),
        evidence=[{"location": "frontend/src/App.tsx"}],
    )

    ticket = kernel.register_evaluation_failure(job, evaluation)[0]

    assert ticket.category == "requirement_gap"
    assert ticket.target_files == ["frontend/src/App.tsx"]


def test_repair_ticket_filters_dependency_traceback_paths() -> None:
    job, task = _frontend_job()
    task.attempt = 1
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))
    report = ProjectValidationReport(
        passed=False,
        retry_targets=[WorkerKind.FRONTEND],
        failure_reason="Frontend tests failed.",
        results=[
            ValidationCommandResult(
                name="frontend_tests",
                worker_kind=WorkerKind.FRONTEND,
                command="npm test",
                cwd="/tmp/frontend",
                passed=False,
                exit_code=1,
                duration_seconds=1,
                stderr_excerpt=(
                    "frontend/src/App.test.tsx:12:4 AssertionError\n"
                    "../node_modules/vitest/index.js:40:2 Error\n"
                    "/tmp/venv/lib/python3.11/site-packages/plugin.py:20:1 Error\n"
                    "docs.pytest.org/en/stable/how-to/capture-warnings.html:1 Error"
                ),
            )
        ],
    )

    ticket = kernel.register_validation_failure(job, report)[0]

    assert ticket.target_files == ["frontend/src/App.test.tsx"]


def test_failed_worker_manifest_is_not_classified_as_requirement_gap() -> None:
    job = JobState(
        request=JobRequest(prompt="Build wallet persistence"),
        tasks=[
            JobTask(
                worker_kind=WorkerKind.DATABASE,
                title="Database",
                instructions="Generate Supabase SQL",
            )
        ],
    )
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))
    evaluation = EvaluationResult(
        passed=False,
        retry_targets=[WorkerKind.DATABASE],
        failure_reason="database worker returned an invalid file manifest",
        checks=["worker_not_succeeded:database"],
    )

    ticket = kernel.register_evaluation_failure(job, evaluation)[0]

    assert ticket.source == "worker"
    assert ticket.category == "worker_output"
    assert ticket.strategy == "targeted_patch"


def test_rejected_repair_preserves_original_validation_ticket() -> None:
    job, _ = _frontend_job()
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))
    original = kernel.register_validation_failure(job, _failed_report())[0]
    evaluation = EvaluationResult(
        passed=False,
        retry_targets=[WorkerKind.FRONTEND],
        failure_reason="frontend repair candidate produced no material change",
        checks=["worker_not_succeeded:frontend"],
    )

    replacement = kernel.register_evaluation_failure(job, evaluation)

    assert replacement == []
    assert job.active_repair_ticket(WorkerKind.FRONTEND) is original
    assert original.category == "test_contract"


def test_dependency_failure_keeps_json_extension() -> None:
    job, task = _frontend_job()
    task.attempt = 1
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))
    report = ProjectValidationReport(
        passed=False,
        retry_targets=[WorkerKind.FRONTEND],
        failure_reason="Frontend package frontend/package.json is missing.",
    )

    ticket = kernel.register_validation_failure(job, report)[0]

    assert ticket.target_files == ["frontend/package.json"]


def test_adapter_failure_ticket_keeps_owned_structured_evidence() -> None:
    job, _ = _frontend_job()
    kernel = UniversalRepairKernel(Settings(app_env="test", enable_persistence=False))
    report = ProjectValidationReport(
        passed=False,
        retry_targets=[WorkerKind.FRONTEND],
        failure_reason="Multiple project findings.",
        adapter_findings=[
            {
                "adapter_id": "video-platform",
                "code": "playback_surface_missing",
                "message": "A video playback surface is missing.",
                "worker_kind": "frontend",
                "blocking": True,
                "paths": ["frontend/src/App.tsx"],
            },
            {
                "adapter_id": "auth-rbac",
                "code": "server_authorization_unproven",
                "message": "Backend authorization is missing.",
                "worker_kind": "backend",
                "blocking": True,
                "paths": ["backend/src/main.py"],
            },
        ],
    )

    ticket = kernel.register_validation_failure(job, report)[0]

    assert ticket.validation_name == "adapter:playback_surface_missing"
    assert "Failure: A video playback surface is missing." in ticket.summary
    assert ticket.target_files == ["frontend/src/App.tsx"]
