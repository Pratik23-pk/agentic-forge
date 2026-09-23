from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from software_developer_agent.artifacts.file_manifest import (
    ManifestConflictError,
    WorkerFileManifest,
    checkpointed_worker_file_manifests,
)
from software_developer_agent.config.settings import Settings
from software_developer_agent.memory.langgraph_memory import open_langgraph_resources
from software_developer_agent.models.job_state import (
    JobState,
    JobTask,
    RepairTicket,
    TaskStatus,
    WorkerKind,
)


def merge_file_records(
    current: dict[str, dict[str, Any]] | None,
    updates: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Associatively keep the highest-attempt record for every generated path."""

    merged = dict(current or {})
    for path, candidate in (updates or {}).items():
        existing = merged.get(path)
        if existing is None or _record_order(candidate) >= _record_order(existing):
            merged[path] = dict(candidate)
    return merged


def merge_task_records(
    current: dict[str, dict[str, Any]] | None,
    updates: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    merged = dict(current or {})
    for task_id, candidate in (updates or {}).items():
        existing = merged.get(task_id)
        if existing is None or int(candidate.get("attempt", 0)) >= int(existing.get("attempt", 0)):
            merged[task_id] = dict(candidate)
    return merged


class ManifestGraphState(TypedDict, total=False):
    job_id: str
    project_id: str
    revision: int
    files: Annotated[dict[str, dict[str, Any]], merge_file_records]
    task_manifests: Annotated[dict[str, dict[str, Any]], merge_task_records]


def _checkpoint_node(_: ManifestGraphState) -> dict[str, Any]:
    return {}


def _build_graph(checkpointer, store):
    builder = StateGraph(ManifestGraphState)
    builder.add_node("checkpoint_manifest", _checkpoint_node)
    builder.add_edge(START, "checkpoint_manifest")
    builder.add_edge("checkpoint_manifest", END)
    return builder.compile(checkpointer=checkpointer, store=store)


class ManifestCheckpointManager:
    """Canonical generated-file state with LangGraph checkpoint and Store durability."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def restore(self, job: JobState) -> dict[str, Any]:
        if not self._settings.enable_langgraph_checkpointing:
            return job.manifest_state
        with open_langgraph_resources(self._settings) as (checkpointer, store):
            graph = _build_graph(checkpointer, store)
            config = _thread_config(job)
            snapshot = graph.get_state(config)
            checkpoint_state = dict(snapshot.values) if snapshot.values else {}
            checkpoint_is_stale = int(job.manifest_state.get("revision", 0)) > int(
                checkpoint_state.get("revision", 0)
            )
            if job.manifest_state and (not checkpoint_state or checkpoint_is_stale):
                checkpoint_state = dict(graph.invoke(job.manifest_state, config))
            if checkpoint_state:
                job.manifest_state = checkpoint_state
                self._store_snapshot(store, job, checkpoint_state)
            return checkpoint_state

    def commit(
        self,
        job: JobState,
        task: JobTask,
        manifest: WorkerFileManifest,
    ) -> WorkerFileManifest:
        previous = self.restore(job)
        update = self._manifest_update(job, previous, task, manifest)
        if self._settings.enable_langgraph_checkpointing:
            with open_langgraph_resources(self._settings) as (checkpointer, store):
                graph = _build_graph(checkpointer, store)
                state = dict(graph.invoke(update, _thread_config(job)))
                self._store_snapshot(store, job, state)
        else:
            state = _apply_without_graph(previous, update)
        job.manifest_state = state
        canonical = next(
            (
                item
                for item in checkpointed_worker_file_manifests(job)
                if item.worker_kind == task.worker_kind
            ),
            manifest,
        )
        canonical.operation = "replace"
        return canonical

    @staticmethod
    def reset(job: JobState) -> None:
        job.manifest_generation += 1
        job.manifest_state = {}
        job.verified_manifest_state = {}
        job.verified_validation = {}
        job.manifest_transaction = {}
        job.touch()

    @staticmethod
    def mark_verified(job: JobState, validation: dict[str, Any]) -> None:
        if not job.manifest_state:
            return
        job.verified_manifest_state = deepcopy(job.manifest_state)
        job.verified_validation = deepcopy(validation)
        job.touch()

    @staticmethod
    def restore_verified(job: JobState) -> bool:
        if not job.verified_manifest_state:
            return False
        job.manifest_generation += 1
        job.manifest_state = deepcopy(job.verified_manifest_state)
        job.manifest_transaction = {}
        job.touch()
        return True

    @staticmethod
    def begin_repair_transaction(job: JobState, targets: set[WorkerKind]) -> None:
        if job.manifest_transaction or not job.manifest_state:
            return
        fingerprints = {
            worker_kind.value: ticket.fingerprint
            for worker_kind in targets
            if (ticket := job.active_repair_ticket(worker_kind)) is not None
        }
        if not fingerprints:
            return
        job.manifest_transaction = {
            "base": deepcopy(job.manifest_state),
            "fingerprints": fingerprints,
            "categories": {
                worker_kind.value: ticket.category
                for worker_kind in targets
                if (ticket := job.active_repair_ticket(worker_kind)) is not None
            },
            "ticket_ids": {
                worker_kind.value: ticket.ticket_id
                for worker_kind in targets
                if (ticket := job.active_repair_ticket(worker_kind)) is not None
            },
            "task_attempts": {
                task.worker_kind.value: task.attempt
                for task in job.tasks
                if task.worker_kind in targets
            },
        }
        job.touch()

    def rollback_repeated_failure(
        self,
        job: JobState,
        tickets: list[RepairTicket],
    ) -> bool:
        transaction = job.manifest_transaction
        if not transaction:
            return False
        fingerprints = transaction.get("fingerprints", {})
        repeated = any(
            fingerprints.get(ticket.worker_kind.value) == ticket.fingerprint for ticket in tickets
        )
        previous_categories = transaction.get("categories", {})
        introduced_regression = any(
            ticket.category in {"build", "dependency", "worker_output"}
            and previous_categories.get(ticket.worker_kind.value) not in {
                None,
                ticket.category,
            }
            for ticket in tickets
        )
        if not repeated and not introduced_regression:
            job.manifest_transaction = {}
            job.touch()
            return False
        base = transaction.get("base")
        if not isinstance(base, dict) or not base:
            job.manifest_transaction = {}
            return False
        job.manifest_generation += 1
        job.manifest_state = deepcopy(base)
        task_attempts = transaction.get("task_attempts", {})
        ticket_ids = transaction.get("ticket_ids", {})
        for task in job.tasks:
            previous_attempt = task_attempts.get(task.worker_kind.value)
            if previous_attempt is None:
                continue
            task.attempt = int(previous_attempt)
            task.repair_rejections += 1
            latest_result = next(
                (
                    result
                    for result in reversed(job.worker_results)
                    if result.task_id == task.task_id and result.attempt > task.attempt
                ),
                None,
            )
            if latest_result is not None:
                latest_result.status = TaskStatus.FAILED
                latest_result.errors.append(
                    "Repair checkpoint rolled back because validation repeated the original "
                    "failure or introduced a compile, dependency, or worker-output regression."
                )
        if introduced_regression:
            for ticket in tickets:
                previous_ticket_id = ticket_ids.get(ticket.worker_kind.value)
                if previous_ticket_id is None:
                    continue
                ticket.resolved = True
                job.active_repair_ticket_ids[ticket.worker_kind.value] = previous_ticket_id
        job.manifest_transaction = {}
        if self._settings.enable_langgraph_checkpointing:
            with open_langgraph_resources(self._settings) as (checkpointer, store):
                graph = _build_graph(checkpointer, store)
                state = dict(graph.invoke(job.manifest_state, _thread_config(job)))
                job.manifest_state = state
                self._store_snapshot(store, job, state)
        job.touch()
        return True

    @staticmethod
    def complete_repair_transaction(job: JobState) -> None:
        if job.manifest_transaction:
            job.manifest_transaction = {}
            job.touch()

    @staticmethod
    def repair_context(job: JobState, task: JobTask) -> str:
        if not job.manifest_state:
            return "No prior generated files are available. Return a complete replacement manifest."
        active_records = [
            (path, record)
            for path, record in sorted(job.manifest_state.get("files", {}).items())
            if isinstance(record, dict) and not record.get("deleted", False)
        ]
        ticket = job.active_repair_ticket(task.worker_kind)
        owned_records = [
            (path, record)
            for path, record in active_records
            if record.get("worker_kind") == task.worker_kind.value
        ]
        content_paths = {path for path, _ in owned_records}
        content_scope = ["target_component"]
        if not owned_records:
            content_paths.update(path for path, _ in active_records)
            content_scope = ["unaccepted_component_bootstrap"]
        elif task.worker_kind == WorkerKind.BACKEND:
            content_paths.update(
                path
                for path, record in active_records
                if record.get("worker_kind") == WorkerKind.DATABASE.value
            )
            content_scope.append("database_contract")
        elif task.worker_kind == WorkerKind.FRONTEND and ticket is not None and ticket.category in {
            "integration",
            "runtime",
        }:
            content_paths.update(
                path
                for path, record in active_records
                if record.get("worker_kind") == WorkerKind.BACKEND.value
            )
            content_scope.append("backend_contract")
        if ticket is not None:
            content_paths.update(ticket.target_files)

        files = []
        project_file_index = []
        for path, record in active_records:
            project_file_index.append(
                {
                    "path": path,
                    "owner": record.get("worker_kind"),
                    "checksum": record.get("checksum"),
                    "characters": len(str(record.get("content", ""))),
                }
            )
            if path not in content_paths:
                continue
            if not isinstance(record, dict) or record.get("deleted", False):
                continue
            files.append(
                {
                    "path": path,
                    "content": record.get("content", ""),
                    "owner": record.get("worker_kind"),
                    "checksum": record.get("checksum"),
                }
            )
        final_or_rejected_repair = bool(
            task.attempt + 1 >= task.max_attempts
            or task.repair_rejections
            or ticket is not None
            and ticket.strategy == "final_patch"
        )
        upgrading_certified_fallback = any(
            result.task_id == task.task_id
            and result.used_fallback
            and result.status == TaskStatus.SUCCEEDED
            and result.attempt == task.attempt
            for result in reversed(job.worker_results)
        )
        response_contract = (
            "Return operation=patch with only materially changed or new files. "
            if task.attempt > 0
            else "Your component has no accepted attempt yet. Return operation=replace with "
            "its complete runtime contracts, entry point, implementation, and focused tests. "
        )
        payload = {
            "instructions": (
                "The complete canonical project remains preserved in the LangGraph checkpoint. "
                "files contains the full target component plus any directly coupled contracts; "
                "project_file_index is the complete immutable inventory of every other checkpointed "
                "file. Preserve every unchanged file and all user-visible requirements. Diagnose "
                "the supplied evidence and correct the root cause with the smallest sufficient change. "
                + response_contract
                + "Never "
                "replace the product with a generic template, weaken valid tests, or alter "
                "dependencies and configuration without direct evidence. Do not claim completion "
                "unless the exact failed command and the full project validation would pass."
            ),
            "target_worker": task.worker_kind.value,
            "execution_budget": {
                "completed_attempts": task.attempt,
                "maximum_attempts": task.max_attempts,
                "final_attempt": task.attempt + 1 >= task.max_attempts,
            },
            "files": files,
            "content_scope": content_scope,
            "project_file_index": project_file_index,
        }
        if upgrading_certified_fallback:
            payload["certified_fallback_upgrade"] = True
            payload["instructions"] += (
                " This checkpoint is only a certified runnable fallback, not the requested product. "
                "Upgrade the entire owned component now: audit every original requirement, planner "
                "contract, selected adapter, route, environment variable, runtime surface, test, and "
                "build contract, then return one coherent patch containing all required product files. "
                "Do not limit this repair to the first reported blocker or preserve fallback placeholder "
                "behavior. Preserve only valid runtime scaffolding and satisfy the complete component in "
                "this single attempt."
            )
        if final_or_rejected_repair:
            payload["instructions"] += (
                " This is a near-final or previously rejected repair. Before responding, perform "
                "one bounded consistency audit across the directly coupled implementation, tests, "
                "API contracts, dependency declarations, and configuration named by the evidence; "
                "fix every discovered cause in one coherent patch without redesigning unrelated "
                "features."
            )
        latest_rejection = next(
            (
                error
                for result in reversed(job.worker_results)
                if result.task_id == task.task_id and result.status.value == "failed"
                for error in reversed(result.errors)
                if error
            ),
            None,
        )
        if latest_rejection:
            payload["previous_candidate_rejection"] = latest_rejection
            payload["instructions"] += (
                " The immediately previous candidate was rejected for the exact reason in "
                "previous_candidate_rejection. Correct that reason explicitly; do not repeat "
                "the same patch or modify unrelated files."
            )
        if ticket is not None:
            payload["repair_ticket"] = {
                "ticket_id": ticket.ticket_id,
                "source": ticket.source,
                "category": ticket.category,
                "summary": ticket.summary,
                "fingerprint": ticket.fingerprint,
                "occurrence": ticket.occurrence,
                "strategy": ticket.strategy,
                "validation_name": ticket.validation_name,
                "command": ticket.command,
                "target_files": ticket.target_files,
                "line": ticket.line,
                "expected": ticket.expected,
                "actual": ticket.actual,
                "evidence": ticket.evidence,
                "allowed_paths": ticket.allowed_paths,
                "adapter_ids": ticket.adapter_ids,
            }
            if ticket.category in {"test_contract", "test_failure"}:
                payload["instructions"] += (
                    " Reproduce the cited failing test scenario step by step, follow the runtime "
                    "call path, and correct the implementation root cause. Resolve every distinct "
                    "failing scenario present in the supplied evidence in the same coherent patch; "
                    "do not stop after the first assertion. Treat a test that "
                    "asserts requested behavior as authoritative; do not remove, skip, loosen, or "
                    "rewrite it merely to make the command pass."
                )
        return json.dumps(
            payload,
            separators=(",", ":"),
        )

    @staticmethod
    def upstream_generation_context(job: JobState, task: JobTask) -> str | None:
        if task.worker_kind != WorkerKind.BACKEND or not job.manifest_state:
            return None
        files = [
            {
                "path": path,
                "content": record.get("content", ""),
                "checksum": record.get("checksum"),
            }
            for path, record in sorted(job.manifest_state.get("files", {}).items())
            if isinstance(record, dict)
            and not record.get("deleted", False)
            and record.get("worker_kind") == WorkerKind.DATABASE.value
        ]
        if not files:
            return None
        return json.dumps(
            {
                "instructions": (
                    "This is accepted upstream database-worker output, not a repair request. "
                    "Return operation=replace for the complete backend. Treat these files as the "
                    "canonical persistence contract: match their entities, columns, enums, keys, "
                    "constraints, and seed identities exactly. Do not create Alembic or any second "
                    "executable migration or seed system."
                ),
                "upstream_worker": WorkerKind.DATABASE.value,
                "files": files,
            },
            separators=(",", ":"),
        )

    def _manifest_update(
        self,
        job: JobState,
        previous: dict[str, Any],
        task: JobTask,
        manifest: WorkerFileManifest,
    ) -> ManifestGraphState:
        previous_files = previous.get("files", {})
        next_revision = int(previous.get("revision", 0)) + 1
        has_previous_for_task = any(
            isinstance(record, dict)
            and record.get("task_id") == task.task_id
            and not record.get("deleted", False)
            for record in previous_files.values()
        )
        operation = manifest.operation or ("patch" if has_previous_for_task else "replace")
        if has_previous_for_task:
            operation = "patch"
        file_updates: dict[str, dict[str, Any]] = {}
        new_paths = {file.path for file in manifest.files}
        deleted_paths = set(manifest.deleted_files)
        if operation == "replace":
            deleted_paths.update(
                path
                for path, record in previous_files.items()
                if isinstance(record, dict)
                and record.get("task_id") == task.task_id
                and path not in new_paths
                and not record.get("deleted", False)
            )

        conflicts: dict[str, set] = {}
        for file in manifest.files:
            existing = previous_files.get(file.path)
            if (
                isinstance(existing, dict)
                and not existing.get("deleted", False)
                and existing.get("task_id") not in {None, task.task_id}
                and existing.get("content") != file.content
            ):
                conflicts[file.path] = {
                    task.worker_kind,
                    _worker_kind(existing.get("worker_kind"), task.worker_kind),
                }
                continue
            file_updates[file.path] = _file_record(
                path=file.path,
                content=file.content,
                task=task,
                deleted=False,
                revision=next_revision,
            )
        if conflicts:
            raise ManifestConflictError(conflicts)

        for path in deleted_paths:
            existing = previous_files.get(path, {})
            if isinstance(existing, dict) and existing.get("task_id") not in {None, task.task_id}:
                continue
            file_updates[path] = _file_record(
                path=path,
                content="",
                task=task,
                deleted=True,
                revision=next_revision,
            )

        return ManifestGraphState(
            job_id=job.job_id,
            project_id=job.request.project_id,
            revision=next_revision,
            files=file_updates,
            task_manifests={
                task.task_id: {
                    "worker_kind": task.worker_kind.value,
                    "attempt": task.attempt,
                    "revision": next_revision,
                    "operation": operation,
                    "summary": manifest.summary,
                    "validation_commands": manifest.validation_commands,
                    "notes": manifest.notes,
                }
            },
        )

    @staticmethod
    def _store_snapshot(store, job: JobState, state: dict[str, Any]) -> None:
        namespace = ("agentic-forge-manifests", sha256(job.request.project_id.encode()).hexdigest())
        store.put(namespace, f"{job.job_id}:{job.manifest_generation}", state)


def _thread_config(job: JobState) -> dict[str, dict[str, str]]:
    return {
        "configurable": {
            "thread_id": f"{job.job_id}:{job.manifest_generation}",
        }
    }


def _file_record(
    *,
    path: str,
    content: str,
    task: JobTask,
    deleted: bool,
    revision: int,
) -> dict[str, Any]:
    return {
        "path": path,
        "content": content,
        "worker_kind": task.worker_kind.value,
        "task_id": task.task_id,
        "attempt": task.attempt,
        "revision": revision,
        "checksum": sha256(content.encode("utf-8")).hexdigest(),
        "deleted": deleted,
    }


def _record_order(record: dict[str, Any]) -> tuple[int, int, str]:
    attempt = int(record.get("attempt", 0))
    return (
        int(record.get("revision", attempt)),
        attempt,
        str(record.get("checksum", "")),
    )


def _worker_kind(value: Any, fallback):
    from software_developer_agent.models.job_state import WorkerKind

    try:
        return WorkerKind(str(value))
    except ValueError:
        return fallback


def _apply_without_graph(
    previous: dict[str, Any],
    update: ManifestGraphState,
) -> dict[str, Any]:
    return {
        "job_id": update.get("job_id") or previous.get("job_id", ""),
        "project_id": update.get("project_id") or previous.get("project_id", ""),
        "revision": update.get("revision", previous.get("revision", 0)),
        "files": merge_file_records(previous.get("files"), update.get("files")),
        "task_manifests": merge_task_records(
            previous.get("task_manifests"), update.get("task_manifests")
        ),
    }
