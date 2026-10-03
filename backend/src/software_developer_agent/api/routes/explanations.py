from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from software_developer_agent.config.settings import get_settings
from software_developer_agent.explanations.project_explainer import (
    ExplainerBudgetError,
    ExplainerPromptLimitError,
    answer_project_question,
    initialize_project_explanation,
)
from software_developer_agent.models.job_state import JobState, JobStatus, ReleaseStatus
from software_developer_agent.orchestration.redis_queue import get_job_queue
from software_developer_agent.persistence.job_store import get_job_store

router = APIRouter(prefix="/jobs", tags=["project-explainer"])


class ProjectQuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2_000)


@router.get("/{job_id}/guide")
def get_project_guide(job_id: str) -> dict[str, Any]:
    job = _get_job(job_id)
    _require_eligible(job)
    initialize_project_explanation(
        job,
        settings=get_settings(),
        persist=_persist,
    )
    return _response(job)


@router.post("/{job_id}/guide", status_code=200)
def initialize_project_guide(job_id: str) -> dict[str, Any]:
    job = _get_job(job_id)
    _require_eligible(job)
    initialize_project_explanation(
        job,
        settings=get_settings(),
        persist=_persist,
    )
    return _response(job)


@router.post("/{job_id}/guide/messages")
def ask_project_guide(job_id: str, payload: ProjectQuestionRequest) -> dict[str, Any]:
    job = _get_job(job_id)
    _require_eligible(job)
    try:
        answer_project_question(
            job,
            payload.question,
            settings=get_settings(),
            persist=_persist,
        )
    except ExplainerPromptLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ExplainerBudgetError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _response(job)


def _persist(job: JobState) -> None:
    get_job_queue().update(job)
    get_job_store().save(job)


def _get_job(job_id: str) -> JobState:
    job = get_job_store().get(job_id) or get_job_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


def _require_eligible(job: JobState) -> None:
    if job.status != JobStatus.SUCCEEDED or job.release_status != ReleaseStatus.VERIFIED:
        raise HTTPException(
            status_code=409,
            detail="Project explainer is available after a verified build completes.",
        )
    if not any(artifact.kind == "folder" for artifact in job.artifacts):
        raise HTTPException(status_code=409, detail="Project folder artifact is unavailable.")


def _response(job: JobState) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "project_id": job.request.project_id,
        "build_status": job.status.value,
        "release_status": job.release_status.value,
        "explanation": job.project_explanation,
    }
