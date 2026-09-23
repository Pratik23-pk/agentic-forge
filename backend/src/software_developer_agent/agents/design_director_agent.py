from __future__ import annotations

import json
import logging
from typing import Any

from software_developer_agent.config.settings import Settings
from software_developer_agent.integrations.llm_client import LLMClient
from software_developer_agent.models.job_state import JobState
from software_developer_agent.prompts.system_prompts import DESIGN_DIRECTOR_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class DesignDirectorAgent:
    """Creates a compact quality contract before implementation begins."""

    def __init__(self, settings: Settings, llm_client: LLMClient | None = None) -> None:
        self._settings = settings
        self._llm_client = llm_client

    def create_spec(self, job: JobState) -> dict[str, Any]:
        if self._settings.enable_llm_calls and self._llm_client is not None:
            try:
                return self._create_with_llm(job)
            except Exception:
                logger.exception("design_director.llm_invalid")
                job.warnings.append(
                    "The model-generated visual contract was invalid; a deterministic quality "
                    "contract was applied so generation could continue."
                )
                job.touch()
        return _deterministic_spec(job)

    def _create_with_llm(self, job: JobState) -> dict[str, Any]:
        user = (
            "Return the required JSON only.\n"
            f"Request: {job.request.prompt}\n"
            f"Project specification: {json.dumps(job.project_spec, sort_keys=True)}\n"
            f"API contract: {json.dumps(job.api_contract, sort_keys=True)}\n"
            f"Planned workers: {json.dumps([task.worker_kind.value for task in job.tasks])}"
        )
        assert self._llm_client is not None
        response = self._llm_client.complete(DESIGN_DIRECTOR_SYSTEM_PROMPT, user)
        payload = json.loads(_extract_json(response.text))
        _validate_spec(payload)
        return payload


def _deterministic_spec(job: JobState) -> dict[str, Any]:
    frontend_required = any(task.worker_kind.value == "frontend" for task in job.tasks)
    return {
        "product_summary": job.request.prompt.strip()[:500],
        "experience_goal": (
            "A polished, focused, responsive product experience."
            if frontend_required
            else "A reliable developer-facing service experience."
        ),
        "visual_direction": {
            "tone": "premium, minimal, content-led",
            "theme": "adaptive dark and light surfaces",
            "typography": "clear display hierarchy with highly readable body text",
            "color_strategy": "restrained neutral foundation with one contextual accent",
            "motion": "purposeful micro-interactions with reduced-motion support",
        },
        "primary_surfaces": ["primary workflow", "loading state", "empty state", "error state"],
        "interaction_requirements": [
            "Keyboard-accessible controls",
            "Responsive behavior from mobile through desktop",
            "Visible feedback for every user action",
        ],
        "quality_criteria": [
            "No placeholder or template-like presentation",
            "Strong first-screen hierarchy",
            "Consistent spacing, type, color, and interaction tokens",
            "Real requested content and media with accessible alternatives",
        ],
    }


def _validate_spec(payload: dict[str, Any]) -> None:
    required = {
        "product_summary",
        "experience_goal",
        "visual_direction",
        "primary_surfaces",
        "interaction_requirements",
        "quality_criteria",
    }
    if not required.issubset(payload):
        raise ValueError("Design director response omitted required contract fields.")
    if not isinstance(payload["visual_direction"], dict):
        raise TypeError("Design visual_direction must be an object.")
    for key in ("primary_surfaces", "interaction_requirements", "quality_criteria"):
        if not isinstance(payload[key], list) or not payload[key]:
            raise TypeError(f"Design {key} must be a non-empty list.")


def _extract_json(text: str) -> str:
    stripped = text.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in design response.")
    return stripped[start : end + 1]
