from dataclasses import dataclass, field

from software_developer_agent.config.settings import Settings
from software_developer_agent.memory.langgraph_memory import (
    LangGraphProjectMemory,
    project_memory,
)


@dataclass(slots=True)
class ProjectContext:
    project_id: str
    summary: str
    decisions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


class ProjectContextManager:
    def __init__(
        self,
        memory: LangGraphProjectMemory | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._memory = memory or (LangGraphProjectMemory(settings) if settings else project_memory)

    def load_context(self, project_id: str) -> ProjectContext:
        checkpoint = self._memory.checkpoint(project_id)
        return ProjectContext(
            project_id=checkpoint.project_id,
            summary=checkpoint.summary,
            decisions=checkpoint.decisions,
            constraints=checkpoint.constraints,
        )

    def record_decision(self, project_id: str, decision: str) -> None:
        self._memory.remember_decision(project_id, decision)

    def record_plan(
        self,
        project_id: str,
        *,
        summary: str,
        decisions: list[str],
        constraints: list[str],
    ) -> None:
        self._memory.remember_plan(
            project_id,
            summary=summary,
            decisions=decisions,
            constraints=constraints,
        )
