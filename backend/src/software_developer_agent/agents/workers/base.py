from abc import ABC, abstractmethod

from software_developer_agent.artifacts.file_manifest import (
    extract_worker_file_manifest,
    fallback_worker_manifest_json,
    normalize_worker_manifest,
    validate_worker_manifest_contract,
    validate_worker_manifest_scope,
    worker_file_manifest_json,
    worker_manifest_prompt,
    worker_manifest_source_syntax_failure,
)
from software_developer_agent.config.settings import Settings
from software_developer_agent.integrations.llm_client import LLMClient
from software_developer_agent.models.job_state import JobTask, TaskStatus, WorkerKind, WorkerResult
from software_developer_agent.prompts.system_prompts import get_worker_system_prompt
from software_developer_agent.tools.registry import ToolContext, ToolRegistry


class DeveloperWorker(ABC):
    worker_kind: WorkerKind

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        settings: Settings | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._settings = settings
        self._llm_client = llm_client

    def run(self, task: JobTask) -> WorkerResult:
        task.status = TaskStatus.RUNNING
        tool_context = None
        manifest = None
        errors: list[str] = []
        candidate_attempt = task.attempt + 1
        original_instructions = task.instructions
        if self._tool_registry is not None:
            if task.tool_context is not None:
                tool_context = ToolContext(
                    content=task.tool_context,
                    calls=list(task.tool_calls),
                )
            else:
                try:
                    tool_context = self._tool_registry.collect_context(task)
                    task.tool_context = tool_context.content
                    task.tool_calls = list(tool_context.calls)
                except Exception as exc:
                    errors.append(f"Tool context failed: {exc}")
        recovery_attempts = self._settings.max_manifest_recovery_attempts if self._settings else 0
        for recovery_index in range(recovery_attempts + 1):
            task.transport_attempts += 1
            if recovery_index:
                correction = errors[-1][:1_200] if errors else "The manifest contract was invalid."
                task.instructions = (
                    original_instructions
                    + "\n\nInternal response correction:\n"
                    + f"Correct exactly this defect: {correction}\n"
                    + "Return one valid JSON manifest only. On initial generation return the complete "
                    + "owned component; on repair return operation=patch with only the necessary "
                    + "changes. This internal contract correction does not consume the project "
                    + "execution budget."
                )
            try:
                output = self.execute(task, tool_context.content if tool_context else "")
                manifest = extract_worker_file_manifest(output, self.worker_kind)
                if not manifest.files:
                    raise ValueError(
                        "Worker did not return a valid file manifest with at least one file."
                    )
                validate_worker_manifest_scope(manifest)
                manifest = normalize_worker_manifest(manifest, task.capability_id)
                if task.attempt > 0 and manifest.operation != "patch":
                    raise ValueError(
                        "Repair output must use operation=patch; full replacement is forbidden."
                    )
                if task.attempt == 0 and manifest.operation is None:
                    manifest.operation = "replace"
                if task.attempt == 0 and manifest.operation != "replace":
                    raise ValueError(
                        "Initial output must use operation=replace with the complete component."
                    )
                validate_worker_manifest_contract(manifest, task.capability_id)
                syntax_failure = worker_manifest_source_syntax_failure(manifest)
                if syntax_failure:
                    raise ValueError(syntax_failure)
                output = worker_file_manifest_json(manifest)
                break
            except Exception as exc:
                errors.append(str(exc))
                manifest = None
                if _terminal_manifest_recovery_error(exc):
                    break
            finally:
                task.instructions = original_instructions

        if manifest is None:
            if (
                self._settings
                and self._settings.enable_guaranteed_artifact_fallback
                and task.attempt == 0
            ):
                project_prompt = (
                    _extract_instruction_value(original_instructions, "Request")
                    or original_instructions
                )
                project_id = (
                    _extract_instruction_value(original_instructions, "Project")
                    or "generated-project"
                )
                output = fallback_worker_manifest_json(task, project_prompt, project_id)
                manifest = extract_worker_file_manifest(output, self.worker_kind)
                validate_worker_manifest_scope(manifest)
                manifest = normalize_worker_manifest(manifest, task.capability_id)
                validate_worker_manifest_contract(manifest, task.capability_id)
                syntax_failure = worker_manifest_source_syntax_failure(manifest)
                if syntax_failure:
                    raise ValueError(syntax_failure)
                task.status = TaskStatus.SUCCEEDED
                return WorkerResult(
                    task_id=task.task_id,
                    worker_kind=self.worker_kind,
                    status=TaskStatus.SUCCEEDED,
                    summary=(
                        f"{self.worker_kind.value} worker response failed; a certified runnable "
                        "checkpoint was created for targeted repair."
                    ),
                    output=worker_file_manifest_json(manifest),
                    errors=errors[-3:],
                    artifacts=[file.path for file in manifest.files],
                    tool_calls=tool_context.calls if tool_context else [],
                    attempt=candidate_attempt,
                    used_fallback=True,
                )
            task.status = TaskStatus.FAILED
            return WorkerResult(
                task_id=task.task_id,
                worker_kind=self.worker_kind,
                status=TaskStatus.FAILED,
                summary=f"{self.worker_kind.value} worker failed.",
                errors=errors[-3:],
                attempt=candidate_attempt,
            )

        task.status = TaskStatus.SUCCEEDED
        return WorkerResult(
            task_id=task.task_id,
            worker_kind=self.worker_kind,
            status=TaskStatus.SUCCEEDED,
            summary=manifest.summary or f"{self.worker_kind.value} worker completed.",
            output=output,
            artifacts=[file.path for file in manifest.files],
            tool_calls=tool_context.calls if tool_context else [],
            attempt=candidate_attempt,
        )

    @abstractmethod
    def execute(self, task: JobTask, tool_context: str = "") -> str: ...

    def complete_or_fallback(self, task: JobTask, tool_context: str, fallback: str) -> str:
        if not self._settings or not self._settings.enable_llm_calls or self._llm_client is None:
            if self._settings and self._settings.app_env == "test":
                return fallback
            raise RuntimeError(
                "Runnable project generation requires ENABLE_LLM_CALLS=true and "
                "a configured OPENAI_API_KEY."
            )
        project_prompt = (
            _extract_instruction_value(task.instructions, "Request") or task.instructions
        )
        project_id = _extract_instruction_value(task.instructions, "Project") or "generated-project"
        user = (
            worker_manifest_prompt(task, project_prompt, project_id)
            + "\n\nTool evidence:\n"
            + (tool_context or "None")
        )
        response = self._llm_client.complete(
            get_worker_system_prompt(
                self.worker_kind,
                task.capability_id,
                task.adapter_ids,
            ),
            user,
        )
        return response.text


def _extract_instruction_value(instructions: str, label: str) -> str | None:
    prefix = f"{label}:"
    for line in instructions.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return None


def _terminal_manifest_recovery_error(error: Exception) -> bool:
    lowered = str(error).lower()
    return any(
        marker in lowered
        for marker in (
            "cost budget exhausted",
            "insufficient budget for a safe",
            "max_output_tokens",
            "model-call limit exhausted",
        )
    )
