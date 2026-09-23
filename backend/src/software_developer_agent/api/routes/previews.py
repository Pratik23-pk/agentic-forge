from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse

from software_developer_agent.api.routes.jobs import _project_root_for_job
from software_developer_agent.config.settings import get_settings
from software_developer_agent.orchestration.redis_queue import get_job_queue
from software_developer_agent.persistence.job_store import get_job_store
from software_developer_agent.sandbox.preview_manager import get_preview_manager

router = APIRouter(prefix="/jobs", tags=["previews"])


@router.post("/{job_id}/preview", status_code=201)
def start_preview(job_id: str) -> dict[str, Any]:
    job = get_job_store().get(job_id) or get_job_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    root = _project_root_for_job(job_id)
    try:
        record = get_preview_manager().start(job, root)
        get_job_queue().update(job)
        get_job_store().save(job)
        return record.to_dict()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{job_id}/preview")
def get_preview(job_id: str) -> dict[str, Any]:
    record = get_preview_manager().get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Preview not found.")
    return record.to_dict()


@router.delete("/{job_id}/preview")
def stop_preview(job_id: str) -> dict[str, Any]:
    record = get_preview_manager().stop(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Preview not found.")
    return record.to_dict()


@router.get("/{job_id}/preview/logs", response_class=PlainTextResponse)
def get_preview_logs(
    job_id: str,
    service: str | None = Query(default=None, max_length=32),
) -> str:
    try:
        return get_preview_manager().logs(job_id, service)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Preview or service not found.") from exc


@router.get("/{job_id}/preview/screenshot")
def get_preview_screenshot(job_id: str) -> FileResponse:
    record = get_preview_manager().get(job_id)
    if record is None or record.screenshot_path is None:
        raise HTTPException(status_code=404, detail="Preview screenshot not found.")
    path = Path(record.screenshot_path).resolve()
    expected_root = (get_settings().preview_cache_dir / job_id).resolve()
    if expected_root not in path.parents or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Preview screenshot not found.")
    return FileResponse(path, media_type="image/png", filename="runtime-preview.png")
