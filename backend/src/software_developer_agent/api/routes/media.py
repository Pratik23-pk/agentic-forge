from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from software_developer_agent.config.settings import get_settings
from software_developer_agent.tools.user_media import get_user_media_store

router = APIRouter(prefix="/media", tags=["media"])


@router.post("/uploads", status_code=201)
async def upload_media(
    files: Annotated[list[UploadFile], File(description="User-provided images or videos")],
) -> dict:
    store = get_user_media_store()
    settings = get_settings()
    if len(files) > settings.max_user_media_assets:
        raise HTTPException(
            status_code=413,
            detail=f"At most {settings.max_user_media_assets} files can be uploaded at once.",
        )
    assets = []
    try:
        for upload in files:
            assets.append(await store.save_pending(upload))
    except ValueError as exc:
        for asset in assets:
            store.delete_pending(str(asset["asset_id"]))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        for upload in files:
            await upload.close()
    return {"assets": assets}


@router.delete("/uploads/{asset_id}", status_code=204)
def delete_upload(asset_id: str) -> None:
    try:
        get_user_media_store().delete_pending(asset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/transcriptions")
async def transcribe_audio(
    audio: Annotated[UploadFile, File(description="Recorded voice prompt")],
    duration_seconds: Annotated[float, Form(gt=0)],
) -> dict:
    settings = get_settings()
    if duration_seconds > settings.max_voice_recording_seconds:
        raise HTTPException(status_code=413, detail="Voice recording exceeds the duration limit.")
    body = await audio.read(settings.max_voice_recording_bytes + 1)
    await audio.close()
    if not body:
        raise HTTPException(status_code=422, detail="Voice recording is empty.")
    if len(body) > settings.max_voice_recording_bytes:
        raise HTTPException(status_code=413, detail="Voice recording exceeds the size limit.")
    if settings.openai_api_key is None:
        raise HTTPException(status_code=503, detail="OpenAI transcription is not configured.")
    content_type = (audio.content_type or "application/octet-stream").split(";", 1)[0]
    if content_type not in {
        "audio/mp4",
        "audio/mpeg",
        "audio/ogg",
        "audio/wav",
        "audio/webm",
        "video/webm",
    }:
        raise HTTPException(status_code=422, detail="Unsupported voice recording format.")
    try:
        client = OpenAI(api_key=settings.openai_api_key.get_secret_value())
        response = client.audio.transcriptions.create(
            model=settings.openai_transcription_model,
            file=(audio.filename or "prompt.webm", body, content_type),
        )
    except (APIConnectionError, APIStatusError, APITimeoutError) as exc:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {type(exc).__name__}") from exc
    text = str(getattr(response, "text", "")).strip()
    if not text:
        raise HTTPException(status_code=502, detail="Transcription returned no text.")
    estimated_cost = round(
        duration_seconds / 60 * settings.transcription_cost_per_minute_usd,
        8,
    )
    return {
        "transcript": text,
        "receipt_id": str(uuid4()),
        "duration_seconds": round(duration_seconds, 2),
        "estimated_cost_usd": estimated_cost,
        "model": settings.openai_transcription_model,
    }
