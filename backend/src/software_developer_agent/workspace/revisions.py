from __future__ import annotations

import difflib
import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from software_developer_agent.config.settings import get_settings


@dataclass(slots=True)
class FileRevision:
    revision_id: str
    job_id: str
    path: str
    sha256: str
    created_at: float
    content_path: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("content_path", None)
        return payload


class RevisionStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._lock = threading.RLock()

    def save(self, job_id: str, relative_path: str, content: str) -> FileRevision:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        created_at = time.time()
        revision_id = f"{int(created_at * 1000)}-{digest[:12]}"
        revision_root = self._root / job_id / "revisions"
        content_path = revision_root / f"{revision_id}.txt"
        record = FileRevision(
            revision_id=revision_id,
            job_id=job_id,
            path=relative_path,
            sha256=digest,
            created_at=created_at,
            content_path=str(content_path),
        )
        with self._lock:
            revision_root.mkdir(parents=True, exist_ok=True)
            content_path.write_text(content, encoding="utf-8")
            with (revision_root / "index.jsonl").open("a", encoding="utf-8") as index:
                index.write(json.dumps(asdict(record), separators=(",", ":")) + "\n")
        return record

    def list(self, job_id: str, relative_path: str | None = None) -> list[FileRevision]:
        index_path = self._root / job_id / "revisions" / "index.jsonl"
        if not index_path.exists():
            return []
        records: list[FileRevision] = []
        with self._lock:
            for line in index_path.read_text(encoding="utf-8").splitlines():
                try:
                    revision = FileRevision(**json.loads(line))
                except (json.JSONDecodeError, TypeError):
                    continue
                if relative_path is None or revision.path == relative_path:
                    records.append(revision)
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def diff(self, revision_id: str, current_content: str) -> str:
        matches = list(self._root.glob(f"*/revisions/{revision_id}.txt"))
        if len(matches) != 1:
            raise KeyError(revision_id)
        previous = matches[0].read_text(encoding="utf-8", errors="replace")
        return "".join(
            difflib.unified_diff(
                previous.splitlines(keepends=True),
                current_content.splitlines(keepends=True),
                fromfile=f"revision/{revision_id}",
                tofile="workspace/current",
            )
        )


@lru_cache
def get_revision_store() -> RevisionStore:
    return RevisionStore(get_settings().preview_cache_dir)
