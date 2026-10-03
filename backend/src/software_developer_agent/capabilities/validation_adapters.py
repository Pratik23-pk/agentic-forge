from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from software_developer_agent.capabilities.models import ProjectSpec
from software_developer_agent.models.job_state import WorkerKind


@dataclass(frozen=True, slots=True)
class AdapterFinding:
    adapter_id: str
    code: str
    message: str
    worker_kind: WorkerKind
    blocking: bool = True
    paths: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["worker_kind"] = self.worker_kind.value
        return payload


@dataclass(slots=True)
class AdapterValidationResult:
    checks: list[str] = field(default_factory=list)
    findings: list[AdapterFinding] = field(default_factory=list)

    @property
    def blocking_findings(self) -> list[AdapterFinding]:
        return [finding for finding in self.findings if finding.blocking]

    @property
    def advisories(self) -> list[AdapterFinding]:
        return [finding for finding in self.findings if not finding.blocking]


ROLE_QUERY = re.compile(
    r"(?:get|find|query)ByRole\(\s*['\"]heading['\"]\s*,\s*\{[^}]*?"
    r"name\s*:\s*/(?P<label>[^/\n]+)/[a-z]*",
    re.IGNORECASE | re.DOTALL,
)
ALT_QUERY = re.compile(
    r"(?:get|find|query)ByAltText\(\s*/(?P<label>[^/\n]+)/[a-z]*\s*\)",
    re.IGNORECASE,
)
HEADING_ELEMENT = re.compile(
    r"<(?:h[1-6]|[^>\s]+[^>]*\srole=['\"]heading['\"])[^>]*>(?P<text>.*?)</[^>]+>",
    re.IGNORECASE | re.DOTALL,
)
ALT_ATTRIBUTE = re.compile(r"\balt\s*=\s*['\"](?P<text>[^'\"]+)['\"]", re.IGNORECASE)
EXTERNAL_ASSET = re.compile(
    r"(?:src|poster)\s*=\s*(?:\{?['\"])(https?://[^'\"}\s]+)",
    re.IGNORECASE,
)


def validate_with_adapters(root: Path, project_spec: ProjectSpec) -> AdapterValidationResult:
    """Run deterministic preflight checks selected by the resolved adapters."""

    result = AdapterValidationResult()
    for adapter_id in project_spec.adapter_ids or [f"stack:{project_spec.capability_id}"]:
        result.checks.append(f"adapter_selected:{adapter_id}")

    if project_spec.frontend_framework and (root / "frontend").exists():
        result.findings.extend(_frontend_semantic_findings(root))
        result.findings.extend(_preview_asset_findings(root))
        result.checks.extend(
            [
                "adapter_frontend_semantics",
                "adapter_preview_assets",
            ]
        )
    selected = set(project_spec.adapter_ids)
    if "auth-rbac" in selected:
        result.findings.extend(_auth_rbac_findings(root))
        result.checks.append("adapter_auth_rbac")
    if "persistence" in selected:
        result.findings.extend(_persistence_findings(root))
        result.checks.append("adapter_persistence")
    if "multi-tenant" in selected:
        result.findings.extend(_multi_tenant_findings(root))
        result.checks.append("adapter_multi_tenant")
    if "file-upload" in selected:
        result.findings.extend(_file_upload_findings(root))
        result.checks.append("adapter_file_upload")
    if "ai-integration" in selected:
        result.findings.extend(_ai_integration_findings(root))
        result.checks.append("adapter_ai_integration")
    if "video-platform" in selected:
        result.findings.extend(_video_findings(root))
        result.checks.append("adapter_video_platform")
    if "realtime" in selected:
        result.findings.extend(_realtime_findings(root))
        result.checks.append("adapter_realtime")
    if "commerce" in selected:
        result.findings.extend(_commerce_findings(root))
        result.checks.append("adapter_commerce")
    if "analytics" in selected:
        result.findings.extend(_analytics_findings(root))
        result.checks.append("adapter_analytics")
    return result


def _auth_rbac_findings(root: Path) -> list[AdapterFinding]:
    runtime, runtime_paths = _component_text(root, "backend", tests=False)
    tests, test_paths = _component_text(root, "backend", tests=True)
    if not runtime:
        return [
            _missing(
                "auth-rbac",
                "server_auth_missing",
                "Authentication requires a backend enforcement boundary.",
                WorkerKind.BACKEND,
            )
        ]
    has_identity = _contains_any(
        runtime, ("authorization", "bearer", "get_user", "current_user", "jwt", "session")
    )
    has_denial = _has_http_denial(runtime, 401) and _has_http_denial(runtime, 403)
    findings: list[AdapterFinding] = []
    if not (has_identity and has_denial):
        findings.append(
            _missing(
                "auth-rbac",
                "server_authorization_unproven",
                "Protected access is requested, but server-side identity verification with 401/403 enforcement is not evident.",
                WorkerKind.BACKEND,
                runtime_paths,
            )
        )
    if not (
        _contains_any(tests, ("401", "403"))
        and _contains_any(tests, ("unauthor", "forbidden", "role", "auth"))
    ):
        findings.append(
            _missing(
                "auth-rbac",
                "authorization_tests_missing",
                "Backend tests must prove anonymous or wrong-role requests are rejected.",
                WorkerKind.BACKEND,
                test_paths,
            )
        )
    return findings


def _has_http_denial(runtime: str, status_code: int) -> bool:
    return bool(
        re.search(
            rf"(?:status_code\s*=\s*|api_error\(\s*|apierror\(\s*|"
            rf"httpexception\(\s*|\.status\(\s*){status_code}\b",
            runtime,
            re.IGNORECASE,
        )
        or re.search(
            rf"\b(?:[a-z_]*(?:error|exception)|apierror)\s*\("
            rf"[^)\n]*\b{status_code}\b[^)\n]*\)",
            runtime,
            re.IGNORECASE,
        )
        or re.search(
            rf"\braise\s+[A-Za-z_][A-Za-z0-9_]*\s*\(\s*{status_code}\b",
            runtime,
            re.IGNORECASE,
        )
        or re.search(
            rf"status\.http_{status_code}_[a-z_]+\b",
            runtime,
            re.IGNORECASE,
        )
    )


def _persistence_findings(root: Path) -> list[AdapterFinding]:
    migrations = (
        tuple(
            path.relative_to(root).as_posix()
            for path in (root / "database").rglob("*.sql")
            if path.is_file()
        )
        if (root / "database").exists()
        else ()
    )
    runtime, runtime_paths = _component_text(root, "backend", tests=False)
    findings: list[AdapterFinding] = []
    if not migrations:
        findings.append(
            _missing(
                "persistence",
                "migration_missing",
                "Persistent data was requested, but no versioned SQL migration is present.",
                WorkerKind.DATABASE,
            )
        )
    if not _contains_any(
        runtime, ("database_url", "supabase", "postgres", "psycopg", "sqlalchemy", "create_client")
    ):
        findings.append(
            _missing(
                "persistence",
                "runtime_persistence_missing",
                "The backend does not visibly connect runtime operations to the requested persistent store.",
                WorkerKind.BACKEND,
                runtime_paths,
            )
        )
    return findings


def _multi_tenant_findings(root: Path) -> list[AdapterFinding]:
    runtime, paths = _component_text(root, "backend", tests=False)
    if _contains_any(runtime, ("tenant_id", "organization_id", "workspace_id")) and _contains_any(
        runtime, ("current_user", "membership", "authorization", "jwt")
    ):
        return []
    return [
        _missing(
            "multi-tenant",
            "tenant_scope_unproven",
            "Multi-tenant access is requested, but trusted server-side tenant scoping is not evident.",
            WorkerKind.BACKEND,
            paths,
        )
    ]


def _file_upload_findings(root: Path) -> list[AdapterFinding]:
    runtime, paths = _component_text(root, "backend", tests=False)
    frontend_runtime, frontend_paths = _component_text(root, "frontend", tests=False)
    has_upload = _contains_any(runtime, ("uploadfile", "multipart", "multer", "formdata"))
    has_policy = _contains_any(
        runtime, ("content_type", "mimetype", "file_size", "max_size", "content-length")
    )
    findings: list[AdapterFinding] = []
    if not has_upload or not has_policy:
        findings.append(
            _missing(
            "file-upload",
            "upload_policy_missing",
            "File uploads require a server-side upload handler with bounded size and content-type validation.",
            WorkerKind.BACKEND,
            paths,
        )
        )

    backend_limits = _upload_limit_values(runtime)
    frontend_limits = _upload_limit_values(frontend_runtime)
    if backend_limits and frontend_limits:
        server_limit = min(backend_limits)
        browser_limit = max(frontend_limits)
        if browser_limit > server_limit:
            findings.append(
                _missing(
                    "file-upload",
                    "upload_limit_mismatch",
                    "Frontend upload limit exceeds the server limit; use one shared maximum "
                    f"(frontend {browser_limit} bytes, backend {server_limit} bytes).",
                    WorkerKind.FRONTEND,
                    frontend_paths,
                )
            )
    return findings


def _upload_limit_values(source: str) -> set[int]:
    values: set[int] = set()
    name_pattern = r"[A-Za-z0-9_]*(?:max|limit)[A-Za-z0-9_]*(?:upload|file|size|bytes)[A-Za-z0-9_]*"
    reverse_name_pattern = r"[A-Za-z0-9_]*(?:upload|file)[A-Za-z0-9_]*(?:max|limit|size|bytes)[A-Za-z0-9_]*"
    for match in re.finditer(
        rf"(?:{name_pattern}|{reverse_name_pattern})\s*(?::[^=;\n]+)?=\s*(?P<value>[0-9][0-9\s*()]*)",
        source,
        re.IGNORECASE,
    ):
        if value := _integer_product(match.group("value")):
            values.add(value)
    for match in re.finditer(
        rf"(?:getenv|environ\.get)\(\s*['\"](?:{name_pattern}|{reverse_name_pattern})['\"]\s*,\s*['\"]?(?P<value>[0-9][0-9\s*()]*)",
        source,
        re.IGNORECASE,
    ):
        if value := _integer_product(match.group("value")):
            values.add(value)
    return values


def _integer_product(expression: str) -> int | None:
    normalized = expression.replace("(", "").replace(")", "").strip()
    if not re.fullmatch(r"[0-9]+(?:\s*\*\s*[0-9]+)*", normalized):
        return None
    result = 1
    for factor in normalized.split("*"):
        result *= int(factor.strip())
    return result


def _ai_integration_findings(root: Path) -> list[AdapterFinding]:
    runtime, paths = _component_text(root, "backend", tests=False)
    findings: list[AdapterFinding] = []
    if not runtime or not _contains_any(
        runtime, ("openai", "responses.create", "chat.completions", "llm")
    ):
        findings.append(
            _missing(
                "ai-integration",
                "server_model_boundary_missing",
                "AI provider calls must be implemented behind a server-side boundary.",
                WorkerKind.BACKEND,
                paths,
            )
        )
    elif not _contains_any(runtime, ("timeout", "try:", "catch (", "except ")):
        findings.append(
            _missing(
                "ai-integration",
                "provider_failure_handling_missing",
                "AI provider timeout and failure handling is not evident.",
                WorkerKind.BACKEND,
                paths,
                blocking=False,
            )
        )
    return findings


def _video_findings(root: Path) -> list[AdapterFinding]:
    frontend, paths = _component_text(root, "frontend", tests=False)
    if _contains_any(frontend, ("<video", "react-player", "hls.js", "dash.js")):
        return []
    return [
        _missing(
            "video-platform",
            "playback_surface_missing",
            "Video functionality is requested, but no standards-based playback surface is present.",
            WorkerKind.FRONTEND,
            paths,
        )
    ]


def _realtime_findings(root: Path) -> list[AdapterFinding]:
    frontend, frontend_paths = _component_text(root, "frontend", tests=False)
    backend, backend_paths = _component_text(root, "backend", tests=False)
    combined = f"{frontend}\n{backend}"
    paths = (*frontend_paths, *backend_paths)
    findings: list[AdapterFinding] = []
    if not _contains_any(combined, ("websocket", "eventsource", "socket.io", "server-sent")):
        findings.append(
            _missing(
                "realtime",
                "realtime_transport_missing",
                "Real-time behavior is requested, but no WebSocket or server-sent event transport is evident.",
                WorkerKind.BACKEND,
                paths,
            )
        )
    elif not _contains_any(
        combined, ("reconnect", "retry", "offline", "deduplic", "last_event_id")
    ):
        findings.append(
            _missing(
                "realtime",
                "reconnect_policy_missing",
                "The real-time transport lacks an explicit reconnect or duplicate-event recovery policy.",
                WorkerKind.FRONTEND,
                paths,
                blocking=False,
            )
        )
    return findings


def _commerce_findings(root: Path) -> list[AdapterFinding]:
    runtime, paths = _component_text(root, "backend", tests=False)
    tests, test_paths = _component_text(root, "backend", tests=True)
    findings: list[AdapterFinding] = []
    if runtime and not _uses_exact_money(runtime):
        findings.append(
            _missing(
                "commerce",
                "exact_money_missing",
                "Commerce runtime must represent money with integer minor units or an exact decimal type.",
                WorkerKind.BACKEND,
                paths,
            )
        )
    has_duplicate_test = _contains_any(tests, ("idempot", "duplicate", "replay"))
    has_conflict_test = _contains_any(
        tests,
        ("insufficient", "inventory", "balance", "conflict"),
    )
    if runtime and not (has_duplicate_test and has_conflict_test):
        findings.append(
            _missing(
                "commerce",
                "transaction_edge_tests_missing",
                "Commerce tests should cover duplicate submission and balance or inventory conflicts.",
                WorkerKind.BACKEND,
                test_paths,
            )
        )
    return findings


def _uses_exact_money(runtime: str) -> bool:
    if _contains_any(
        runtime,
        (
            "decimal",
            "minor_unit",
            "minorunit",
            "amount_cents",
            "amountcents",
            "price_cents",
            "pricecents",
            "balance_cents",
            "balancecents",
        ),
    ):
        return True
    money_name = (
        r"(?:amount|balance|cost|price|total|wallet(?:_balance)?)"
        r"(?:_(?:cents?|minor(?:_units?)?)|(?:cents?|minor(?:units?)?))?"
    )
    return bool(
        re.search(rf"\b{money_name}\s*:\s*(?:int|integer|decimal|numeric|bigint|number)\b", runtime)
        or re.search(
            rf"\b{money_name}\s*=\s*(?:column|mapped_column)\(\s*(?:integer|numeric)",
            runtime,
        )
        or re.search(
            rf"\b{money_name}\s+(?:int|integer|decimal|numeric|bigint)\b",
            runtime,
        )
    )


def _analytics_findings(root: Path) -> list[AdapterFinding]:
    tests, paths = _component_text(root, "frontend", tests=True)
    if _contains_any(tests, ("empty", "no data", "partial", "loading")):
        return []
    return [
        _missing(
            "analytics",
            "dataset_state_tests_missing",
            "Analytics UI tests should cover empty or partial datasets.",
            WorkerKind.FRONTEND,
            paths,
            blocking=False,
        )
    ]


def _component_text(root: Path, component: str, *, tests: bool) -> tuple[str, tuple[str, ...]]:
    component_root = root / component
    if not component_root.exists():
        return "", ()
    paths = [
        path
        for path in component_root.rglob("*")
        if path.is_file()
        and "node_modules" not in path.parts
        and path.suffix.lower() in {".js", ".jsx", ".mjs", ".py", ".ts", ".tsx"}
        and _is_test_file(path.name) is tests
    ]
    return (
        "\n".join(path.read_text(encoding="utf-8", errors="replace").lower() for path in paths),
        tuple(path.relative_to(root).as_posix() for path in paths[:12]),
    )


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _missing(
    adapter_id: str,
    code: str,
    message: str,
    worker_kind: WorkerKind,
    paths: tuple[str, ...] = (),
    *,
    blocking: bool = True,
) -> AdapterFinding:
    return AdapterFinding(
        adapter_id=adapter_id,
        code=code,
        message=message,
        worker_kind=worker_kind,
        blocking=blocking,
        paths=paths,
    )


def _frontend_semantic_findings(root: Path) -> list[AdapterFinding]:
    frontend = root / "frontend"
    test_files = [
        path
        for path in frontend.rglob("*")
        if path.is_file()
        and _is_test_file(path.name)
        and path.suffix in {".js", ".jsx", ".ts", ".tsx"}
    ]
    source_files = [
        path
        for path in frontend.rglob("*")
        if path.is_file()
        and not _is_test_file(path.name)
        and "node_modules" not in path.parts
        and path.suffix in {".js", ".jsx", ".ts", ".tsx"}
    ]
    source_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in source_files
    )
    heading_matches = list(HEADING_ELEMENT.finditer(source_text))
    heading_texts = [_visible_text(match.group("text")) for match in heading_matches]
    has_dynamic_heading = any("{" in match.group("text") for match in heading_matches)
    alt_texts = [match.group("text") for match in ALT_ATTRIBUTE.finditer(source_text)]
    findings: list[AdapterFinding] = []

    for test_file in test_files:
        test_text = test_file.read_text(encoding="utf-8", errors="replace")
        relative_test = test_file.relative_to(root).as_posix()
        for match in ROLE_QUERY.finditer(test_text):
            label = _literal_query(match.group("label"))
            if not label or any(_query_matches(label, heading) for heading in heading_texts):
                continue
            if _normalize_text(label) not in _normalize_text(source_text):
                continue
            if has_dynamic_heading:
                findings.append(
                    AdapterFinding(
                        adapter_id="stack:react-accessibility",
                        code="dynamic_heading_requires_runtime_verification",
                        message=(
                            f"{relative_test}:{_line_number(test_text, match.start())} queries for "
                            f"heading {label!r}, and the source renders data-driven headings. "
                            "Executable tests must determine the result."
                        ),
                        worker_kind=WorkerKind.FRONTEND,
                        blocking=False,
                        paths=(relative_test, *(_relative_paths(root, source_files))),
                        metadata={
                            "line": _line_number(test_text, match.start()),
                            "expected": f"runtime heading matching {label!r}",
                            "actual": "static analysis is inconclusive for a JSX expression",
                        },
                    )
                )
                continue
            findings.append(
                AdapterFinding(
                    adapter_id="stack:react-accessibility",
                    code="test_heading_role_mismatch",
                    message=(
                        f"{relative_test}:{_line_number(test_text, match.start())} queries for "
                        f"heading {label!r}, but that visible text is not rendered as a heading."
                    ),
                    worker_kind=WorkerKind.FRONTEND,
                    paths=(relative_test, *(_relative_paths(root, source_files))),
                    metadata={
                        "line": _line_number(test_text, match.start()),
                        "expected": f"visible heading matching {label!r}",
                        "actual": "matching text is rendered only in a non-heading element",
                    },
                )
            )
        for match in ALT_QUERY.finditer(test_text):
            label = _literal_query(match.group("label"))
            matches = [alt for alt in alt_texts if label and _query_matches(label, alt)]
            if len(matches) <= 1:
                continue
            findings.append(
                AdapterFinding(
                    adapter_id="stack:react-accessibility",
                    code="singular_alt_query_is_ambiguous",
                    message=(
                        f"{relative_test}:{_line_number(test_text, match.start())} uses a singular "
                        f"alt-text query matching {len(matches)} images. Use unique accessible names "
                        "or an explicitly plural assertion."
                    ),
                    worker_kind=WorkerKind.FRONTEND,
                    paths=(relative_test, *(_relative_paths(root, source_files))),
                    metadata={
                        "line": _line_number(test_text, match.start()),
                        "expected": "one matching accessible image",
                        "actual": f"{len(matches)} matching accessible images",
                    },
                )
            )
    return findings


def _preview_asset_findings(root: Path) -> list[AdapterFinding]:
    findings: list[AdapterFinding] = []
    for path in (root / "frontend").rglob("*"):
        if (
            not path.is_file()
            or _is_test_file(path.name)
            or "node_modules" in path.parts
            or path.suffix not in {".html", ".js", ".jsx", ".ts", ".tsx"}
        ):
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        urls = sorted({match.group(1) for match in EXTERNAL_ASSET.finditer(content)})
        if not urls:
            continue
        findings.append(
            AdapterFinding(
                adapter_id="core",
                code="external_preview_asset",
                message=(
                    f"{path.relative_to(root).as_posix()} references {len(urls)} external runtime "
                    "asset(s). The isolated preview may show placeholders when outbound network "
                    "access is disabled."
                ),
                worker_kind=WorkerKind.FRONTEND,
                blocking=False,
                paths=(path.relative_to(root).as_posix(),),
                metadata={"urls": urls[:10]},
            )
        )
    return findings


def _is_test_file(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered.startswith("test_")
        and lowered.endswith(".py")
        or lowered.endswith("_test.py")
        or any(marker in lowered for marker in (".test.", ".spec.", "_test."))
    )


def _visible_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    without_expressions = re.sub(r"\{[^{}]*\}", " ", without_tags)
    return _normalize_text(without_expressions)


def _literal_query(value: str) -> str:
    if re.search(r"[\[\]().*+?{}|]", value):
        return ""
    return value.replace(r"\s", " ").replace(r"\/", "/").strip()


def _query_matches(query: str, value: str) -> bool:
    return _normalize_text(query) in _normalize_text(value)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("’", "'").lower()).strip()


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _relative_paths(root: Path, paths: list[Path]) -> tuple[str, ...]:
    return tuple(path.relative_to(root).as_posix() for path in paths[:12])
