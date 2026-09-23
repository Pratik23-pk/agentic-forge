from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(slots=True)
class ProjectFileSnapshot:
    path: str
    summary: str
    checksum: str | None = None


@dataclass(slots=True)
class ProjectState:
    project_id: str
    summary: str = ""
    files: list[ProjectFileSnapshot] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def remember_decision(self, decision: str) -> None:
        self.decisions.append(decision)
        self.updated_at = datetime.now(UTC)

    def remember_constraint(self, constraint: str) -> None:
        self.constraints.append(constraint)
        self.updated_at = datetime.now(UTC)
