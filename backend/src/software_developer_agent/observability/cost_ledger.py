from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil, floor

from software_developer_agent.config.settings import Settings
from software_developer_agent.models.job_state import JobState
from software_developer_agent.observability.cost_tracker import TokenUsage


class BudgetExceededError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_million: float
    cached_input_per_million: float
    output_per_million: float


MODEL_PRICES: dict[str, ModelPrice] = {
    "gpt-5.6-sol": ModelPrice(4.0, 0.4, 20.0),
    "gpt-5.6": ModelPrice(4.0, 0.4, 20.0),
    "gpt-5.6-terra": ModelPrice(2.0, 0.2, 12.0),
    "gpt-5.6-luna": ModelPrice(0.2, 0.02, 1.2),
    "gpt-5.4": ModelPrice(2.5, 0.25, 15.0),
    "gpt-5.4-mini": ModelPrice(0.75, 0.075, 4.5),
}

PROMPT_ESTIMATE_SAFETY_FACTOR = 1.2
BUDGET_RESERVE_RATIO = 0.02
MINIMUM_WORKER_OUTPUT_RATIO = 0.8


class GlobalCostLedger:
    """Persists model usage and enforces normal and repair dollar ceilings."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._normal_limit = settings.normal_run_budget_usd
        self._hard_limit = settings.maximum_run_budget_usd
        self._max_calls_per_node = settings.max_llm_calls_per_node

    def initialize(self, job: JobState) -> None:
        if job.cost_ledger:
            return
        profile = str(job.preflight.get("effective_profile", "standard"))
        authorized_limit = float(job.preflight.get("authorized_budget_usd", self._hard_limit))
        hard_limit = min(
            authorized_limit,
            (
                self._settings.maximum_advanced_run_budget_usd
                if profile == "advanced"
                else self._hard_limit
            ),
        )
        normal_limit = hard_limit if profile == "advanced" else min(self._normal_limit, hard_limit)
        job.cost_ledger = {
            "currency": "USD",
            "generation_profile": profile,
            "normal_limit_usd": normal_limit,
            "hard_limit_usd": hard_limit,
            "authorized_limit_usd": hard_limit,
            "budget_phase": "normal",
            "spent_usd": 0.0,
            "prompt_tokens": 0,
            "cached_prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "calls": [],
            "authorizations": {},
        }
        job.touch()

    def authorize(
        self,
        job: JobState,
        *,
        node: str,
        model: str,
        estimated_prompt_tokens: int,
        requested_output_tokens: int,
    ) -> int:
        self.initialize(job)
        authorizations = job.cost_ledger.setdefault("authorizations", {})
        node_authorizations = int(authorizations.get(node, 0))
        if node_authorizations >= self._max_calls_per_node:
            raise BudgetExceededError(
                f"Model-call limit exhausted for {node}; maximum is "
                f"{self._max_calls_per_node} calls per job."
            )
        price = _price_for_model(model)
        is_repair = node.startswith("repair.")
        if is_repair and job.cost_ledger.get("budget_phase") != "repair":
            job.cost_ledger["budget_phase"] = "repair"
            job.touch()
        elevated_phase = job.cost_ledger.get("budget_phase") in {
            "completion_reserve",
            "repair",
        }
        normal_limit = float(job.cost_ledger.get("normal_limit_usd", self._normal_limit))
        hard_limit = float(job.cost_ledger.get("hard_limit_usd", self._hard_limit))
        limit = hard_limit if elevated_phase else normal_limit
        spent = float(job.cost_ledger.get("spent_usd", 0.0))
        reserved_prompt_tokens = ceil(estimated_prompt_tokens * PROMPT_ESTIMATE_SAFETY_FACTOR)
        estimated_input = reserved_prompt_tokens / 1_000_000 * price.input_per_million
        budget_reserve = max(limit * BUDGET_RESERVE_RATIO, 0.002)
        remaining = limit - budget_reserve - spent - estimated_input
        affordable_output = floor(max(remaining, 0.0) / price.output_per_million * 1_000_000)
        minimum_worker_output = floor(requested_output_tokens * MINIMUM_WORKER_OUTPUT_RATIO)
        if (
            not elevated_phase
            and node.startswith("worker.")
            and len(job.tasks) >= 2
            and affordable_output < minimum_worker_output
            and hard_limit > normal_limit
        ):
            job.cost_ledger["budget_phase"] = "completion_reserve"
            job.touch()
            limit = hard_limit
            budget_reserve = max(limit * BUDGET_RESERVE_RATIO, 0.002)
            remaining = limit - budget_reserve - spent - estimated_input
            affordable_output = floor(
                max(remaining, 0.0) / price.output_per_million * 1_000_000
            )
        if remaining <= 0:
            raise BudgetExceededError(
                f"Cost budget exhausted before {node}; spent ${spent:.4f} of ${limit:.2f}."
            )
        allowed = min(requested_output_tokens, affordable_output)
        if allowed < 128:
            raise BudgetExceededError(
                f"Insufficient budget for a safe {node} response; ${remaining:.4f} remains."
            )
        authorizations[node] = node_authorizations + 1
        job.touch()
        return allowed

    def record(
        self,
        job: JobState,
        *,
        node: str,
        model: str,
        usage: TokenUsage,
    ) -> float:
        self.initialize(job)
        price = _price_for_model(model)
        cached = min(usage.cached_prompt_tokens, usage.prompt_tokens)
        uncached = max(usage.prompt_tokens - cached, 0)
        cost = (
            uncached / 1_000_000 * price.input_per_million
            + cached / 1_000_000 * price.cached_input_per_million
            + usage.completion_tokens / 1_000_000 * price.output_per_million
        )
        ledger = job.cost_ledger
        ledger["spent_usd"] = round(float(ledger.get("spent_usd", 0.0)) + cost, 8)
        for field in (
            "prompt_tokens",
            "cached_prompt_tokens",
            "completion_tokens",
            "reasoning_tokens",
        ):
            ledger[field] = int(ledger.get(field, 0)) + int(getattr(usage, field))
        ledger.setdefault("calls", []).append(
            {
                "node": node,
                "model": model,
                "usage": asdict(usage),
                "cost_usd": round(cost, 8),
            }
        )
        job.touch()
        return cost

    def hard_limit_reached(self, job: JobState) -> bool:
        self.initialize(job)
        hard_limit = float(job.cost_ledger.get("hard_limit_usd", self._hard_limit))
        return float(job.cost_ledger.get("spent_usd", 0.0)) >= hard_limit


def _price_for_model(model: str) -> ModelPrice:
    if model in MODEL_PRICES:
        return MODEL_PRICES[model]
    for model_id, price in MODEL_PRICES.items():
        if model.startswith(model_id):
            return price
    raise BudgetExceededError(f"No trusted pricing configuration exists for model {model!r}.")
