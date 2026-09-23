from dataclasses import dataclass, field

from software_developer_agent.models.job_state import TaskStatus, WorkerKind


@dataclass(slots=True)
class AgentResult:
    agent_name: str
    status: TaskStatus
    summary: str
    worker_kind: WorkerKind | None = None
    output: str = ""
    errors: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
