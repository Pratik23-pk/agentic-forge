from dataclasses import dataclass, field
from typing import Any, Literal

ToolStatus = Literal["succeeded", "failed", "skipped"]


@dataclass(slots=True)
class ToolResult:
    tool_name: str
    status: ToolStatus
    input_summary: str
    output_summary: str = ""
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "tool": self.tool_name,
            "status": self.status,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "metadata": self.metadata,
        }
