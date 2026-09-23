from dataclasses import dataclass


@dataclass(slots=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(slots=True)
class CostSnapshot:
    usage: TokenUsage
    estimated_cost_usd: float


class CostTracker:
    """Tracks token usage and estimated cost for a job run."""

    def __init__(self, input_cost_per_million: float = 0.15, output_cost_per_million: float = 0.60):
        self._usage = TokenUsage()
        self._input_cost_per_million = input_cost_per_million
        self._output_cost_per_million = output_cost_per_million

    def add_usage(self, usage: TokenUsage) -> None:
        self._usage.prompt_tokens += usage.prompt_tokens
        self._usage.completion_tokens += usage.completion_tokens
        self._usage.cached_prompt_tokens += usage.cached_prompt_tokens
        self._usage.reasoning_tokens += usage.reasoning_tokens

    def snapshot(self) -> CostSnapshot:
        cost = (
            self._usage.prompt_tokens / 1_000_000 * self._input_cost_per_million
            + self._usage.completion_tokens / 1_000_000 * self._output_cost_per_million
        )
        return CostSnapshot(usage=self._usage, estimated_cost_usd=round(cost, 8))
