from __future__ import annotations

from enum import StrEnum
from typing import Any

from software_developer_agent.capabilities.registry import resolve_project_spec
from software_developer_agent.config.settings import Settings
from software_developer_agent.models.job_state import JobState
from software_developer_agent.models.request_policy import derive_request_policy


class GenerationProfile(StrEnum):
    AUTO = "auto"
    STANDARD = "standard"
    ADVANCED = "advanced"


_ADVANCED_CAPABILITIES = {
    "authentication",
    "database",
    "deployment",
    "payments",
    "persistence",
}
_ADVANCED_ADAPTERS = {
    "auth-rbac",
    "commerce",
    "file-upload",
    "multi-tenant",
    "realtime",
    "video-platform",
}


def prepare_job_preflight(job: JobState, settings: Settings) -> dict[str, Any]:
    if job.preflight:
        return job.preflight

    requested = _profile(job.request.metadata.get("generation_profile", "auto"))
    policy = derive_request_policy(job.request.prompt)
    project_spec = resolve_project_spec(job.request.prompt, job.request.metadata, policy)
    uploaded_assets = _uploaded_assets(job.request.metadata)
    image_count = sum(1 for asset in uploaded_assets if asset.get("kind") == "image")
    video_count = sum(1 for asset in uploaded_assets if asset.get("kind") == "video")
    capability_signals = sorted(set(policy.requested_capabilities) & _ADVANCED_CAPABILITIES)
    adapter_signals = sorted(set(project_spec.adapter_ids) & _ADVANCED_ADAPTERS)
    advanced_signals = [*capability_signals, *adapter_signals]
    capability_weight = len(capability_signals)
    complexity_score = min(
        10,
        capability_weight * 2
        + min(len(adapter_signals), 3)
        + min(video_count * 2, 4)
        + (1 if image_count >= 4 else 0)
        + (1 if len(project_spec.adapter_ids) >= 2 else 0),
    )
    recommended = (
        GenerationProfile.ADVANCED
        if complexity_score >= 4 or video_count >= 2
        else GenerationProfile.STANDARD
    )
    effective = recommended if requested == GenerationProfile.AUTO else requested
    authorized = _authorized_budget(job, settings, effective)
    estimate = _estimate_cost_range(effective, complexity_score, image_count, video_count)
    warnings: list[str] = []
    if requested == GenerationProfile.STANDARD and recommended == GenerationProfile.ADVANCED:
        warnings.append(
            "The request has advanced complexity signals. Standard mode will preserve scope but "
            "use tighter research, reasoning, and repair budgets."
        )
    if estimate[1] > authorized:
        warnings.append(
            "The estimated upper range exceeds the approved ceiling. The workflow will optimize "
            "and pause safely rather than spend beyond the authorization."
        )

    job.request_policy = policy.to_dict()
    job.project_spec = project_spec.to_dict()
    job.request.metadata["generation_profile"] = requested.value
    job.request.metadata["effective_generation_profile"] = effective.value
    job.request.metadata["authorized_budget_usd"] = authorized
    job.preflight = {
        "requested_profile": requested.value,
        "recommended_profile": recommended.value,
        "effective_profile": effective.value,
        "authorized_budget_usd": authorized,
        "estimated_cost_usd": {"minimum": estimate[0], "maximum": estimate[1]},
        "complexity_score": complexity_score,
        "signals": advanced_signals,
        "uploaded_media": {"images": image_count, "videos": video_count},
        "requested_capabilities": sorted(policy.requested_capabilities),
        "warnings": warnings,
        "approval_required": True,
    }
    job.warnings.extend(warning for warning in warnings if warning not in job.warnings)
    job.touch()
    return job.preflight


def validate_budget_request(
    profile: str,
    budget: float | None,
    settings: Settings,
) -> float:
    selected = _profile(profile)
    default = (
        settings.default_advanced_run_budget_usd
        if selected == GenerationProfile.ADVANCED
        else settings.maximum_run_budget_usd
    )
    authorized = round(float(default if budget is None else budget), 2)
    maximum = (
        settings.maximum_run_budget_usd
        if selected == GenerationProfile.STANDARD
        else settings.maximum_advanced_run_budget_usd
    )
    if authorized <= 0 or authorized > maximum:
        raise ValueError(
            f"{selected.value.title()} mode requires a budget above $0 and no more than "
            f"${maximum:.2f}."
        )
    return authorized


def is_advanced_job(job: JobState) -> bool:
    return job.preflight.get("effective_profile") == GenerationProfile.ADVANCED.value


def _profile(value: object) -> GenerationProfile:
    try:
        return GenerationProfile(str(value).strip().lower())
    except ValueError as exc:
        raise ValueError("Generation profile must be auto, standard, or advanced.") from exc


def _authorized_budget(
    job: JobState,
    settings: Settings,
    effective: GenerationProfile,
) -> float:
    raw = job.request.metadata.get("authorized_budget_usd")
    if raw is None:
        raw = (
            settings.default_advanced_run_budget_usd
            if effective == GenerationProfile.ADVANCED
            else settings.maximum_run_budget_usd
        )
    authorized = round(float(raw), 2)
    maximum = (
        settings.maximum_advanced_run_budget_usd
        if effective == GenerationProfile.ADVANCED
        else settings.maximum_run_budget_usd
    )
    if authorized <= 0 or authorized > maximum:
        raise ValueError(
            f"The authorized budget must be above $0 and no more than ${maximum:.2f} "
            f"for {effective.value} mode."
        )
    return authorized


def _estimate_cost_range(
    profile: GenerationProfile,
    score: int,
    images: int,
    videos: int,
) -> tuple[float, float]:
    base = 0.16 if profile == GenerationProfile.STANDARD else 0.42
    media = min(images, 6) * 0.01 + min(videos, 4) * 0.04
    complexity = score * (0.025 if profile == GenerationProfile.STANDARD else 0.06)
    minimum = round(base + media + complexity * 0.45, 2)
    maximum = round(base + media + complexity + (0.18 if profile == GenerationProfile.ADVANCED else 0.09), 2)
    return minimum, maximum


def _uploaded_assets(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    assets = metadata.get("uploaded_assets", [])
    if not isinstance(assets, list):
        return []
    return [asset for asset in assets if isinstance(asset, dict)]
