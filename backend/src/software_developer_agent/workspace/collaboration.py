from __future__ import annotations

import asyncio
from collections import defaultdict
from functools import lru_cache
from typing import Any

from fastapi import WebSocket


class CollaborationHub:
    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, job_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._rooms[job_id].add(websocket)
            collaborators = len(self._rooms[job_id])
        await self.broadcast(
            job_id,
            {"type": "presence", "collaborators": collaborators},
        )

    async def disconnect(self, job_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._rooms[job_id].discard(websocket)
            collaborators = len(self._rooms[job_id])
            if not self._rooms[job_id]:
                self._rooms.pop(job_id, None)
        await self.broadcast(
            job_id,
            {"type": "presence", "collaborators": collaborators},
        )

    async def broadcast(
        self,
        job_id: str,
        message: dict[str, Any],
        sender: WebSocket | None = None,
    ) -> None:
        async with self._lock:
            recipients = list(self._rooms.get(job_id, set()))
        failed: list[WebSocket] = []
        for websocket in recipients:
            if websocket is sender:
                continue
            try:
                await websocket.send_json(message)
            except RuntimeError:
                failed.append(websocket)
        if failed:
            async with self._lock:
                for websocket in failed:
                    self._rooms[job_id].discard(websocket)


@lru_cache
def get_collaboration_hub() -> CollaborationHub:
    return CollaborationHub()
