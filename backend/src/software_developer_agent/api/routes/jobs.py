import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from software_developer_agent.config.settings import get_settings
from software_developer_agent.guardrails.input.acceptable_use import (
    ProhibitedRequestError,
    check_acceptable_use,
    prohibited_use_findings,
    prohibited_use_reason,
    prompt_fingerprint,
)
from software_developer_agent.models.job_state import (
    GuardrailReport,
    HumanFeedbackDecision,
    JobRequest,
    JobState,
    JobStatus,
)
from software_developer_agent.models.project_naming import resolve_project_name
from software_developer_agent.observability.logging import redact_secrets
from software_developer_agent.observability.metrics import metrics
from software_developer_agent.orchestration.conditional_router import RouteAction, RouteDecision
from software_developer_agent.orchestration.redis_queue import get_job_queue
from software_developer_agent.orchestration.state_machine import AgentRuntime
from software_developer_agent.persistence.job_store import get_job_store

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)


class SubmitJobRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000)
    project_id: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
    run_immediately: bool = True


class SubmitHumanFeedbackRequest(BaseModel):
    decision: HumanFeedbackDecision
    message: str | None = Field(default=None, max_length=10_000)


@router.post("", status_code=202)
def submit_job(payload: SubmitJobRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    _reject_prohibited_prompt(payload.prompt)
    queue = get_job_queue()
    store = get_job_store()
    project_name, generated_name = resolve_project_name(payload.project_id, payload.prompt)
    metadata = dict(payload.metadata)
    metadata["project_name_generated"] = generated_name
    job = JobState(
        request=JobRequest(
            prompt=payload.prompt,
            project_id=project_name,
            metadata=metadata,
        )
    )
    metrics.increment("jobs_submitted")
    if payload.run_immediately:
        queue.update(job)
    else:
        queue.submit(job)
    store.save(job)

    if not payload.run_immediately:
        return job.to_dict()

    job.set_status(JobStatus.RUNNING)
    queue.update(job)
    store.save(job)
    background_tasks.add_task(_run_and_persist_job, job)
    response = job.to_dict()
    response["route"] = _accepted_route()
    return response


@router.post("/{job_id}/feedback", status_code=202)
def submit_human_feedback(
    job_id: str,
    payload: SubmitHumanFeedbackRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    queue = get_job_queue()
    store = get_job_store()
    job = store.get(job_id) or queue.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    runtime = AgentRuntime()
    try:
        runtime.apply_human_feedback(job, payload.decision, payload.message)
    except ProhibitedRequestError as exc:
        raise HTTPException(
            status_code=422,
            detail=_prohibited_detail(exc.report, source="human_feedback"),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    job.set_status(JobStatus.RUNNING)
    queue.update(job)
    store.save(job)
    background_tasks.add_task(_run_and_persist_job, job)
    response = job.to_dict()
    response["route"] = _accepted_route()
    return response


@router.post("/{job_id}/run", status_code=202)
def run_job(job_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    queue = get_job_queue()
    store = get_job_store()
    job = store.get(job_id) or queue.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status in {
        JobStatus.RUNNING,
        JobStatus.EVALUATING,
        JobStatus.RETRYING,
    }:
        raise HTTPException(status_code=409, detail="Job is already running.")

    job.set_status(JobStatus.RUNNING)
    queue.update(job)
    store.save(job)
    background_tasks.add_task(_run_and_persist_job, job)
    response = job.to_dict()
    response["route"] = _accepted_route()
    return response


@router.post("/work-next", status_code=202)
def work_next_job(background_tasks: BackgroundTasks) -> dict[str, Any]:
    queue = get_job_queue()
    store = get_job_store()
    job = queue.pop_next()
    if job is None:
        return {"status": "idle"}

    job.set_status(JobStatus.RUNNING)
    queue.update(job)
    store.save(job)
    background_tasks.add_task(_run_and_persist_job, job)
    response = job.to_dict()
    response["route"] = _accepted_route()
    return response


def _run_job(
    job: JobState,
    runtime: AgentRuntime | None = None,
) -> tuple[dict[str, Any], RouteDecision]:
    runtime = runtime or AgentRuntime()
    try:
        route = runtime.run_to_completion(job)
    except Exception as exc:
        logger.exception("job.pipeline_failed", extra={"job_id": job.job_id})
        error = redact_secrets(f"{type(exc).__name__}: {exc}")[:2_000]
        job.errors.append(error)
        job.set_status(JobStatus.FAILED)
        metrics.increment("jobs_failed")
        route = RouteDecision(
            RouteAction.FAILURE,
            "The generation pipeline failed safely; no artifact was published.",
        )
    return job.to_dict(), route


def _run_and_persist_job(job: JobState) -> None:
    queue = get_job_queue()
    store = get_job_store()

    def persist_progress(current: JobState) -> None:
        queue.update(current)
        store.save(current)

    runtime = AgentRuntime()
    set_progress_callback = getattr(runtime, "set_progress_callback", None)
    if callable(set_progress_callback):
        set_progress_callback(persist_progress)
    _run_job(job, runtime)
    queue.update(job)
    store.save(job)


@router.get("")
def list_jobs() -> list[dict[str, Any]]:
    store = get_job_store()
    jobs = store.list_recent()
    if not jobs:
        jobs = get_job_queue().list_jobs()
    return [job.to_dict() for job in jobs]


@router.get("/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = get_job_store().get(job_id) or get_job_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job.to_dict()


@router.get("/{job_id}/artifacts")
def list_artifacts(job_id: str) -> list[dict[str, Any]]:
    job = get_job_store().get(job_id) or get_job_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return [asdict(artifact) for artifact in job.artifacts]


@router.get("/{job_id}/files")
def list_generated_files(job_id: str) -> dict[str, Any]:
    root = _project_root_for_job(job_id)
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            files.append({"path": relative, "size": path.stat().st_size})
    return {"root": str(root), "files": files}


@router.get("/{job_id}/files/content")
def get_generated_file_content(job_id: str, path: str) -> PlainTextResponse:
    root = _project_root_for_job(job_id)
    target = _safe_child(root, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    if target.stat().st_size > 300_000:
        raise HTTPException(status_code=413, detail="File is too large to preview.")
    return PlainTextResponse(target.read_text(encoding="utf-8", errors="replace"))


@router.get("/{job_id}/download")
def download_generated_project(job_id: str) -> FileResponse:
    job = get_job_store().get(job_id) or get_job_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    zip_artifact = next((artifact for artifact in job.artifacts if artifact.kind == "zip"), None)
    if zip_artifact is None:
        raise HTTPException(status_code=404, detail="ZIP artifact not found.")
    zip_path = Path(zip_artifact.path)
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="ZIP file not found on disk.")
    return FileResponse(zip_path, filename=zip_path.name, media_type="application/zip")


def _reject_prohibited_prompt(prompt: str) -> None:
    """Refuse a prohibited build request before a job, queue entry, or agent exists."""

    report = check_acceptable_use(prompt)
    if report.passed:
        return
    detail = _prohibited_detail(report, source="prompt")
    logger.warning(
        "guardrails.prohibited_prompt categories=%s fingerprint=%s",
        ",".join(detail["categories"]),
        prompt_fingerprint(prompt),
    )
    metrics.increment("guardrail_blocks")
    metrics.increment("prohibited_requests")
    raise HTTPException(status_code=422, detail=detail)


def _prohibited_detail(report: GuardrailReport, source: str) -> dict[str, Any]:
    findings = prohibited_use_findings(report)
    return {
        "code": "prohibited_request",
        "source": source,
        "categories": [str(finding.metadata.get("category", "unknown")) for finding in findings],
        "policy_ids": [str(finding.metadata.get("policy_id", "AUP")) for finding in findings],
        "message": prohibited_use_reason(report) or "Request rejected by acceptable use.",
    }


def _route_to_dict(route: RouteDecision) -> dict[str, Any]:
    return {
        "action": route.action.value,
        "reason": route.reason,
        "retry_targets": [target.value for target in route.retry_targets],
    }


def _accepted_route() -> dict[str, Any]:
    return {
        "action": "accepted",
        "reason": "Job accepted for background execution.",
        "retry_targets": [],
    }


def _project_root_for_job(job_id: str) -> Path:
    job = get_job_store().get(job_id) or get_job_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    folder = next((artifact for artifact in job.artifacts if artifact.kind == "folder"), None)
    if folder is None:
        raise HTTPException(status_code=404, detail="Project folder artifact not found.")
    root = Path(folder.path).resolve()
    generated_root = get_settings().generated_projects_dir.resolve()
    if generated_root not in root.parents and root != generated_root:
        raise HTTPException(status_code=403, detail="Artifact path is outside generated projects.")
    if not root.exists():
        raise HTTPException(status_code=404, detail="Project folder not found on disk.")
    return root


def _safe_child(root: Path, relative_path: str) -> Path:
    target = (root / relative_path).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(status_code=403, detail="Invalid file path.")
    return target
