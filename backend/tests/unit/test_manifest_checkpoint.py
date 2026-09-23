import json

from software_developer_agent.artifacts.file_manifest import (
    GeneratedFileSpec,
    WorkerFileManifest,
    checkpointed_worker_file_manifests,
    normalize_worker_manifest,
)
from software_developer_agent.config.settings import Settings
from software_developer_agent.memory.manifest_checkpoint import ManifestCheckpointManager
from software_developer_agent.memory.project_context_manager import ProjectContextManager
from software_developer_agent.models.job_state import (
    JobRequest,
    JobState,
    JobTask,
    RepairTicket,
    TaskStatus,
    WorkerKind,
    WorkerResult,
)


def test_unaccepted_component_retry_requests_complete_initial_manifest() -> None:
    task = JobTask(worker_kind=WorkerKind.FRONTEND, title="UI", instructions="Build UI")
    job = JobState(request=JobRequest(prompt="Build a full-stack app"), tasks=[task])
    job.manifest_state = {
        "files": {
            "backend/main.py": {
                "content": "app = object()",
                "worker_kind": "backend",
                "task_id": "backend-task",
            }
        }
    }

    initial_context = json.loads(ManifestCheckpointManager.repair_context(job, task))

    assert "operation=replace" in initial_context["instructions"]
    assert "operation=patch" not in initial_context["instructions"]
    assert initial_context["files"][0]["path"] == "backend/main.py"
    task.attempt = 1
    repair_context = json.loads(ManifestCheckpointManager.repair_context(job, task))
    assert "operation=patch" in repair_context["instructions"]


def _frontend_job() -> tuple[JobState, JobTask, ManifestCheckpointManager]:
    task = JobTask(
        worker_kind=WorkerKind.FRONTEND,
        title="Frontend",
        instructions="Build the frontend.",
        capability_id="react-vite",
    )
    job = JobState(
        request=JobRequest(prompt="Build a frontend", project_id="checkpoint-test"),
        tasks=[task],
    )
    manager = ManifestCheckpointManager(
        Settings(
            app_env="test",
            enable_persistence=False,
            enable_langgraph_checkpointing=True,
        )
    )
    return job, task, manager


def test_partial_retry_preserves_complete_checkpointed_manifest() -> None:
    job, task, manager = _frontend_job()
    task.attempt = 1
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Initial application",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.tsx",
                    "export function App() { return <main />; }\n",
                    WorkerKind.FRONTEND,
                ),
                GeneratedFileSpec(
                    "frontend/src/App.test.tsx",
                    "export {};\n",
                    WorkerKind.FRONTEND,
                ),
            ],
        ),
    )

    task.attempt = 2
    canonical = manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Added the missing package manifest",
            operation="patch",
            files=[
                GeneratedFileSpec(
                    "frontend/package.json",
                    '{"name":"demo","version":"1.0.0"}\n',
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )

    assert {file.path for file in canonical.files} == {
        "frontend/package.json",
        "frontend/src/App.test.tsx",
        "frontend/src/App.tsx",
    }
    assert {file.path for file in checkpointed_worker_file_manifests(job)[0].files} == {
        "frontend/package.json",
        "frontend/src/App.test.tsx",
        "frontend/src/App.tsx",
    }


def test_same_attempt_normalization_uses_newer_manifest_revision() -> None:
    job, task, manager = _frontend_job()
    task.attempt = 1
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Initial test contract",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.test.tsx",
                    "expect(view).toBeInTheDocument();\n",
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )

    canonical = manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Normalized matcher types",
            operation="patch",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.test.tsx",
                    "import '@testing-library/jest-dom/vitest';\n"
                    "expect(view).toBeInTheDocument();\n",
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )

    files = {file.path: file.content for file in canonical.files}
    assert files["frontend/src/App.test.tsx"].startswith("import '@testing-library")
    assert job.manifest_state["revision"] == 2


def test_checkpoint_restores_manifest_without_job_snapshot() -> None:
    job, task, manager = _frontend_job()
    task.attempt = 1
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Initial application",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.tsx",
                    "export function App() { return null; }\n",
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )
    restored = JobState(
        request=job.request,
        job_id=job.job_id,
        tasks=[task],
    )

    manager.restore(restored)

    assert restored.manifest_state["files"]["frontend/src/App.tsx"]["content"].startswith(
        "export function App"
    )


def test_explicit_deleted_files_create_checkpoint_tombstones() -> None:
    job, task, manager = _frontend_job()
    task.attempt = 1
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Initial application",
            files=[
                GeneratedFileSpec(
                    "frontend/src/obsolete.ts",
                    "export const obsolete = true;\n",
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )
    task.attempt = 2
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Removed obsolete source",
            operation="patch",
            files=[],
            deleted_files=["frontend/src/obsolete.ts"],
        ),
    )

    assert job.manifest_state["files"]["frontend/src/obsolete.ts"]["deleted"] is True
    assert checkpointed_worker_file_manifests(job) == []


def test_repair_context_contains_complete_canonical_project() -> None:
    job, task, manager = _frontend_job()
    task.attempt = 1
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Initial application",
            files=[
                GeneratedFileSpec("frontend/a.ts", "a\n", WorkerKind.FRONTEND),
                GeneratedFileSpec("frontend/b.ts", "b\n", WorkerKind.FRONTEND),
            ],
        ),
    )

    context = json.loads(manager.repair_context(job, task))

    assert [file["path"] for file in context["files"]] == ["frontend/a.ts", "frontend/b.ts"]
    assert all("content" in file and "checksum" in file for file in context["files"])
    assert [file["path"] for file in context["project_file_index"]] == [
        "frontend/a.ts",
        "frontend/b.ts",
    ]


def test_backend_repair_context_omits_unrelated_frontend_content_but_indexes_it() -> None:
    task = JobTask(
        worker_kind=WorkerKind.BACKEND,
        title="Backend",
        instructions="Repair backend.",
        capability_id="react-fastapi",
        attempt=1,
    )
    job = JobState(
        request=JobRequest(prompt="Build a commerce app", project_id="scoped-context"),
        tasks=[task],
        manifest_state={
            "files": {
                "database/migrations/001.sql": {
                    "content": "create table products(id bigint primary key);\n",
                    "worker_kind": "database",
                    "checksum": "database-checksum",
                },
                "backend/app/main.py": {
                    "content": "app = object()\n",
                    "worker_kind": "backend",
                    "checksum": "backend-checksum",
                },
                "frontend/src/App.tsx": {
                    "content": "export function App() { return <main />; }\n",
                    "worker_kind": "frontend",
                    "checksum": "frontend-checksum",
                },
            }
        },
    )

    context = json.loads(ManifestCheckpointManager.repair_context(job, task))

    assert {file["path"] for file in context["files"]} == {
        "database/migrations/001.sql",
        "backend/app/main.py",
    }
    assert {file["path"] for file in context["project_file_index"]} == {
        "database/migrations/001.sql",
        "backend/app/main.py",
        "frontend/src/App.tsx",
    }
    assert "frontend/src/App.tsx" not in json.dumps(context["files"])
    assert context["content_scope"] == ["target_component", "database_contract"]


def test_repair_context_includes_latest_candidate_rejection() -> None:
    job, task, manager = _frontend_job()
    task.attempt = 1
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Initial application",
            files=[GeneratedFileSpec("frontend/a.ts", "a\n", WorkerKind.FRONTEND)],
        ),
    )
    job.add_worker_result(
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.FRONTEND,
            status=TaskStatus.FAILED,
            summary="Candidate rejected",
            errors=["The proposed patch still lacks the required loading state."],
            attempt=task.attempt,
        )
    )

    context = json.loads(manager.repair_context(job, task))

    assert context["previous_candidate_rejection"] == (
        "The proposed patch still lacks the required loading state."
    )
    assert "previous_candidate_rejection" in context["instructions"]


def test_test_failure_repair_context_protects_authoritative_tests() -> None:
    job, task, manager = _frontend_job()
    task.attempt = 1
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Initial application",
            files=[GeneratedFileSpec("frontend/game.ts", "export {};\n", WorkerKind.FRONTEND)],
        ),
    )
    job.add_repair_ticket(
        RepairTicket(
            source="adapter_validation",
            worker_kind=WorkerKind.FRONTEND,
            category="test_failure",
            summary="Expected checkmate; received check.",
            fingerprint="stable-test-failure",
            occurrence=2,
            strategy="escalated_patch",
        )
    )

    context = json.loads(manager.repair_context(job, task))

    assert "Reproduce the cited failing test scenario step by step" in context["instructions"]
    assert "do not remove, skip, loosen, or rewrite it" in context["instructions"]


def test_near_final_repair_context_requires_bounded_consistency_audit() -> None:
    job, task, manager = _frontend_job()
    task.attempt = task.max_attempts - 1
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Current application",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.tsx",
                    "export function App() { return <main />; }\n",
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )

    context = json.loads(manager.repair_context(job, task))

    assert "bounded consistency audit" in context["instructions"]
    assert "fix every discovered cause in one coherent patch" in context["instructions"]


def test_certified_fallback_repair_requires_complete_component_upgrade() -> None:
    job, task, manager = _frontend_job()
    task.attempt = 1
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
                    "export function App() { return <main>Fallback</main>; }\n",
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
            summary="Fallback",
            attempt=1,
            used_fallback=True,
        )
    )

    context = json.loads(manager.repair_context(job, task))

    assert context["certified_fallback_upgrade"] is True
    assert "Upgrade the entire owned component now" in context["instructions"]
    assert "Do not limit this repair to the first reported blocker" in context["instructions"]


def test_backend_initial_context_contains_canonical_database_manifest() -> None:
    database_task = JobTask(
        worker_kind=WorkerKind.DATABASE,
        title="Database",
        instructions="Build schema.",
        capability_id="react-fastapi",
    )
    backend_task = JobTask(
        worker_kind=WorkerKind.BACKEND,
        title="Backend",
        instructions="Build API.",
        capability_id="react-fastapi",
    )
    job = JobState(
        request=JobRequest(prompt="Build persistent app", project_id="upstream-context"),
        tasks=[database_task, backend_task],
    )
    manager = ManifestCheckpointManager(Settings(app_env="test", enable_persistence=False))
    database_task.attempt = 1
    manager.commit(
        job,
        database_task,
        WorkerFileManifest(
            worker_kind=WorkerKind.DATABASE,
            summary="Canonical schema",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "database/migrations/001.sql",
                    "CREATE TABLE plans (id uuid PRIMARY KEY);\n",
                    WorkerKind.DATABASE,
                )
            ],
        ),
    )

    context = json.loads(manager.upstream_generation_context(job, backend_task) or "{}")

    assert context["upstream_worker"] == "database"
    assert context["files"][0]["path"] == "database/migrations/001.sql"
    assert "Do not create Alembic" in context["instructions"]
    assert "operation=replace" in context["instructions"]


def test_trusted_capability_versions_override_llm_versions_and_keep_extras() -> None:
    manifest = WorkerFileManifest(
        worker_kind=WorkerKind.FRONTEND,
        summary="Generated frontend",
        files=[
            GeneratedFileSpec(
                "frontend/package.json",
                json.dumps(
                    {
                        "name": "demo",
                        "dependencies": {"react": "18.3.1", "zod": "4.0.0"},
                        "devDependencies": {
                            "@testing-library/react": "16.0.1",
                            "jsdom": "24.1.1",
                            "vite": "5.4.8",
                            "vitest": "2.0.5",
                        },
                    }
                ),
                WorkerKind.FRONTEND,
            )
        ],
    )

    normalized = normalize_worker_manifest(manifest, "react-vite")
    package = json.loads(normalized.files[0].content)

    assert package["dependencies"]["react"] == "19.2.8"
    assert package["dependencies"]["zod"] == "4.0.0"
    assert package["devDependencies"]["vite"] == "8.1.0"
    assert package["devDependencies"]["vitest"] == "4.1.11"
    assert package["devDependencies"]["@testing-library/react"] == "16.3.2"
    assert package["devDependencies"]["@testing-library/dom"] == "10.4.1"
    assert package["devDependencies"]["jsdom"] == "27.4.0"


def test_initial_react_manifest_receives_verified_runtime_contracts() -> None:
    manifest = WorkerFileManifest(
        worker_kind=WorkerKind.FRONTEND,
        summary="Heritage gallery",
        operation="replace",
        files=[
            GeneratedFileSpec(
                "frontend/index.html", '<div id="root"></div>\n', WorkerKind.FRONTEND
            ),
            GeneratedFileSpec("frontend/src/main.tsx", "import './App';\n", WorkerKind.FRONTEND),
            GeneratedFileSpec(
                "frontend/src/App.tsx",
                "export function App() { return <main />; }\n",
                WorkerKind.FRONTEND,
            ),
            GeneratedFileSpec(
                "frontend/src/App.test.tsx",
                "import '@testing-library/jest-dom/vitest';\nimport { render } from '@testing-library/react';\n",
                WorkerKind.FRONTEND,
            ),
        ],
    )

    normalized = normalize_worker_manifest(manifest, "react-vite")
    files = {file.path: file.content for file in normalized.files}
    package = json.loads(files["frontend/package.json"])

    assert "frontend/tsconfig.json" in files
    assert "frontend/vite.config.ts" in files
    assert "frontend/src/vite-env.d.ts" in files
    assert '"jsx": "react-jsx"' in files["frontend/tsconfig.json"]
    assert package["devDependencies"]["@testing-library/jest-dom"] == "6.9.1"
    assert package["devDependencies"]["@testing-library/react"] == "16.3.2"
    assert package["devDependencies"]["jsdom"] == "27.4.0"


def test_project_context_uses_langgraph_long_term_store() -> None:
    settings = Settings(app_env="test", enable_persistence=False)
    context_manager = ProjectContextManager(settings=settings)

    context_manager.record_decision("memory-project", "Use a single frontend worker.")
    context = context_manager.load_context("memory-project")

    assert context.decisions == ["Use a single frontend worker."]


def test_project_context_persists_planning_memory_without_duplicates() -> None:
    settings = Settings(app_env="test", enable_persistence=False)
    context_manager = ProjectContextManager(settings=settings)

    context_manager.record_plan(
        "planning-memory-project",
        summary="Build a frontend only.",
        decisions=["capability:react-vite"],
        constraints=["excluded:database"],
    )
    context_manager.record_plan(
        "planning-memory-project",
        summary="Build a frontend only.",
        decisions=["capability:react-vite"],
        constraints=["excluded:database"],
    )
    context = context_manager.load_context("planning-memory-project")

    assert context.summary == "Build a frontend only."
    assert context.decisions == ["capability:react-vite"]
    assert context.constraints == ["excluded:database"]


def test_repeated_failed_patch_rolls_back_transactionally() -> None:
    job, task, manager = _frontend_job()
    task.attempt = 1
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Initial candidate",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.tsx",
                    "export const value = 'initial';\n",
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )
    initial_generation = job.manifest_generation
    original_ticket = RepairTicket(
        source="adapter_validation",
        worker_kind=WorkerKind.FRONTEND,
        category="test_failure",
        summary="Same assertion failed",
        fingerprint="stable-fingerprint",
        occurrence=1,
        strategy="targeted_patch",
    )
    job.add_repair_ticket(original_ticket)
    manager.begin_repair_transaction(job, {WorkerKind.FRONTEND})

    task.attempt = 2
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Ineffective candidate",
            operation="patch",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.tsx",
                    "export const value = 'ineffective';\n",
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )
    repeated_ticket = RepairTicket(
        source="adapter_validation",
        worker_kind=WorkerKind.FRONTEND,
        category="test_failure",
        summary="Same assertion still failed",
        fingerprint="stable-fingerprint",
        occurrence=2,
        strategy="escalated_patch",
    )

    rolled_back = manager.rollback_repeated_failure(job, [repeated_ticket])

    assert rolled_back
    assert job.manifest_generation == initial_generation + 1
    assert (
        job.manifest_state["files"]["frontend/src/App.tsx"]["content"]
        == "export const value = 'initial';\n"
    )
    assert task.attempt == 1
    assert task.repair_rejections == 1
    assert job.manifest_transaction == {}


def test_new_build_regression_rolls_back_without_spending_attempt() -> None:
    job, task, manager = _frontend_job()
    task.attempt = 2
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Test-failing checkpoint",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.tsx",
                    "export const status: string = 'test-failing';\n",
                    WorkerKind.FRONTEND,
                )
            ],
        ),
    )
    original_ticket = RepairTicket(
        source="adapter_validation",
        worker_kind=WorkerKind.FRONTEND,
        category="test_contract",
        summary="Expected forbidden message",
        fingerprint="test-fingerprint",
        occurrence=1,
        strategy="targeted_patch",
    )
    job.add_repair_ticket(original_ticket)
    manager.begin_repair_transaction(job, {WorkerKind.FRONTEND})
    task.attempt = 3
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Introduced a type regression",
            operation="patch",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.tsx",
                    "export const status: string = {};\n",
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
            summary="Candidate",
            attempt=3,
        )
    )
    regression_ticket = RepairTicket(
        source="adapter_validation",
        worker_kind=WorkerKind.FRONTEND,
        category="build",
        summary="TypeScript build failed",
        fingerprint="build-fingerprint",
        occurrence=1,
        strategy="targeted_patch",
    )
    job.add_repair_ticket(regression_ticket)

    rolled_back = manager.rollback_repeated_failure(job, [regression_ticket])

    assert rolled_back
    assert task.attempt == 2
    assert task.repair_rejections == 1
    assert (
        job.manifest_state["files"]["frontend/src/App.tsx"]["content"]
        == "export const status: string = 'test-failing';\n"
    )
    assert regression_ticket.resolved
    assert job.active_repair_ticket(WorkerKind.FRONTEND) is original_ticket
    assert job.worker_results[-1].status == TaskStatus.FAILED


def test_retry_replace_is_committed_as_non_destructive_patch() -> None:
    job, task, manager = _frontend_job()
    task.attempt = 1
    manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Initial",
            operation="replace",
            files=[
                GeneratedFileSpec(
                    "frontend/src/App.tsx", "export const app = true;\n", WorkerKind.FRONTEND
                ),
                GeneratedFileSpec("frontend/src/App.test.tsx", "export {};\n", WorkerKind.FRONTEND),
            ],
        ),
    )
    task.attempt = 2

    canonical = manager.commit(
        job,
        task,
        WorkerFileManifest(
            worker_kind=WorkerKind.FRONTEND,
            summary="Unsafe replacement",
            operation="replace",
            files=[
                GeneratedFileSpec("frontend/package.json", '{"name":"demo"}\n', WorkerKind.FRONTEND)
            ],
        ),
    )

    assert {file.path for file in canonical.files} == {
        "frontend/package.json",
        "frontend/src/App.test.tsx",
        "frontend/src/App.tsx",
    }
    assert job.manifest_state["task_manifests"][task.task_id]["operation"] == "patch"
