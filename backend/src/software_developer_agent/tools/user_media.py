from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile

from software_developer_agent.config.settings import Settings, get_settings
from software_developer_agent.models.job_state import JobState

IMAGE_SIGNATURES = {
    "image/jpeg": lambda body: body.startswith(b"\xff\xd8\xff"),
    "image/png": lambda body: body.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/gif": lambda body: body.startswith((b"GIF87a", b"GIF89a")),
    "image/webp": lambda body: body.startswith(b"RIFF") and body[8:12] == b"WEBP",
}
VIDEO_SIGNATURES = {
    "video/mp4": lambda body: len(body) >= 12 and body[4:8] == b"ftyp",
    "video/webm": lambda body: body.startswith(b"\x1a\x45\xdf\xa3"),
    "video/ogg": lambda body: body.startswith(b"OggS"),
}
EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/ogg": ".ogv",
}


@dataclass(slots=True)
class UserMediaStore:
    settings: Settings

    async def save_pending(self, upload: UploadFile) -> dict[str, Any]:
        declared = (upload.content_type or "").split(";", 1)[0].lower()
        if declared not in {*IMAGE_SIGNATURES, *VIDEO_SIGNATURES}:
            raise ValueError("Only JPEG, PNG, GIF, WebP, MP4, WebM, and Ogg media are supported.")
        maximum = (
            self.settings.max_user_image_upload_bytes
            if declared in IMAGE_SIGNATURES
            else self.settings.max_user_video_upload_bytes
        )
        body = await _read_limited(upload, maximum)
        validators = IMAGE_SIGNATURES if declared in IMAGE_SIGNATURES else VIDEO_SIGNATURES
        if not validators[declared](body):
            raise ValueError("Uploaded bytes do not match the declared media type.")

        asset_id = str(uuid4())
        digest = hashlib.sha256(body).hexdigest()
        kind = "image" if declared in IMAGE_SIGNATURES else "video"
        extension = EXTENSIONS[declared]
        directory = self.settings.upload_cache_dir / "pending" / asset_id
        directory.mkdir(parents=True, exist_ok=False)
        safe_name = _safe_filename(upload.filename or f"upload{extension}", extension)
        file_path = directory / f"asset{extension}"
        file_path.write_bytes(body)
        record = {
            "asset_id": asset_id,
            "kind": kind,
            "filename": safe_name,
            "mime_type": declared,
            "bytes": len(body),
            "sha256": digest,
            "created_at": time.time(),
            "status": "pending",
            "cache_path": str(file_path),
        }
        _write_json(directory / "asset.json", record)
        return _public_record(record)

    def bind_to_job(self, job_id: str, asset_ids: list[str]) -> list[dict[str, Any]]:
        if len(asset_ids) > self.settings.max_user_media_assets:
            raise ValueError(
                f"A job can include at most {self.settings.max_user_media_assets} uploaded assets."
            )
        unique_ids = list(dict.fromkeys(asset_ids))
        prepared: list[tuple[str, Path, dict[str, Any]]] = []
        for asset_id in unique_ids:
            source = self._safe_asset_dir("pending", asset_id)
            record = _read_json(source / "asset.json")
            prepared.append((asset_id, source, record))

        bound: list[dict[str, Any]] = []
        for asset_id, source, record in prepared:
            destination = self._safe_asset_dir(job_id, asset_id)
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)
            cache_path = next(
                path
                for path in destination.iterdir()
                if path.name.startswith("asset.") and path.suffix != ".json"
            )
            extension = cache_path.suffix
            filename = f"user-{asset_id[:8]}-{_safe_stem(record['filename'])}{extension}"
            record.update(
                {
                    "status": "bound",
                    "job_id": job_id,
                    "cache_path": str(cache_path),
                    "project_path": f"frontend/public/assets/media/{filename}",
                    "web_path": f"/assets/media/{filename}",
                }
            )
            _write_json(destination / "asset.json", record)
            bound.append(_pipeline_record(record))
        return bound

    def delete_pending(self, asset_id: str) -> None:
        directory = self._safe_asset_dir("pending", asset_id)
        if directory.is_dir():
            shutil.rmtree(directory)

    def cleanup_job(self, job_id: str) -> None:
        directory = (self.settings.upload_cache_dir / _safe_segment(job_id)).resolve()
        root = self.settings.upload_cache_dir.resolve()
        if root not in directory.parents:
            return
        if directory.is_dir():
            shutil.rmtree(directory)
        _remove_empty_parents(root)

    def _safe_asset_dir(self, owner: str, asset_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", asset_id):
            raise ValueError("Invalid uploaded asset identifier.")
        root = self.settings.upload_cache_dir.resolve()
        directory = (root / _safe_segment(owner) / asset_id).resolve()
        if root not in directory.parents:
            raise ValueError("Invalid uploaded asset path.")
        if owner == "pending" and not directory.is_dir():
            raise ValueError("Uploaded asset does not exist or was already attached.")
        return directory


def cleanup_user_media(job: JobState, settings: Settings) -> None:
    UserMediaStore(settings).cleanup_job(job.job_id)


@lru_cache
def get_user_media_store() -> UserMediaStore:
    return UserMediaStore(get_settings())


async def _read_limited(upload: UploadFile, maximum: int) -> bytes:
    chunks = bytearray()
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        chunks.extend(chunk)
        if len(chunks) > maximum:
            raise ValueError("Uploaded media exceeds the configured size limit.")
    if not chunks:
        raise ValueError("Uploaded media is empty.")
    return bytes(chunks)


def _pipeline_record(record: dict[str, Any]) -> dict[str, Any]:
    download = {
        "cache_path": record["cache_path"],
        "project_path": record["project_path"],
        "web_path": record["web_path"],
        "mime_type": record["mime_type"],
        "bytes": record["bytes"],
        "sha256": record["sha256"],
        "remote_url": None,
    }
    return {
        "asset_id": record["asset_id"],
        "kind": record["kind"],
        "title": record["filename"],
        "source": "User upload",
        "source_url": None,
        "remote_url": None,
        "embed_url": None,
        "poster_url": None,
        "download": download,
        "rights_status": "user-provided",
    }


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in ("asset_id", "kind", "filename", "mime_type", "bytes", "sha256", "status")
    }


def _safe_filename(value: str, extension: str) -> str:
    stem = _safe_stem(Path(value).stem)
    return f"{stem}{extension}"


def _safe_stem(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")[:72] or "media"


def _safe_segment(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")[:80] or "asset"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("Uploaded asset metadata is missing.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("Uploaded asset metadata is invalid.")
    return payload


def _remove_empty_parents(root: Path) -> None:
    pending = root / "pending"
    if pending.is_dir() and not any(pending.iterdir()):
        pending.rmdir()
    if root.is_dir() and not any(root.iterdir()):
        root.rmdir()
