from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from software_developer_agent.models.job_state import WorkerKind


@dataclass(frozen=True, slots=True)
class DomainAdapter:
    """Deterministic domain contract selected in addition to a stack capability pack."""

    adapter_id: str
    display_name: str
    aliases: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    prompt_guidance: dict[WorkerKind, str] = field(default_factory=dict)


DOMAIN_ADAPTERS: tuple[DomainAdapter, ...] = (
    DomainAdapter(
        adapter_id="browser-game",
        display_name="Browser Game",
        aliases=(
            "browser game",
            "online game",
            "multiplayer game",
            "web game",
            "webgl game",
            "canvas game",
        ),
        acceptance_criteria=(
            "The primary game loop and player controls work through browser interaction tests.",
            "Game-state transitions are deterministic and terminal states are covered by tests.",
            "Real-time games define reconnect, ordering, and authoritative-state behavior.",
        ),
        prompt_guidance={
            WorkerKind.FRONTEND: (
                "Browser-game adapter: separate rendering from deterministic game state; test "
                "controls, state transitions, reset, and terminal states. Use requestAnimationFrame "
                "only for rendering loops and clean up every listener and animation handle."
            ),
            WorkerKind.BACKEND: (
                "Browser-game adapter: keep server-authoritative multiplayer state, validate every "
                "action, define ordering and reconnect semantics, and test concurrent transitions."
            ),
        },
    ),
    DomainAdapter(
        adapter_id="video-platform",
        display_name="Video and Streaming Platform",
        aliases=(
            "video hosting",
            "video platform",
            "video streaming",
            "streaming platform",
            "movie website",
            "hls",
            "dash playback",
            "video upload",
        ),
        acceptance_criteria=(
            "Video playback, loading, empty, and failure states are covered by browser tests.",
            "Uploads and protected media use authorization, size, and content-type validation.",
            "Streaming implementations support range requests or an explicit HLS/DASH contract.",
        ),
        prompt_guidance={
            WorkerKind.FRONTEND: (
                "Video-platform adapter: build accessible native or standards-based playback, "
                "explicit loading/error states, keyboard controls, and tests that do not depend on "
                "unavailable public media URLs."
            ),
            WorkerKind.BACKEND: (
                "Video-platform adapter: validate media metadata and authorization, stream without "
                "buffering entire files, and define range or HLS/DASH responses precisely."
            ),
            WorkerKind.DATABASE: (
                "Video-platform adapter: model media lifecycle, ownership, processing status, "
                "visibility, and immutable storage identifiers with indexed access paths."
            ),
        },
    ),
    DomainAdapter(
        adapter_id="realtime",
        display_name="Real-time Application",
        aliases=(
            "real-time",
            "realtime",
            "websocket",
            "live collaboration",
            "collaborative editor",
            "live chat",
        ),
        acceptance_criteria=(
            "Connection, reconnect, duplicate-message, ordering, and stale-state behavior are tested.",
            "Clients expose a recoverable offline state instead of silently losing updates.",
        ),
        prompt_guidance={
            WorkerKind.FRONTEND: (
                "Real-time adapter: implement explicit connection state, bounded reconnect, event "
                "deduplication, cleanup, and deterministic tests for delayed and repeated events."
            ),
            WorkerKind.BACKEND: (
                "Real-time adapter: define event schemas, ordering, idempotency, authorization, "
                "backpressure, and reconnect/resume behavior before implementation."
            ),
        },
    ),
    DomainAdapter(
        adapter_id="commerce",
        display_name="Commerce Application",
        aliases=("ecommerce", "e-commerce", "online store", "marketplace", "shopping cart"),
        acceptance_criteria=(
            "Money uses integer minor units or an exact decimal representation.",
            "Cart, inventory, order, and payment transitions are idempotent and tested.",
        ),
        prompt_guidance={
            WorkerKind.BACKEND: (
                "Commerce adapter: use exact money types, idempotent mutations, explicit order "
                "states, inventory conflict handling, and no client-trusted totals."
            ),
            WorkerKind.FRONTEND: (
                "Commerce adapter: render server-confirmed prices and states, preserve cart error "
                "recovery, and test duplicate submission and inventory-conflict paths."
            ),
        },
    ),
    DomainAdapter(
        adapter_id="analytics",
        display_name="Analytics and Data Application",
        aliases=(
            "analytics",
            "analytics dashboard",
            "business intelligence",
            "data dashboard",
            "reporting app",
        ),
        acceptance_criteria=(
            "Empty, loading, partial, and invalid datasets render without runtime failure.",
            "Aggregations, filters, time zones, and numeric formatting have deterministic tests.",
        ),
        prompt_guidance={
            WorkerKind.FRONTEND: (
                "Analytics adapter: test empty and partial datasets, preserve accessible tabular "
                "alternatives for charts, and keep filtering and time-zone behavior deterministic."
            ),
            WorkerKind.BACKEND: (
                "Analytics adapter: make aggregation boundaries, time zones, pagination, and null "
                "semantics explicit and test them with representative datasets."
            ),
        },
    ),
    DomainAdapter(
        adapter_id="auth-rbac",
        display_name="Authentication and Role-Based Access",
        aliases=(
            "authentication",
            "login",
            "sign in",
            "role-based",
            "role based",
            "rbac",
            "admin only",
            "user account",
        ),
        acceptance_criteria=(
            "Authentication and authorization are enforced on the server, not only hidden in the UI.",
            "Unauthorized and forbidden paths are covered by executable tests.",
            "Secrets and privileged credentials never reach browser bundles.",
        ),
        prompt_guidance={
            WorkerKind.BACKEND: (
                "Auth/RBAC adapter: verify identity server-side on every protected route, enforce "
                "roles independently of UI state, return distinct 401/403 responses, and test "
                "anonymous, wrong-role, and permitted requests. Never trust a client-supplied role."
            ),
            WorkerKind.FRONTEND: (
                "Auth/RBAC adapter: provide explicit signed-out, loading, expired-session, and "
                "forbidden states. UI route guards improve UX but never replace server authorization."
            ),
            WorkerKind.DATABASE: (
                "Auth/RBAC adapter: connect application profiles to immutable auth identities and "
                "apply least-privilege row policies for user and administrator access."
            ),
        },
    ),
    DomainAdapter(
        adapter_id="persistence",
        display_name="Persistent Data Application",
        aliases=(
            "database",
            "persistent",
            "persistence",
            "postgres",
            "postgresql",
            "supabase",
            "store data",
            "save data",
        ),
        acceptance_criteria=(
            "Schema migrations are repeatable and the runtime uses the requested persistent store.",
            "Constraints, indexes, lifecycle timestamps, and representative seed data are explicit.",
            "Persistence failures have deterministic error handling and integration tests.",
        ),
        prompt_guidance={
            WorkerKind.DATABASE: (
                "Persistence adapter: generate idempotent PostgreSQL migrations, constraints, "
                "indexes, least-privilege policies, and representative deterministic seed data."
            ),
            WorkerKind.BACKEND: (
                "Persistence adapter: use the configured database in runtime request paths, manage "
                "transactions explicitly, map storage errors safely, and test persistence behavior."
            ),
        },
    ),
    DomainAdapter(
        adapter_id="multi-tenant",
        display_name="Multi-Tenant Application",
        aliases=("multi-tenant", "multitenant", "organizations", "workspaces", "tenant isolation"),
        acceptance_criteria=(
            "Every tenant-owned query is scoped by trusted server-side identity.",
            "Cross-tenant reads and writes are rejected by tests and database policy.",
        ),
        prompt_guidance={
            WorkerKind.BACKEND: (
                "Multi-tenant adapter: derive tenant identity from verified membership, scope every "
                "query server-side, and test cross-tenant read and mutation rejection."
            ),
            WorkerKind.DATABASE: (
                "Multi-tenant adapter: include tenant foreign keys, composite uniqueness where "
                "needed, indexed tenant filters, and defense-in-depth row security."
            ),
        },
    ),
    DomainAdapter(
        adapter_id="file-upload",
        display_name="File Upload Application",
        aliases=(
            "file upload",
            "file uploads",
            "upload files",
            "uploading files",
            "image upload",
            "photo upload",
            "video upload",
            "audio upload",
            "document upload",
            "media upload",
            "attachment upload",
            "avatar upload",
        ),
        acceptance_criteria=(
            "Uploads enforce authorization, size, content-type, and safe object-name policies.",
            "Failed and interrupted uploads are recoverable and covered by tests.",
        ),
        prompt_guidance={
            WorkerKind.BACKEND: (
                "File-upload adapter: stream with bounded size, validate claimed and detected media "
                "types, generate safe storage keys, require authorization, and test rejection paths. "
                "Expose one documented maximum upload size for the frontend contract."
            ),
            WorkerKind.FRONTEND: (
                "File-upload adapter: show progress, validation, cancellation, retry, and accessible "
                "error states without treating browser MIME metadata as authoritative. Never advertise "
                "or accept a larger file than the backend's configured maximum."
            ),
        },
    ),
    DomainAdapter(
        adapter_id="ai-integration",
        display_name="AI-Integrated Application",
        aliases=("openai", "llm", "ai assistant", "ai generation", "chatbot", "generative ai"),
        acceptance_criteria=(
            "Model credentials and provider calls remain server-side.",
            "Timeout, quota, malformed-response, and moderation paths fail safely.",
            "Model output is treated as untrusted data before persistence or rendering.",
        ),
        prompt_guidance={
            WorkerKind.BACKEND: (
                "AI adapter: keep provider credentials server-side, bound input and output, set "
                "timeouts, validate structured responses, and test quota and malformed-output paths."
            ),
            WorkerKind.FRONTEND: (
                "AI adapter: provide streaming/loading, cancellation, retry, and recoverable failure "
                "states; render model output as untrusted content."
            ),
        },
    ),
    DomainAdapter(
        adapter_id="content-platform",
        display_name="Content Platform",
        aliases=("content platform", "blog", "cms", "publishing platform", "movie catalog"),
        acceptance_criteria=(
            "Draft, published, empty, and unavailable content states are explicit.",
            "Content ownership and publication permissions are enforced server-side when applicable.",
        ),
        prompt_guidance={
            WorkerKind.FRONTEND: (
                "Content adapter: create intentional browse, detail, empty, loading, and not-found "
                "surfaces with semantic navigation and responsive media treatment."
            ),
            WorkerKind.BACKEND: (
                "Content adapter: model draft/published lifecycle, ownership, pagination, stable "
                "identifiers, and permission-aware queries."
            ),
        },
    ),
    DomainAdapter(
        adapter_id="scheduling",
        display_name="Scheduling Application",
        aliases=("scheduling", "booking", "appointments", "calendar", "reservations"),
        acceptance_criteria=(
            "Time zones, daylight-saving transitions, conflicts, and cancellation states are explicit.",
            "Concurrent booking conflicts are rejected atomically and tested.",
        ),
        prompt_guidance={
            WorkerKind.BACKEND: (
                "Scheduling adapter: store canonical instants with explicit display zones, enforce "
                "conflicts atomically, and test daylight-saving and concurrent booking boundaries."
            ),
            WorkerKind.FRONTEND: (
                "Scheduling adapter: expose the active time zone and clear availability, conflict, "
                "confirmation, cancellation, and empty states."
            ),
        },
    ),
    DomainAdapter(
        adapter_id="geospatial",
        display_name="Geospatial Application",
        aliases=(
            "map",
            "maps",
            "geospatial",
            "location tracking",
            "nearby places",
            "route planner",
        ),
        acceptance_criteria=(
            "Coordinate order, units, permissions, empty results, and denied geolocation are explicit.",
            "Map features remain usable with keyboard-accessible non-map alternatives.",
        ),
        prompt_guidance={
            WorkerKind.FRONTEND: (
                "Geospatial adapter: provide permission-denied and unavailable-location states, "
                "document coordinate order, and include an accessible list alternative to the map."
            ),
            WorkerKind.BACKEND: (
                "Geospatial adapter: validate latitude/longitude bounds, make distance units explicit, "
                "and use indexed spatial or bounded queries with deterministic tests."
            ),
        },
    ),
)


def domain_adapter_registry() -> dict[str, DomainAdapter]:
    return {adapter.adapter_id: adapter for adapter in DOMAIN_ADAPTERS}


def resolve_adapter_ids(
    prompt: str,
    capability_id: str,
    metadata: dict[str, Any] | None = None,
) -> list[str]:
    """Select one stack adapter and only the positively indicated domain adapters."""

    requested = (metadata or {}).get("adapter_ids", [])
    if isinstance(requested, str):
        requested = [item.strip() for item in requested.split(",") if item.strip()]
    explicit = [str(item) for item in requested if str(item) in domain_adapter_registry()]
    detected = [
        adapter.adapter_id
        for adapter in DOMAIN_ADAPTERS
        if any(_has_positive_term(prompt, alias) for alias in adapter.aliases)
    ]
    return list(dict.fromkeys(["core", f"stack:{capability_id}", *explicit, *detected]))


def adapter_acceptance_criteria(adapter_ids: list[str]) -> list[str]:
    registry = domain_adapter_registry()
    return [
        criterion
        for adapter_id in adapter_ids
        if (adapter := registry.get(adapter_id)) is not None
        for criterion in adapter.acceptance_criteria
    ]


def adapter_prompt_guidance(adapter_ids: list[str], worker_kind: WorkerKind) -> str:
    registry = domain_adapter_registry()
    guidance = [
        text
        for adapter_id in adapter_ids
        if (adapter := registry.get(adapter_id)) is not None
        if (text := adapter.prompt_guidance.get(worker_kind))
    ]
    return "\n".join(guidance)


def _has_positive_term(prompt: str, term: str) -> bool:
    normalized = prompt.lower().replace("’", "'")
    escaped = re.escape(term.lower()).replace(r"\ ", r"\s+")
    for match in re.finditer(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", normalized):
        prefix = normalized[max(0, match.start() - 32) : match.start()]
        if not re.search(r"\b(?:no|not|without|exclude|avoid)\b[^.;\n]{0,24}$", prefix):
            return True
    return False
