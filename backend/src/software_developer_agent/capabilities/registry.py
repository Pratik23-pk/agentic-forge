from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from software_developer_agent.capabilities.adapters import (
    adapter_acceptance_criteria,
    resolve_adapter_ids,
)
from software_developer_agent.capabilities.models import ProjectSpec
from software_developer_agent.models.job_state import WorkerKind
from software_developer_agent.models.request_policy import RequestPolicy, derive_request_policy


@dataclass(frozen=True, slots=True)
class CapabilityPack:
    """Stack-specific planning, prompting, runtime, and validation contract."""

    capability_id: str
    display_name: str
    application_type: str
    aliases: tuple[str, ...]
    worker_kinds: tuple[WorkerKind, ...]
    frontend_framework: str | None
    backend_framework: str | None
    primary_languages: tuple[str, ...]
    runtime_versions: dict[str, str]
    package_managers: dict[str, str]
    ports: dict[str, int]
    allowed_npm_commands: frozenset[str] = field(default_factory=frozenset)
    prompt_guidance: dict[WorkerKind, str] = field(default_factory=dict)
    required_paths: tuple[str, ...] = ()

    def project_spec(
        self,
        *,
        policy: RequestPolicy,
        explicitly_selected: bool,
        confidence: float,
    ) -> ProjectSpec:
        criteria = [
            "All declared dependency installation commands succeed.",
            "All generated tests pass.",
            "The production build succeeds when the stack has a build step.",
            "The application starts locally and its primary workflow succeeds.",
            "Generated documentation references only files and commands that exist.",
        ]
        return ProjectSpec(
            capability_id=self.capability_id,
            application_type=self.application_type,
            frontend_framework=self.frontend_framework,
            backend_framework=self.backend_framework,
            primary_languages=list(self.primary_languages),
            runtime_versions=dict(self.runtime_versions),
            package_managers=dict(self.package_managers),
            ports=dict(self.ports),
            requested_features=sorted(policy.requested_capabilities),
            excluded_features=sorted(policy.excluded_capabilities),
            acceptance_criteria=criteria,
            explicitly_selected=explicitly_selected,
            confidence=confidence,
        )


COMMON_NPM_COMMANDS = frozenset(
    {"eslint", "jest", "node", "react-scripts", "tsc", "vite", "vitest"}
)


CAPABILITY_PACKS: tuple[CapabilityPack, ...] = (
    CapabilityPack(
        capability_id="nextjs-fullstack",
        display_name="Next.js Full-stack TypeScript",
        application_type="fullstack_web_application",
        aliases=("next.js", "nextjs", "next js"),
        worker_kinds=(WorkerKind.FRONTEND,),
        frontend_framework="Next.js",
        backend_framework="Next.js route handlers",
        primary_languages=("TypeScript",),
        runtime_versions={"node": "20"},
        package_managers={"javascript": "npm"},
        ports={"application": 3000, "frontend": 3000},
        allowed_npm_commands=COMMON_NPM_COMMANDS | {"next"},
        required_paths=("frontend/package.json",),
        prompt_guidance={
            WorkerKind.FRONTEND: """Certified stack: Next.js full-stack with TypeScript.
Generate one complete Next.js application under frontend/ using the App Router. Backend behavior
belongs in route handlers or server actions inside the same Next.js project; do not create or call
a separate FastAPI service unless the user explicitly requests one. Use server components by
default, client components only where interactivity requires them, typed route payloads, secure
server-only secrets, accessible UI, focused Vitest tests, and a production `next build`. Include
scripts for dev, test, build, and start. Do not generate Vite configuration or index.html."""
        },
    ),
    CapabilityPack(
        capability_id="react-fastapi",
        display_name="React/Vite + FastAPI",
        application_type="fullstack_web_application",
        aliases=("react fastapi", "fastapi react", "react and fastapi"),
        worker_kinds=(WorkerKind.BACKEND, WorkerKind.FRONTEND),
        frontend_framework="React with Vite",
        backend_framework="FastAPI",
        primary_languages=("TypeScript", "Python"),
        runtime_versions={"node": "20", "python": "3.11"},
        package_managers={"javascript": "npm", "python": "pip"},
        ports={"frontend": 5173, "backend": 8000},
        allowed_npm_commands=COMMON_NPM_COMMANDS,
        required_paths=("frontend/package.json", "backend/pyproject.toml"),
        prompt_guidance={
            WorkerKind.BACKEND: """Certified stack: Python 3.11 and FastAPI. Use typed Pydantic
models, a health endpoint, dependency injection where useful, exact pinned dependencies, pytest,
and a clean application factory or app entry point. Run Pyright-compatible typing.""",
            WorkerKind.FRONTEND: """Certified stack: React, TypeScript, and Vite. Use a typed API
client matching the shared FastAPI contract, accessible components, Vitest, and a production Vite
build. Keep server-only behavior in the backend.""",
        },
    ),
    CapabilityPack(
        capability_id="react-node",
        display_name="React/Vite + Node.js/Express",
        application_type="fullstack_web_application",
        aliases=("react node", "react express", "node react", "express react"),
        worker_kinds=(WorkerKind.BACKEND, WorkerKind.FRONTEND),
        frontend_framework="React with Vite",
        backend_framework="Express",
        primary_languages=("TypeScript",),
        runtime_versions={"node": "20"},
        package_managers={"javascript": "npm"},
        ports={"frontend": 5173, "backend": 8000},
        allowed_npm_commands=COMMON_NPM_COMMANDS,
        required_paths=("frontend/package.json", "backend/package.json"),
        prompt_guidance={
            WorkerKind.BACKEND: """Certified stack: Node.js, TypeScript, and Express. Generate a
backend/package.json rather than Python manifests. Include typed request validation, centralized
errors, a health endpoint, exact dependencies, Vitest or Jest tests, type checking, build, and start
scripts. Do not generate FastAPI or Python files.""",
            WorkerKind.FRONTEND: """Certified stack: React, TypeScript, and Vite. Match the shared
Express API contract exactly and include accessible UI, API tests, type checking, and Vitest.""",
        },
    ),
    CapabilityPack(
        capability_id="fastapi-api",
        display_name="FastAPI Service",
        application_type="backend_service",
        aliases=("fastapi", "python api", "python backend"),
        worker_kinds=(WorkerKind.BACKEND,),
        frontend_framework=None,
        backend_framework="FastAPI",
        primary_languages=("Python",),
        runtime_versions={"python": "3.11"},
        package_managers={"python": "pip"},
        ports={"backend": 8000},
        required_paths=("backend/pyproject.toml",),
        prompt_guidance={
            WorkerKind.BACKEND: """Certified stack: Python 3.11 and FastAPI. Generate only the
requested service, exact dependencies, Pyright-compatible typing, pytest API tests, health and
startup checks, and no frontend files."""
        },
    ),
    CapabilityPack(
        capability_id="node-api",
        display_name="Node.js/Express TypeScript Service",
        application_type="backend_service",
        aliases=("node.js backend", "node backend", "express api", "node api", "nestjs"),
        worker_kinds=(WorkerKind.BACKEND,),
        frontend_framework=None,
        backend_framework="Express",
        primary_languages=("TypeScript",),
        runtime_versions={"node": "20"},
        package_managers={"javascript": "npm"},
        ports={"backend": 8000},
        allowed_npm_commands=COMMON_NPM_COMMANDS,
        required_paths=("backend/package.json",),
        prompt_guidance={
            WorkerKind.BACKEND: """Certified stack: Node.js and TypeScript. Use Express unless the
user explicitly selects NestJS. Generate backend/package.json, typed validation, focused tests,
type checking, production build and start scripts. Do not generate Python files."""
        },
    ),
    CapabilityPack(
        capability_id="react-vite",
        display_name="React/Vite TypeScript Frontend",
        application_type="frontend_application",
        aliases=("react", "vite", "react.js", "reactjs"),
        worker_kinds=(WorkerKind.FRONTEND,),
        frontend_framework="React with Vite",
        backend_framework=None,
        primary_languages=("TypeScript",),
        runtime_versions={"node": "20"},
        package_managers={"javascript": "npm"},
        ports={"frontend": 5173},
        allowed_npm_commands=COMMON_NPM_COMMANDS,
        required_paths=("frontend/package.json",),
        prompt_guidance={
            WorkerKind.FRONTEND: """Certified stack: React, TypeScript, and Vite. Generate a
standalone frontend without inventing a backend. Include accessible responsive UI, deterministic
state, focused Vitest tests, exact dependencies, and a production Vite build. Deliver package.json,
tsconfig.json with the automatic JSX runtime, vite.config.ts, index.html, Vite environment types,
entry point, implementation, test setup when needed, and focused tests in the first manifest."""
        },
    ),
    CapabilityPack(
        capability_id="python-cli",
        display_name="Python Command-line Application",
        application_type="command_line_application",
        aliases=("python cli", "command line python", "python command-line"),
        worker_kinds=(WorkerKind.BACKEND,),
        frontend_framework=None,
        backend_framework="Python CLI",
        primary_languages=("Python",),
        runtime_versions={"python": "3.11"},
        package_managers={"python": "pip"},
        ports={},
        required_paths=("backend/pyproject.toml",),
        prompt_guidance={
            WorkerKind.BACKEND: """Certified stack: Python 3.11 command-line application. Do not
generate FastAPI or a network server. Provide a console entry point, argparse or Typer interface as
appropriate, deterministic exit codes, Pyright-compatible typing, exact dependencies, and pytest
CLI tests."""
        },
    ),
)


def capability_registry() -> dict[str, CapabilityPack]:
    return {pack.capability_id: pack for pack in CAPABILITY_PACKS}


def resolve_capability(capability_id: str) -> CapabilityPack:
    try:
        return capability_registry()[capability_id]
    except KeyError as exc:
        supported = ", ".join(sorted(capability_registry()))
        raise ValueError(
            f"Unsupported capability {capability_id!r}. Supported: {supported}."
        ) from exc


def resolve_project_spec(
    prompt: str,
    metadata: dict[str, Any] | None = None,
    policy: RequestPolicy | None = None,
) -> ProjectSpec:
    resolved_policy = policy or derive_request_policy(prompt)
    normalized_metadata = metadata or {}
    explicit = str(
        normalized_metadata.get("capability_id")
        or normalized_metadata.get("stack_id")
        or normalized_metadata.get("stack")
        or ""
    ).strip()
    if explicit:
        pack = resolve_capability(explicit)
        spec = pack.project_spec(
            policy=resolved_policy,
            explicitly_selected=True,
            confidence=1.0,
        )
        return _with_adapters(spec, prompt, normalized_metadata)

    lowered = prompt.lower()
    pack = _detect_capability(lowered, resolved_policy)
    spec = pack.project_spec(
        policy=resolved_policy,
        explicitly_selected=_mentions_alias(lowered, pack.aliases),
        confidence=0.96 if _mentions_alias(lowered, pack.aliases) else 0.72,
    )
    return _with_adapters(spec, prompt, normalized_metadata)


def required_workers(spec: ProjectSpec, policy: RequestPolicy) -> list[WorkerKind]:
    workers = list(resolve_capability(spec.capability_id).worker_kinds)
    if policy.excludes("backend"):
        workers = [worker for worker in workers if worker != WorkerKind.BACKEND]
    if policy.excludes("frontend"):
        workers = [worker for worker in workers if worker != WorkerKind.FRONTEND]
    if (policy.requests("database") or policy.requests("persistence")) and not policy.excludes(
        "database"
    ):
        workers.insert(0, WorkerKind.DATABASE)
    return list(dict.fromkeys(workers))


def worker_prompt_guidance(capability_id: str, worker_kind: WorkerKind) -> str:
    return resolve_capability(capability_id).prompt_guidance.get(worker_kind, "")


def _with_adapters(
    spec: ProjectSpec,
    prompt: str,
    metadata: dict[str, Any],
) -> ProjectSpec:
    spec.adapter_ids = resolve_adapter_ids(prompt, spec.capability_id, metadata)
    spec.acceptance_criteria = list(
        dict.fromkeys([*spec.acceptance_criteria, *adapter_acceptance_criteria(spec.adapter_ids)])
    )
    return spec


def _detect_capability(
    prompt: str,
    policy: RequestPolicy | None = None,
) -> CapabilityPack:
    if _contains_any(prompt, ("next.js", "nextjs", "next js")):
        return resolve_capability("nextjs-fullstack")
    if _contains_any(prompt, ("python cli", "python command-line", "command line python")):
        return resolve_capability("python-cli")
    if _contains_any(prompt, ("fastapi", "python api", "python backend")):
        if _looks_like_frontend(prompt):
            return resolve_capability("react-fastapi")
        return resolve_capability("fastapi-api")
    if _contains_any(prompt, ("express", "node.js", "nodejs", "node backend", "nestjs")):
        if _looks_like_frontend(prompt):
            return resolve_capability("react-node")
        return resolve_capability("node-api")
    if _contains_any(prompt, ("react", "vite", "frontend", "landing page", "website")):
        if _needs_backend(prompt, policy):
            return resolve_capability("react-fastapi")
        return resolve_capability("react-vite")
    if _contains_any(prompt, ("cli", "command line", "command-line")):
        return resolve_capability("python-cli")
    if policy is not None and policy.excludes("backend"):
        # An explicit exclusion must not fall through to a full-stack pack, or the
        # resolved spec advertises a backend framework the product will never have.
        return resolve_capability("react-vite")
    return resolve_capability("react-fastapi")


def _looks_like_frontend(prompt: str) -> bool:
    return _contains_any(
        prompt,
        (
            "app",
            "dashboard",
            "frontend",
            "full-stack",
            "fullstack",
            "game",
            "page",
            "react",
            "site",
            "ui",
            "web",
        ),
    ) and not _contains_any(prompt, ("api only", "backend only", "service only"))


def _needs_backend(prompt: str, policy: RequestPolicy | None = None) -> bool:
    if policy is not None and policy.excludes("backend"):
        return False
    return any(
        _has_positive_term(prompt, term)
        for term in (
            "admin",
            "api",
            "authentication",
            "backend",
            "database",
            "file upload",
            "full-stack",
            "fullstack",
            "login",
            "payment",
            "persistence",
            "role-based",
            "role based",
            "sign in",
            "supabase",
            "user account",
            "websocket",
        )
    )


def _has_positive_term(prompt: str, term: str) -> bool:
    escaped = re.escape(term).replace(r"\ ", r"\s+")
    for match in re.finditer(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", prompt):
        prefix = prompt[max(0, match.start() - 40) : match.start()]
        if not re.search(
            r"\b(?:no|not|without|exclude|excluding|avoid|do not|don't)\b[^.;\n]{0,32}$",
            prefix,
        ):
            return True
    return False


def _mentions_alias(prompt: str, aliases: tuple[str, ...]) -> bool:
    return any(_has_term(prompt, alias) for alias in aliases)


def _contains_any(prompt: str, terms: tuple[str, ...]) -> bool:
    return any(_has_term(prompt, term) for term in terms)


def _has_term(prompt: str, term: str) -> bool:
    if any(character in term for character in (".", "-", " ")):
        return term in prompt
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", prompt) is not None
