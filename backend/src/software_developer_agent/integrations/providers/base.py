from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import httpx


class ProviderError(RuntimeError):
    def __init__(self, provider: str, message: str, status_code: int = 502) -> None:
        self.provider = provider
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    provider: str
    configured: bool
    enabled: bool
    capabilities: tuple[str, ...]
    documentation_url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProviderHttpClient:
    def __init__(
        self,
        provider: str,
        base_url: str,
        token: str,
        timeout_seconds: int,
        headers: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._provider = provider
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                **(headers or {}),
            },
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        json_payload: Any = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        expected: set[int] | None = None,
    ) -> httpx.Response:
        try:
            response = self._client.request(
                method,
                path,
                json=json_payload,
                content=content,
                headers=headers,
                params=params,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(self._provider, f"{self._provider} request failed.") from exc
        allowed = expected or {200, 201, 202, 204}
        if response.status_code not in allowed:
            message = _provider_message(response)
            mapped_status = 409 if response.status_code in {400, 409, 422} else 502
            if response.status_code in {401, 403}:
                mapped_status = 403
            if response.status_code == 404:
                mapped_status = 404
            raise ProviderError(
                self._provider,
                f"{self._provider} rejected the request: {message}",
                mapped_status,
            )
        return response


def _provider_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or "provider error")[:500]
        return str(payload.get("message") or payload.get("error") or "provider error")[:500]
    return f"HTTP {response.status_code}"
