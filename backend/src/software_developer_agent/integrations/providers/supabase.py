from __future__ import annotations

import re
from typing import Any

import httpx

from software_developer_agent.config.settings import Settings
from software_developer_agent.integrations.providers.base import (
    ProviderError,
    ProviderHttpClient,
    ProviderStatus,
)

PROJECT_REF = re.compile(r"^[a-z0-9]{10,40}$")


class SupabaseProvider:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        token = (
            settings.supabase_management_access_token.get_secret_value()
            if settings.supabase_management_access_token
            else ""
        )
        self._http = ProviderHttpClient(
            "Supabase",
            settings.supabase_management_api_url,
            token,
            settings.provider_timeout_seconds,
            transport=transport,
        )

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider="supabase",
            configured=self._settings.supabase_management_access_token is not None,
            enabled=self._settings.enable_provider_actions,
            capabilities=("managed_database", "auth", "storage", "project_secrets"),
            documentation_url="https://supabase.com/docs/reference/api/introduction",
        )

    def create_project(
        self,
        *,
        name: str,
        organization_slug: str,
        database_password: str,
        confirm_billing: bool,
    ) -> dict[str, Any]:
        self._require_ready()
        if not confirm_billing:
            raise ProviderError(
                "Supabase",
                "Project provisioning requires confirm_billing=true.",
                409,
            )
        if len(database_password) < 12:
            raise ProviderError(
                "Supabase", "Database password must contain at least 12 characters.", 409
            )
        project = self._http.request(
            "POST",
            "/v1/projects",
            json_payload={
                "name": name,
                "organization_slug": organization_slug,
                "db_pass": database_password,
            },
        ).json()
        return {
            "provider": "supabase",
            "project_id": project.get("id"),
            "project_ref": project.get("ref"),
            "name": project.get("name"),
            "region": project.get("region"),
            "status": project.get("status"),
        }

    def list_api_keys(self, project_ref: str) -> list[dict[str, Any]]:
        self._require_ready()
        self._validate_ref(project_ref)
        keys = self._http.request(
            "GET",
            f"/v1/projects/{project_ref}/api-keys",
            params={"reveal": "false"},
        ).json()
        return [
            {
                key: item.get(key)
                for key in ("id", "type", "prefix", "name", "description", "inserted_at")
            }
            for item in keys
            if isinstance(item, dict)
        ]

    def list_buckets(self, project_ref: str) -> list[dict[str, Any]]:
        self._require_ready()
        self._validate_ref(project_ref)
        buckets = self._http.request(
            "GET",
            f"/v1/projects/{project_ref}/storage/buckets",
        ).json()
        return [item for item in buckets if isinstance(item, dict)]

    def create_secrets(
        self,
        project_ref: str,
        secrets: dict[str, str],
        *,
        confirm_write: bool,
    ) -> dict[str, Any]:
        self._require_ready()
        self._validate_ref(project_ref)
        if not confirm_write:
            raise ProviderError("Supabase", "Secret writes require confirm_write=true.", 409)
        if not secrets or len(secrets) > 50:
            raise ProviderError("Supabase", "Provide between 1 and 50 secrets.", 409)
        payload: list[dict[str, str]] = []
        for name, value in secrets.items():
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", name) or not value:
                raise ProviderError("Supabase", "Invalid secret name or empty value.", 409)
            payload.append({"name": name, "value": value})
        self._http.request(
            "POST",
            f"/v1/projects/{project_ref}/secrets",
            json_payload=payload,
        )
        return {"provider": "supabase", "project_ref": project_ref, "names": sorted(secrets)}

    def list_secrets(self, project_ref: str) -> list[dict[str, Any]]:
        self._require_ready()
        self._validate_ref(project_ref)
        secrets = self._http.request(
            "GET",
            f"/v1/projects/{project_ref}/secrets",
        ).json()
        return [
            {"name": item.get("name"), "updated_at": item.get("updated_at")}
            for item in secrets
            if isinstance(item, dict)
        ]

    def _require_ready(self) -> None:
        if not self._settings.enable_provider_actions:
            raise ProviderError("Supabase", "Provider actions are disabled.", 403)
        if self._settings.supabase_management_access_token is None:
            raise ProviderError(
                "Supabase",
                "SUPABASE_MANAGEMENT_ACCESS_TOKEN is not configured.",
                409,
            )

    @staticmethod
    def _validate_ref(project_ref: str) -> None:
        if not PROJECT_REF.fullmatch(project_ref):
            raise ProviderError("Supabase", "Invalid Supabase project reference.", 409)
