from software_developer_agent.agents.workers.base import DeveloperWorker
from software_developer_agent.artifacts.file_manifest import fallback_worker_manifest_json
from software_developer_agent.models.job_state import JobTask, WorkerKind


class FrontendDeveloperAgent(DeveloperWorker):
    worker_kind = WorkerKind.FRONTEND

    def execute(self, task: JobTask, tool_context: str = "") -> str:
        project_prompt = (
            _extract_instruction_value(task.instructions, "Request") or task.instructions
        )
        project_id = _extract_instruction_value(task.instructions, "Project") or "generated-project"
        fallback = fallback_worker_manifest_json(task, project_prompt, project_id)
        return self.complete_or_fallback(task, tool_context, fallback)


def _extract_instruction_value(instructions: str, label: str) -> str | None:
    prefix = f"{label}:"
    for line in instructions.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return None
