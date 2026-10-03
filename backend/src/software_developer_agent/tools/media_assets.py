from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import shutil
import socket
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from software_developer_agent.config.settings import Settings
from software_developer_agent.models.job_state import JobState
from software_developer_agent.tools.policy import ToolPolicy
from software_developer_agent.tools.serper_search import SerperSearchTool
from software_developer_agent.tools.types import ToolResult

MediaKind = Literal["image", "video"]
PreferredStrategy = Literal["download", "embed", "remote"]

IMAGE_MIME_EXTENSIONS = {
    "image/avif": ".avif",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
VIDEO_MIME_EXTENSIONS = {
    "video/mp4": ".mp4",
    "video/ogg": ".ogv",
    "video/webm": ".webm",
}
REDIRECT_CODES = {301, 302, 303, 307, 308}
DOWNLOAD_HINTS = ("download", "offline", "bundle", "local asset", "self-contained")
EMBED_HINTS = ("embed", "youtube", "vimeo", "stream", "hosted video")


class MediaAssetPipeline:
    def __init__(
        self,
        settings: Settings,
        policy: ToolPolicy,
        search_tool: SerperSearchTool | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        public_url_validator: Callable[[str], bool] | None = None,
    ) -> None:
        self._settings = settings
        self._policy = policy
        self._search = search_tool or SerperSearchTool(settings)
        self._transport = transport
        self._public_url_validator = public_url_validator or is_public_http_url

    def acquire(
        self,
        query: str,
        kind: MediaKind,
        task_id: str,
        instructions: str,
    ) -> ToolResult:
        tool_name = "media_asset_acquisition"
        search_result = (
            self._search.search_images(query)
            if kind == "image"
            else self._search.search_videos(query)
        )
        if search_result.status != "succeeded":
            return ToolResult(
                tool_name,
                search_result.status,
                query,
                search_result.output_summary,
                metadata={"kind": kind, "search_tool": search_result.tool_name},
            )

        candidates = search_result.metadata.get("candidates", [])
        assets: list[dict[str, Any]] = []
        preferred = _preferred_strategy(instructions, kind)
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            asset = self._candidate_options(candidate, kind, task_id, preferred)
            if asset is not None:
                assets.append(asset)
            if len(assets) >= self._settings.max_media_assets:
                break

        if not assets:
            return ToolResult(
                tool_name,
                "failed",
                query,
                f"No usable {kind} candidates were returned.",
                metadata={
                    "kind": kind,
                    "urls": search_result.metadata.get("urls", []),
                    "licensing_note": search_result.metadata.get("licensing_note", ""),
                },
            )

        payload = {
            "media_kind": kind,
            "preferred_strategy": preferred,
            "decision_rule": (
                "Use one listed option exactly. Prefer a downloaded local path for critical or "
                "offline-safe media; otherwise use a permitted embed or remote URL. Never invent "
                "a URL. When both local and external options exist, use the local asset as the "
                "runtime fallback. Provide a polished fallback and visible attribution when required."
            ),
            "assets": assets,
        }
        return ToolResult(
            tool_name=tool_name,
            status="succeeded",
            input_summary=query,
            output_summary=f"Prepared {len(assets)} {kind} asset option(s).",
            content=json.dumps(payload, separators=(",", ":")),
            metadata={
                "kind": kind,
                "preferred_strategy": preferred,
                "assets": assets,
                "urls": [
                    str(asset["source_url"])
                    for asset in assets
                    if asset.get("source_url")
                ],
                "licensing_note": search_result.metadata.get("licensing_note", ""),
            },
        )

    def _candidate_options(
        self,
        candidate: dict[str, Any],
        kind: MediaKind,
        task_id: str,
        preferred: PreferredStrategy,
    ) -> dict[str, Any] | None:
        source_url = _clean_http_url(candidate.get("source_url"))
        direct_url = _direct_media_url(candidate, kind)
        embed_url = _video_embed_url(source_url) if kind == "video" else None
        if direct_url is None and embed_url is None:
            return None

        downloaded: dict[str, Any] | None = None
        download_error: str | None = None
        should_download = self._settings.enable_media_downloads and direct_url is not None
        if should_download:
            try:
                downloaded = self._download(direct_url, kind, task_id, candidate)
            except (OSError, ValueError, httpx.HTTPError) as exc:
                download_error = str(exc)[:300]
                if _download_failure_proves_invalid_media(download_error):
                    direct_url = None

        if direct_url is None and embed_url is None and downloaded is None:
            return None

        return {
            "kind": kind,
            "title": str(candidate.get("title", ""))[:180],
            "source": str(candidate.get("source", ""))[:120],
            "source_url": source_url,
            "remote_url": direct_url,
            "embed_url": embed_url,
            "poster_url": _clean_http_url(candidate.get("poster_url")),
            "download": downloaded,
            "download_error": download_error,
            "rights_status": "verify-source-terms-before-publication",
        }

    def _download(
        self,
        url: str,
        kind: MediaKind,
        task_id: str,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        if not self._policy.is_url_allowed(url) or not self._public_url_validator(url):
            raise ValueError("Media URL is blocked by network policy.")
        maximum = (
            self._settings.max_image_download_bytes
            if kind == "image"
            else self._settings.max_video_download_bytes
        )
        mime_extensions = IMAGE_MIME_EXTENSIONS if kind == "image" else VIDEO_MIME_EXTENSIONS
        timeout = httpx.Timeout(self._settings.tool_timeout_seconds)
        headers = {"User-Agent": "AgenticForgeMedia/1.0"}
        current_url = url
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            headers=headers,
            transport=self._transport,
        ) as client:
            for _ in range(4):
                if not self._policy.is_url_allowed(current_url) or not self._public_url_validator(
                    current_url
                ):
                    raise ValueError("Media redirect is blocked by network policy.")
                with client.stream("GET", current_url) as response:
                    if response.status_code in REDIRECT_CODES:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("Media redirect omitted its destination.")
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    mime_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    extension = mime_extensions.get(mime_type)
                    if extension is None:
                        raise ValueError(f"Unsupported {kind} content type: {mime_type or 'unknown'}.")
                    declared = _positive_int(response.headers.get("content-length"))
                    if declared is not None and declared > maximum:
                        raise ValueError(f"{kind.title()} exceeds the configured download limit.")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > maximum:
                            raise ValueError(
                                f"{kind.title()} exceeds the configured download limit."
                            )
                    content = bytes(body)
                    _validate_media_signature(content, mime_type)
                    return self._cache_download(
                        content,
                        extension,
                        mime_type,
                        current_url,
                        kind,
                        task_id,
                        candidate,
                    )
        raise ValueError("Media URL exceeded the redirect limit.")

    def _cache_download(
        self,
        content: bytes,
        extension: str,
        mime_type: str,
        remote_url: str,
        kind: MediaKind,
        task_id: str,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        digest = hashlib.sha256(content).hexdigest()
        safe_task_id = _safe_segment(task_id)
        cache_dir = self._settings.media_cache_dir / safe_task_id / kind
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{digest}{extension}"
        temporary = cache_path.with_suffix(f"{extension}.tmp")
        temporary.write_bytes(content)
        temporary.replace(cache_path)
        stem = _safe_segment(str(candidate.get("title", kind)))[:60] or kind
        filename = f"{stem}-{digest[:10]}{extension}"
        return {
            "cache_path": str(cache_path),
            "project_path": f"frontend/public/assets/media/{filename}",
            "web_path": f"/assets/media/{filename}",
            "mime_type": mime_type,
            "bytes": len(content),
            "sha256": digest,
            "remote_url": remote_url,
        }


def materialize_selected_media_assets(
    job: JobState,
    settings: Settings,
    project_root: Path,
    text_files: dict[str, str],
) -> list[dict[str, Any]]:
    combined_source = "\n".join(text_files.values())
    allowed_cache_roots = {
        settings.media_cache_dir.resolve(),
        settings.upload_cache_dir.resolve(),
    }
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for asset in _media_asset_records(job):
        kind = str(asset.get("kind", "media"))
        downloaded = asset.get("download")
        if isinstance(downloaded, dict):
            web_path = str(downloaded.get("web_path", ""))
            if web_path and web_path in combined_source:
                cache_path = Path(str(downloaded.get("cache_path", ""))).resolve()
                project_path = _safe_project_media_path(downloaded.get("project_path"))
                if (
                    project_path is not None
                    and any(root in cache_path.parents for root in allowed_cache_roots)
                    and cache_path.is_file()
                ):
                    destination = project_root / project_path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(cache_path, destination)
                    key = (kind, web_path)
                    if key not in seen:
                        selected.append(_provenance_record(asset, "download", web_path))
                        seen.add(key)
        for strategy, field in (("embed", "embed_url"), ("remote", "remote_url")):
            value = asset.get(field)
            if isinstance(value, str) and value and value in combined_source:
                key = (kind, value)
                if key not in seen:
                    selected.append(_provenance_record(asset, strategy, value))
                    seen.add(key)
    return selected


def cleanup_media_cache(job: JobState, settings: Settings) -> None:
    cache_root = settings.media_cache_dir.resolve()
    for task in job.tasks:
        task_dir = (cache_root / _safe_segment(task.task_id)).resolve()
        if cache_root not in task_dir.parents:
            continue
        if task_dir.is_dir():
            shutil.rmtree(task_dir)
    if cache_root.is_dir() and not any(cache_root.iterdir()):
        cache_root.rmdir()


def is_public_http_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        }
    except OSError:
        return False
    if not addresses:
        return False
    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError:
            return False
        if not parsed_address.is_global:
            return False
    return True


def _media_asset_records(job: JobState) -> list[dict[str, Any]]:
    uploaded = job.request.metadata.get("uploaded_assets", [])
    records: list[dict[str, Any]] = (
        [asset for asset in uploaded if isinstance(asset, dict)]
        if isinstance(uploaded, list)
        else []
    )
    for result in job.worker_results:
        for call in result.tool_calls:
            if call.get("tool") != "media_asset_acquisition" or call.get("status") != "succeeded":
                continue
            metadata = call.get("metadata")
            if not isinstance(metadata, dict):
                continue
            assets = metadata.get("assets", [])
            records.extend(asset for asset in assets if isinstance(asset, dict))
    return records


def _provenance_record(asset: dict[str, Any], strategy: str, selected_url: str) -> dict[str, Any]:
    downloaded = asset.get("download")
    return {
        "kind": asset.get("kind"),
        "title": asset.get("title"),
        "source": asset.get("source"),
        "source_url": asset.get("source_url"),
        "strategy": strategy,
        "selected_url": selected_url,
        "rights_status": asset.get("rights_status"),
        "sha256": downloaded.get("sha256") if isinstance(downloaded, dict) else None,
        "project_path": (
            downloaded.get("project_path")
            if strategy == "download" and isinstance(downloaded, dict)
            else None
        ),
    }


def _safe_project_media_path(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        return None
    normalized = path.as_posix()
    if not normalized.startswith("frontend/public/assets/media/"):
        return None
    return normalized


def _preferred_strategy(instructions: str, kind: MediaKind) -> PreferredStrategy:
    lowered = instructions.lower()
    if any(hint in lowered for hint in DOWNLOAD_HINTS):
        return "download"
    if kind == "video" and any(hint in lowered for hint in EMBED_HINTS):
        return "embed"
    return "download" if kind == "image" else "embed"


def _direct_media_url(candidate: dict[str, Any], kind: MediaKind) -> str | None:
    if kind == "image":
        return _clean_http_url(candidate.get("image_url"))
    video_url = _clean_http_url(candidate.get("video_url"))
    if video_url:
        return video_url
    source_url = _clean_http_url(candidate.get("source_url"))
    if source_url and urlparse(source_url).path.lower().endswith((".mp4", ".webm", ".ogv")):
        return source_url
    return None


def _video_embed_url(source_url: str | None) -> str | None:
    if source_url is None:
        return None
    parsed = urlparse(source_url)
    host = (parsed.hostname or "").lower()
    video_id = ""
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif host.endswith("youtube.com"):
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/")):
            video_id = parsed.path.strip("/").split("/", 1)[1]
    if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
        return f"https://www.youtube-nocookie.com/embed/{video_id}"
    if host.endswith("vimeo.com"):
        candidate = parsed.path.strip("/").split("/")[-1]
        if candidate.isdigit():
            return f"https://player.vimeo.com/video/{candidate}"
    return None


def _clean_http_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def _safe_segment(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")[:80] or "asset"


def _positive_int(value: str | None) -> int | None:
    try:
        parsed = int(value or "")
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _validate_media_signature(content: bytes, mime_type: str) -> None:
    valid = {
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/gif": content.startswith((b"GIF87a", b"GIF89a")),
        "image/webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP",
        "image/avif": len(content) >= 12 and content[4:8] == b"ftyp" and b"avif" in content[8:32],
        "video/mp4": len(content) >= 12 and content[4:8] == b"ftyp",
        "video/webm": content.startswith(b"\x1a\x45\xdf\xa3"),
        "video/ogg": content.startswith(b"OggS"),
    }.get(mime_type, False)
    if not valid:
        raise ValueError("Downloaded media bytes do not match the declared content type.")


def _download_failure_proves_invalid_media(message: str) -> bool:
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in (
            "blocked by network policy",
            "content type: text/",
            "content type: application/json",
            "bytes do not match the declared content type",
        )
    )
