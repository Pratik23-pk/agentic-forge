from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from software_developer_agent.api.routes.jobs import _project_root_for_job, _safe_child
from software_developer_agent.config.settings import get_settings
from software_developer_agent.orchestration.redis_queue import get_job_queue
from software_developer_agent.persistence.job_store import get_job_store
from software_developer_agent.workspace.collaboration import get_collaboration_hub
from software_developer_agent.workspace.revisions import get_revision_store

router = APIRouter(prefix="/jobs", tags=["workspace"])
DESIGN_TOKEN = re.compile(
    r"(?P<prefix>--(?P<name>[a-zA-Z][a-zA-Z0-9-]*)\s*:\s*)"
    r"(?P<value>[^;{}]+)(?P<suffix>;)"
)


class UpdateFileRequest(BaseModel):
    content: str = Field(max_length=300_000)
    expected_sha256: str | None = Field(default=None, min_length=64, max_length=64)


class UpdateDesignTokensRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    tokens: dict[str, str] = Field(min_length=1, max_length=100)
    expected_sha256: str = Field(min_length=64, max_length=64)


@router.put("/{job_id}/files/content")
async def update_generated_file(
    job_id: str,
    path: str,
    payload: UpdateFileRequest,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.enable_browser_editor:
        raise HTTPException(status_code=403, detail="Browser editing is disabled.")
    root = _project_root_for_job(job_id)
    target = _safe_child(root, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    if path.startswith("artifacts/") or path.endswith("package-lock.json"):
        raise HTTPException(
            status_code=403, detail="Generated metadata and lockfiles are read-only."
        )
    current = target.read_text(encoding="utf-8", errors="strict")
    current_sha = _sha256(current)
    if payload.expected_sha256 and payload.expected_sha256 != current_sha:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "The file changed after it was opened.",
                "current_sha256": current_sha,
            },
        )
    if payload.content == current:
        return {
            "path": path,
            "size": len(current.encode("utf-8")),
            "sha256": current_sha,
            "revision": None,
        }

    revision = get_revision_store().save(job_id, path, current)
    temporary = target.with_name(f".{target.name}.editing")
    temporary.write_text(payload.content, encoding="utf-8")
    temporary.replace(target)
    next_sha = _sha256(payload.content)
    _refresh_project_zip(job_id, root)
    await get_collaboration_hub().broadcast(
        job_id,
        {
            "type": "file_updated",
            "path": path,
            "sha256": next_sha,
            "revision_id": revision.revision_id,
        },
    )
    return {
        "path": path,
        "size": len(payload.content.encode("utf-8")),
        "sha256": next_sha,
        "revision": revision.to_dict(),
    }


@router.get("/{job_id}/revisions")
def list_file_revisions(job_id: str, path: str | None = None) -> list[dict[str, Any]]:
    _project_root_for_job(job_id)
    return [revision.to_dict() for revision in get_revision_store().list(job_id, path)]


@router.get("/{job_id}/design-tokens")
def list_design_tokens(job_id: str) -> dict[str, Any]:
    root = _project_root_for_job(job_id)
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.css")):
        if "node_modules" in path.parts or path.stat().st_size > 300_000:
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        tokens = {
            match.group("name"): match.group("value").strip()
            for match in DESIGN_TOKEN.finditer(content)
        }
        if tokens:
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": _sha256(content),
                    "tokens": tokens,
                }
            )
    return {"files": files}


@router.put("/{job_id}/design-tokens")
async def update_design_tokens(
    job_id: str,
    payload: UpdateDesignTokensRequest,
) -> dict[str, Any]:
    root = _project_root_for_job(job_id)
    target = _safe_child(root, payload.path)
    if target.suffix.lower() != ".css" or not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="CSS token file not found.")
    current = target.read_text(encoding="utf-8", errors="strict")
    current_sha = _sha256(current)
    if current_sha != payload.expected_sha256:
        raise HTTPException(status_code=409, detail="The design token file changed after loading.")
    existing = {match.group("name") for match in DESIGN_TOKEN.finditer(current)}
    unknown = sorted(set(payload.tokens) - existing)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown design tokens: {', '.join(unknown)}")
    for name, value in payload.tokens.items():
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9-]*", name):
            raise HTTPException(status_code=422, detail="Invalid design token name.")
        if not _safe_design_value(value):
            raise HTTPException(status_code=422, detail=f"Unsafe value for design token {name}.")

    def replace(match: re.Match[str]) -> str:
        value = payload.tokens.get(match.group("name"), match.group("value").strip())
        return f"{match.group('prefix')}{value}{match.group('suffix')}"

    updated = DESIGN_TOKEN.sub(replace, current)
    if updated == current:
        return {"path": payload.path, "sha256": current_sha, "tokens": payload.tokens}
    revision = get_revision_store().save(job_id, payload.path, current)
    temporary = target.with_name(f".{target.name}.designing")
    temporary.write_text(updated, encoding="utf-8")
    temporary.replace(target)
    next_sha = _sha256(updated)
    _refresh_project_zip(job_id, root)
    await get_collaboration_hub().broadcast(
        job_id,
        {
            "type": "file_updated",
            "path": payload.path,
            "sha256": next_sha,
            "revision_id": revision.revision_id,
        },
    )
    return {"path": payload.path, "sha256": next_sha, "tokens": payload.tokens}


@router.get("/{job_id}/revisions/{revision_id}/diff")
def get_file_revision_diff(job_id: str, revision_id: str, path: str) -> dict[str, str]:
    root = _project_root_for_job(job_id)
    target = _safe_child(root, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    revisions = get_revision_store().list(job_id, path)
    if revision_id not in {revision.revision_id for revision in revisions}:
        raise HTTPException(status_code=404, detail="Revision not found.")
    try:
        diff = get_revision_store().diff(
            revision_id,
            target.read_text(encoding="utf-8", errors="replace"),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Revision content not found.") from exc
    return {"revision_id": revision_id, "path": path, "diff": diff}


@router.websocket("/{job_id}/collaboration")
async def collaborate(job_id: str, websocket: WebSocket) -> None:
    settings = get_settings()
    if not settings.enable_collaboration:
        await websocket.close(code=1008, reason="Collaboration is disabled.")
        return
    try:
        _project_root_for_job(job_id)
    except HTTPException:
        await websocket.close(code=1008, reason="Project not found.")
        return
    hub = get_collaboration_hub()
    await hub.connect(job_id, websocket)
    try:
        while True:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict):
                continue
            message_type = str(payload.get("type", ""))
            if message_type not in {"cursor", "selection", "active_file"}:
                continue
            encoded = json.dumps(payload)
            if len(encoded) > 8_000:
                continue
            await hub.broadcast(job_id, payload, sender=websocket)
    except WebSocketDisconnect:
        await hub.disconnect(job_id, websocket)


def _refresh_project_zip(job_id: str, root: Path) -> None:
    job = get_job_store().get(job_id) or get_job_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    artifact = next((item for item in job.artifacts if item.kind == "zip"), None)
    if artifact is None:
        return
    zip_path = Path(artifact.path).resolve()
    artifacts_root = get_settings().artifacts_dir.resolve()
    if artifacts_root not in zip_path.parents:
        raise HTTPException(status_code=403, detail="ZIP path is outside artifact storage.")
    temporary = zip_path.with_name(f".{zip_path.name}.editing")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(root.rglob("*")):
            if file_path.is_file() and "node_modules" not in file_path.parts:
                archive.write(file_path, file_path.relative_to(root))
    temporary.replace(zip_path)


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _safe_design_value(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        bool(normalized)
        and len(normalized) <= 200
        and not any(
            marker in normalized
            for marker in (";", "{", "}", "expression(", "javascript:", "@import")
        )
    )
