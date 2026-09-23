from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from software_developer_agent.api.routes.providers import provider_status, router
from software_developer_agent.config.settings import Settings
from software_developer_agent.integrations.providers.base import ProviderError
from software_developer_agent.integrations.providers.github import GitHubProvider
from software_developer_agent.integrations.providers.supabase import SupabaseProvider


def test_provider_actions_are_disabled_by_default() -> None:
    settings = Settings(app_env="test")
    assert GitHubProvider(settings).status().enabled is False
    assert SupabaseProvider(settings).status().configured is False


def test_provider_surface_contains_no_hosting_or_deployment_actions() -> None:
    assert {item["provider"] for item in provider_status()} == {"github", "supabase"}
    assert all(
        "deploy" not in route.path and "hosting" not in route.path for route in router.routes
    )


def test_supabase_requires_explicit_billing_confirmation() -> None:
    settings = Settings(
        app_env="test",
        enable_provider_actions=True,
        supabase_management_access_token=SecretStr("test-token"),
    )
    with pytest.raises(ProviderError, match="confirm_billing=true"):
        SupabaseProvider(settings).create_project(
            name="demo",
            organization_slug="example",
            database_password="a-secure-password",
            confirm_billing=False,
        )


def test_supabase_secret_results_never_return_values() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={})
        return httpx.Response(
            200,
            json=[{"name": "OPENAI_API_KEY", "value": "must-not-return", "updated_at": "now"}],
        )

    settings = Settings(
        app_env="test",
        enable_provider_actions=True,
        supabase_management_access_token=SecretStr("test-token"),
    )
    provider = SupabaseProvider(settings, httpx.MockTransport(handler))
    project_ref = "abcdefghijklmnopqrst"
    result = provider.create_secrets(
        project_ref,
        {"OPENAI_API_KEY": "secret-value"},
        confirm_write=True,
    )
    assert result["names"] == ["OPENAI_API_KEY"]
    assert "secret-value" not in str(result)
    listed = provider.list_secrets(project_ref)
    assert listed == [{"name": "OPENAI_API_KEY", "updated_at": "now"}]


def test_github_rejects_invalid_branch_before_network(tmp_path: Path) -> None:
    settings = Settings(
        app_env="test",
        enable_provider_actions=True,
        github_token=SecretStr("test-token"),
    )
    with pytest.raises(ProviderError, match="Invalid Git branch"):
        GitHubProvider(settings).sync(
            tmp_path,
            owner="owner",
            repository="repo",
            branch="bad branch",
            message="test",
        )
