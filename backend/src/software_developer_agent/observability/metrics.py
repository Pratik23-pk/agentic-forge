from dataclasses import asdict, dataclass, field
from threading import Lock
from time import time


@dataclass(slots=True)
class MetricsSnapshot:
    jobs_submitted: int = 0
    jobs_succeeded: int = 0
    jobs_failed: int = 0
    retries_scheduled: int = 0
    guardrail_blocks: int = 0
    prohibited_requests: int = 0
    human_checkpoints_created: int = 0
    human_feedback_approved: int = 0
    human_feedback_changes_requested: int = 0
    mcp_tool_calls: int = 0
    started_at: float = field(default_factory=time)


class InMemoryMetrics:
    """Small process-local metrics collector for development and tests."""

    def __init__(self) -> None:
        self._snapshot = MetricsSnapshot()
        self._lock = Lock()

    def increment(self, field_name: str, amount: int = 1) -> None:
        with self._lock:
            current = getattr(self._snapshot, field_name)
            setattr(self._snapshot, field_name, current + amount)

    def snapshot(self) -> MetricsSnapshot:
        with self._lock:
            return MetricsSnapshot(**asdict(self._snapshot))


metrics = InMemoryMetrics()
