"""Credential-gated source control and managed-service adapters."""

from software_developer_agent.integrations.providers.github import GitHubProvider
from software_developer_agent.integrations.providers.supabase import SupabaseProvider

__all__ = ["GitHubProvider", "SupabaseProvider"]
