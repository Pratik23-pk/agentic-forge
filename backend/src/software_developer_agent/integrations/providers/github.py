from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from software_developer_agent.config.settings import Settings
from software_developer_agent.integrations.providers.base import (
    ProviderError,
    ProviderHttpClient,
    ProviderStatus,
)

REPOSITORY_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


class GitHubProvider:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        secret = settings.github_token.get_secret_value() if settings.github_token else ""
        self._http = ProviderHttpClient(
            "GitHub",
            settings.github_api_url,
            secret,
            settings.provider_timeout_seconds,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": settings.github_api_version,
            },
            transport=transport,
        )

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider="github",
            configured=self._settings.github_token is not None,
            enabled=self._settings.enable_provider_actions,
            capabilities=("repository_sync", "branches", "commits", "pull_requests"),
            documentation_url="https://docs.github.com/en/rest/repos/contents",
        )

    def sync(
        self,
        root: Path,
        *,
        owner: str,
        repository: str,
        branch: str,
        message: str,
        base_branch: str | None = None,
        pull_request_title: str | None = None,
    ) -> dict[str, Any]:
        self._require_ready()
        _validate_repository_part(owner, "owner")
        _validate_repository_part(repository, "repository")
        _validate_branch(branch)
        repository_path = f"/repos/{quote(owner)}/{quote(repository)}"
        repository_payload = self._http.request("GET", repository_path).json()
        default_branch = str(repository_payload.get("default_branch") or "main")
        parent_branch = base_branch or default_branch
        parent_sha = self._resolve_ref(repository_path, parent_branch)
        branch_sha = self._resolve_ref(repository_path, branch, allow_missing=True)
        if branch_sha is None:
            self._http.request(
                "POST",
                f"{repository_path}/git/refs",
                json_payload={"ref": f"refs/heads/{branch}", "sha": parent_sha},
            )
            branch_sha = parent_sha

        commit = self._http.request(
            "GET",
            f"{repository_path}/git/commits/{quote(branch_sha, safe='')}",
        ).json()
        base_tree = str(commit["tree"]["sha"])
        tree_entries: list[dict[str, str]] = []
        for path in _project_files(root):
            content = path.read_bytes()
            blob = self._http.request(
                "POST",
                f"{repository_path}/git/blobs",
                json_payload={
                    "content": base64.b64encode(content).decode("ascii"),
                    "encoding": "base64",
                },
            ).json()
            tree_entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "mode": "100644",
                    "type": "blob",
                    "sha": str(blob["sha"]),
                }
            )
        tree = self._http.request(
            "POST",
            f"{repository_path}/git/trees",
            json_payload={"base_tree": base_tree, "tree": tree_entries},
        ).json()
        next_commit = self._http.request(
            "POST",
            f"{repository_path}/git/commits",
            json_payload={
                "message": message,
                "tree": str(tree["sha"]),
                "parents": [branch_sha],
            },
        ).json()
        commit_sha = str(next_commit["sha"])
        self._http.request(
            "PATCH",
            f"{repository_path}/git/refs/heads/{quote(branch, safe='')}",
            json_payload={"sha": commit_sha, "force": False},
        )

        pull_request: dict[str, Any] | None = None
        if pull_request_title and branch != parent_branch:
            pull_request = self._http.request(
                "POST",
                f"{repository_path}/pulls",
                json_payload={
                    "title": pull_request_title,
                    "head": branch,
                    "base": parent_branch,
                    "body": "Generated and validated by Agentic Forge.",
                },
            ).json()
        return {
            "provider": "github",
            "repository_url": str(repository_payload.get("html_url") or ""),
            "branch": branch,
            "commit_sha": commit_sha,
            "files_synced": len(tree_entries),
            "pull_request_url": (
                str(pull_request.get("html_url")) if pull_request is not None else None
            ),
        }

    def _resolve_ref(
        self,
        repository_path: str,
        branch: str,
        allow_missing: bool = False,
    ) -> str | None:
        try:
            payload = self._http.request(
                "GET",
                f"{repository_path}/git/ref/heads/{quote(branch, safe='')}",
            ).json()
        except ProviderError as exc:
            if allow_missing and exc.status_code == 404:
                return None
            raise
        return str(payload["object"]["sha"])

    def _require_ready(self) -> None:
        if not self._settings.enable_provider_actions:
            raise ProviderError("GitHub", "Provider actions are disabled.", 403)
        if self._settings.github_token is None:
            raise ProviderError("GitHub", "GITHUB_TOKEN is not configured.", 409)


def _project_files(root: Path) -> list[Path]:
    paths = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and "node_modules" not in path.parts
        and ".venv" not in path.parts
        and path.stat().st_size <= 5_000_000
    ]
    if len(paths) > 1_000:
        raise ProviderError("GitHub", "Generated project exceeds the 1,000-file sync limit.", 409)
    return paths


def _validate_repository_part(value: str, label: str) -> None:
    if not REPOSITORY_PART.fullmatch(value):
        raise ProviderError("GitHub", f"Invalid GitHub {label}.", 409)


def _validate_branch(value: str) -> None:
    if not value or value.startswith("-") or ".." in value or value.endswith(("/", ".lock")):
        raise ProviderError("GitHub", "Invalid Git branch name.", 409)
    if any(character.isspace() or character in "~^:?*[\\" for character in value):
        raise ProviderError("GitHub", "Invalid Git branch name.", 409)
