from __future__ import annotations

import ast
import json
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from textwrap import dedent
from typing import Any

from software_developer_agent.capabilities.templates import (
    deterministic_stack_files,
    deterministic_validation_commands,
    trusted_node_package,
    trusted_optional_node_dependencies,
)
from software_developer_agent.models.job_state import JobState, JobTask, TaskStatus, WorkerKind
from software_developer_agent.prompts.system_prompts import ARTIFACT_WRITER_SYSTEM_PROMPT

MAX_GENERATED_FILES = 120
MAX_FILE_CHARS = 300_000
BLOCKED_PATH_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    "node_modules",
}
WORKER_PATH_PREFIXES = {
    WorkerKind.DATABASE: "database/",
    WorkerKind.BACKEND: "backend/",
    WorkerKind.FRONTEND: "frontend/",
}
WORKER_MANIFEST_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "operation": {"type": "string", "enum": ["replace", "patch"]},
        "files": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_GENERATED_FILES,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
        "deleted_files": {
            "type": "array",
            "maxItems": MAX_GENERATED_FILES,
            "items": {"type": "string"},
        },
        "validation_commands": {
            "type": "array",
            "maxItems": 12,
            "items": {"type": "string"},
        },
        "notes": {
            "type": "array",
            "maxItems": 12,
            "items": {"type": "string"},
        },
    },
    "required": [
        "summary",
        "operation",
        "files",
        "deleted_files",
        "validation_commands",
        "notes",
    ],
    "additionalProperties": False,
}


class WorkerManifestScopeError(ValueError):
    pass


class WorkerManifestContractError(ValueError):
    pass


class ManifestConflictError(ValueError):
    def __init__(self, conflicts: dict[str, set[WorkerKind]]) -> None:
        self.conflicts = conflicts
        descriptions = [
            f"{path} ({', '.join(sorted(kind.value for kind in worker_kinds))})"
            for path, worker_kinds in sorted(conflicts.items())
        ]
        super().__init__("Conflicting worker files: " + "; ".join(descriptions))


@dataclass(slots=True)
class GeneratedFileSpec:
    path: str
    content: str
    worker_kind: WorkerKind


@dataclass(slots=True)
class WorkerFileManifest:
    worker_kind: WorkerKind
    summary: str
    files: list[GeneratedFileSpec] = field(default_factory=list)
    operation: str | None = None
    deleted_files: list[str] = field(default_factory=list)
    validation_commands: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def worker_manifest_prompt(task: JobTask, project_prompt: str, project_id: str) -> str:
    """Prompt contract for workers that generate project files for the artifact writer."""

    return (
        "You are generating source files for the Artifact Writer and Project Generator. "
        "You cannot directly edit the "
        "filesystem in this model call; instead, produce complete file specifications.\n\n"
        "Return only compact JSON with this exact shape:\n"
        "{"
        '"summary":"what was implemented",'
        '"operation":"replace|patch",'
        '"files":[{"path":"backend/src/app/main.py","content":"complete file text"}],'
        '"deleted_files":["path intentionally removed during repair"],'
        '"validation_commands":["command to run from project root"],'
        '"notes":["important local setup note"]'
        "}\n\n"
        "Rules:\n"
        "- Treat the original user request as the source of truth.\n"
        "- Explicit exclusions override defaults, templates, and keyword matches.\n"
        "- Generate real runnable code, not plans or TODO-only placeholders.\n"
        "- Keep source and tests conventionally formatted; never minify generated code. Precise "
        "line-level diagnostics are required for efficient repair.\n"
        "- Keep paths relative to the generated project root.\n"
        "- Use localhost-first architecture unless the user explicitly asks for hosting.\n"
        "- Use environment placeholders only; never invent or include real credentials.\n"
        "- Do not add GitHub, CI/CD, deployment, cloud, authentication, Docker, payments, "
        "databases, or external services unless positively requested.\n"
        "- Implement every positively requested medium literally: images require accessible image "
        "or project-local visual assets; icons, emoji, and descriptive text are not substitutes.\n"
        "- Never default to SQLite or another persistence technology.\n"
        "- Generate every dependency file referenced by setup instructions.\n"
        "- Before returning, verify the owned component has its dependency manifest, runtime "
        "configuration, entry point, implementation, focused tests, and matching test/build scripts.\n"
        "- Use only dependency versions supplied by the certified stack capability; never choose "
        "versions from memory or upgrade them.\n"
        "- On the first attempt use operation=replace and return the complete owned component.\n"
        "- During a repair use operation=patch, return only changed or new files, and list "
        "intentional removals in deleted_files. Unchanged checkpointed files are preserved.\n"
        "- A repair must address the supplied evidence directly. Do not rewrite working files, "
        "change product behavior, replace the application with a template, or broaden scope.\n"
        "- For a failing test that asserts requested behavior, trace the exact scenario through "
        "the implementation and repair its root cause. Never delete, skip, or weaken a valid test.\n"
        "- Never ask a question when the supplied project and failure evidence are sufficient.\n"
        "- Keep backend and frontend API routes, payloads, enums, and responses identical.\n"
        "- Include focused tests and executable validation commands.\n\n"
        "Artifact writer policy:\n"
        f"{ARTIFACT_WRITER_SYSTEM_PROMPT}\n\n"
        f"Project ID: {project_id}\n"
        f"Certified dependency policy: {_dependency_policy(task)}\n"
        f"Original user request:\n{project_prompt}\n\n"
        f"Worker task:\n{task.instructions}"
        + (
            "\n\nCanonical project context for this generation or repair:\n" + task.retry_context
            if task.retry_context
            else ""
        )
    )


def extract_worker_file_manifest(output: str, worker_kind: WorkerKind) -> WorkerFileManifest:
    payload = _extract_json_payload(output)
    if not isinstance(payload, dict):
        return WorkerFileManifest(worker_kind=worker_kind, summary="", files=[])

    files: list[GeneratedFileSpec] = []
    for item in payload.get("files", []):
        if not isinstance(item, dict):
            continue
        path = _safe_relative_path(str(item.get("path", "")))
        if path is None:
            continue
        content = item.get("content", "")
        if not isinstance(content, str):
            continue
        if len(content) > MAX_FILE_CHARS:
            continue
        files.append(GeneratedFileSpec(path=path, content=content, worker_kind=worker_kind))
        if len(files) >= MAX_GENERATED_FILES:
            break

    operation = str(payload.get("operation", "")).strip().lower() or None
    if operation not in {None, "replace", "patch"}:
        operation = None
    deleted_files = [
        path
        for item in payload.get("deleted_files", [])
        if isinstance(item, str) and (path := _safe_relative_path(item)) is not None
    ]

    return WorkerFileManifest(
        worker_kind=worker_kind,
        summary=str(payload.get("summary", "")).strip(),
        files=files,
        operation=operation,
        deleted_files=deleted_files,
        validation_commands=[
            str(command).strip()
            for command in payload.get("validation_commands", [])
            if isinstance(command, str) and command.strip()
        ],
        notes=[
            str(note).strip()
            for note in payload.get("notes", [])
            if isinstance(note, str) and note.strip()
        ],
    )


def validate_worker_manifest_scope(manifest: WorkerFileManifest) -> None:
    prefix = WORKER_PATH_PREFIXES[manifest.worker_kind]
    invalid_paths = [
        path
        for path in [*(file.path for file in manifest.files), *manifest.deleted_files]
        if not path.startswith(prefix)
    ]
    if invalid_paths:
        raise WorkerManifestScopeError(
            f"{manifest.worker_kind.value} worker generated files outside {prefix}: "
            + ", ".join(sorted(invalid_paths))
        )


def worker_manifest_source_syntax_failure(manifest: WorkerFileManifest) -> str | None:
    for file in manifest.files:
        if PurePosixPath(file.path).suffix.lower() != ".py":
            continue
        try:
            ast.parse(file.content, filename=file.path)
        except SyntaxError as exc:
            location = f"{file.path}:{exc.lineno or 1}:{exc.offset or 1}"
            return (
                f"Candidate contains invalid Python syntax at {location}: {exc.msg}. "
                "Correct the syntax before consuming an execution attempt."
            )
    return None


def validate_worker_manifest_contract(
    manifest: WorkerFileManifest,
    capability_id: str,
) -> None:
    for file in manifest.files:
        name = PurePosixPath(file.path).name.lower()
        if name.startswith("tsconfig") and name.endswith(".json"):
            try:
                config = json.loads(file.content)
            except json.JSONDecodeError as exc:
                raise WorkerManifestContractError(
                    f"Invalid {file.path}: {exc.msg}"
                ) from exc
            if not isinstance(config, dict):
                raise WorkerManifestContractError(f"{file.path} must contain a JSON object")
        if name != "package.json":
            continue
        try:
            package = json.loads(file.content)
        except json.JSONDecodeError as exc:
            raise WorkerManifestContractError(f"Invalid {file.path}: {exc.msg}") from exc
        if not isinstance(package, dict):
            raise WorkerManifestContractError(f"{file.path} must contain a JSON object")
    if manifest.operation == "patch":
        return
    paths = {file.path for file in manifest.files}
    errors: list[str] = []
    if manifest.worker_kind == WorkerKind.FRONTEND:
        if "frontend/package.json" not in paths:
            errors.append("frontend/package.json is required")
        if capability_id in {"react-fastapi", "react-node", "react-vite"}:
            for path in (
                "frontend/index.html",
                "frontend/tsconfig.json",
                "frontend/src/vite-env.d.ts",
            ):
                if path not in paths:
                    errors.append(f"{path} is required")
            if not _has_matching_path(
                paths, "frontend/vite.config", {".js", ".mjs", ".ts", ".mts"}
            ):
                errors.append("a frontend/vite.config module is required")
            if not _has_matching_path(
                paths,
                "frontend/src/main",
                {".js", ".jsx", ".ts", ".tsx"},
            ):
                errors.append("a frontend/src/main entry point is required")
        if not _has_runtime_source(paths, "frontend/"):
            errors.append("frontend runtime source is required")
        if not any(_is_test_path(path) for path in paths):
            errors.append("at least one focused frontend test is required")
    elif manifest.worker_kind == WorkerKind.BACKEND:
        if not paths.intersection(
            {
                "backend/package.json",
                "backend/pyproject.toml",
                "backend/requirements.txt",
            }
        ):
            errors.append("a backend dependency manifest is required")
        if not _has_runtime_source(paths, "backend/"):
            errors.append("backend runtime source is required")
        if not any(_is_test_path(path) for path in paths):
            errors.append("at least one focused backend test is required")
    elif manifest.worker_kind == WorkerKind.DATABASE and not any(
        path.endswith(".sql") for path in paths
    ):
        errors.append("at least one database migration is required")
    if errors:
        raise WorkerManifestContractError("Incomplete initial manifest: " + "; ".join(errors))


def collect_worker_file_manifests(job: JobState) -> list[WorkerFileManifest]:
    checkpointed = checkpointed_worker_file_manifests(job)
    if checkpointed:
        return checkpointed

    manifests: list[WorkerFileManifest] = []
    latest_results_by_task = {result.task_id: result for result in job.worker_results}
    for task in job.tasks:
        result = latest_results_by_task.get(task.task_id)
        if result is None or result.status != TaskStatus.SUCCEEDED or not result.output.strip():
            continue
        manifest = extract_worker_file_manifest(result.output, task.worker_kind)
        if manifest.files:
            manifests.append(manifest)
    return manifests


def collect_worker_file_specs(job: JobState) -> list[GeneratedFileSpec]:
    specs: list[GeneratedFileSpec] = []
    for manifest in collect_worker_file_manifests(job):
        specs.extend(manifest.files)
    return specs


def has_worker_file_specs(job: JobState) -> bool:
    return bool(collect_worker_file_specs(job))


def fallback_worker_manifest_json(task: JobTask, project_prompt: str, project_id: str) -> str:
    files = deterministic_stack_files(
        task.capability_id,
        task.worker_kind,
        project_prompt,
        project_id,
    ) or _fallback_files_for_worker(task.worker_kind, project_prompt, project_id)
    payload = {
        "summary": f"{task.worker_kind.value} worker generated local runnable source files.",
        "operation": "replace",
        "files": [{"path": path, "content": content} for path, content in files.items()],
        "deleted_files": [],
        "validation_commands": deterministic_validation_commands(
            task.capability_id,
            task.worker_kind,
        )
        or _fallback_validation_commands(task.worker_kind),
        "notes": [
            "Certified deterministic checkpoint; semantic implementation may require targeted repair."
        ],
    }
    return json.dumps(payload, indent=2)


def normalize_worker_manifest(
    manifest: WorkerFileManifest,
    capability_id: str,
) -> WorkerFileManifest:
    """Apply deterministic capability-pack versions to generated Node manifests."""

    if manifest.operation != "patch":
        _inject_missing_runtime_contracts(manifest, capability_id)
        _inject_missing_environment_examples(manifest)
        _normalize_python_source_layout(manifest)
    _normalize_python_build_contract(manifest)
    _normalize_python_password_hash_contracts(manifest)
    _normalize_python_dependency_contracts(manifest)
    _normalize_frontend_test_contracts(manifest, capability_id)
    _normalize_frontend_typescript_contracts(manifest, capability_id)
    trusted_package = trusted_node_package(capability_id, manifest.worker_kind)
    if trusted_package is None:
        return manifest
    package_path = f"{manifest.worker_kind.value}/package.json"
    for file in manifest.files:
        if file.path != package_path:
            continue
        try:
            generated_package = json.loads(file.content)
        except json.JSONDecodeError:
            continue
        if not isinstance(generated_package, dict):
            continue
        trusted_scripts = trusted_package.get("scripts", {})
        if isinstance(trusted_scripts, dict):
            generated_scripts = generated_package.setdefault("scripts", {})
            if not isinstance(generated_scripts, dict):
                generated_scripts = {}
                generated_package["scripts"] = generated_scripts
            for name, command in trusted_scripts.items():
                generated_scripts[str(name)] = str(command)
        for section in ("dependencies", "devDependencies"):
            trusted_dependencies = trusted_package.get(section, {})
            if not isinstance(trusted_dependencies, dict):
                continue
            generated_dependencies = generated_package.setdefault(section, {})
            if not isinstance(generated_dependencies, dict):
                generated_dependencies = {}
                generated_package[section] = generated_dependencies
            for name, version in trusted_dependencies.items():
                generated_dependencies[str(name)] = str(version)
                for other_section in ("dependencies", "devDependencies", "optionalDependencies"):
                    other_dependencies = generated_package.get(other_section)
                    if other_section != section and isinstance(other_dependencies, dict):
                        other_dependencies.pop(str(name), None)
        optional_dependencies = trusted_optional_node_dependencies(
            capability_id,
            manifest.worker_kind,
        )
        source_text = "\n".join(item.content for item in manifest.files)
        for section, trusted_dependencies in optional_dependencies.items():
            generated_dependencies = generated_package.setdefault(section, {})
            if not isinstance(generated_dependencies, dict):
                continue
            selected_optional = {
                name
                for name in trusted_dependencies
                if name in generated_dependencies or name in source_text
            }
            if not selected_optional:
                continue
            if any(name.startswith("@testing-library/") for name in selected_optional):
                selected_optional.add("@testing-library/dom")
            if "@testing-library/react" in selected_optional:
                selected_optional.add("jsdom")
            for name in selected_optional:
                generated_dependencies[name] = trusted_dependencies[name]
                for other_section in ("dependencies", "optionalDependencies"):
                    other_dependencies = generated_package.get(other_section)
                    if isinstance(other_dependencies, dict):
                        other_dependencies.pop(name, None)
        if isinstance(trusted_package.get("engines"), dict):
            generated_package["engines"] = dict(trusted_package["engines"])
        file.content = json.dumps(generated_package, indent=2) + "\n"
    return manifest


def _normalize_python_source_layout(manifest: WorkerFileManifest) -> None:
    if manifest.worker_kind != WorkerKind.BACKEND:
        return
    paths = {file.path for file in manifest.files}
    if "backend/requirements.txt" not in paths or "backend/pyproject.toml" in paths:
        return
    for file in manifest.files:
        if file.path.startswith("backend/src/"):
            normalized_path = "backend/" + file.path.removeprefix("backend/src/")
            if normalized_path in paths:
                raise WorkerManifestContractError(
                    f"Requirements-based backend defines conflicting runtime paths: "
                    f"{file.path} and {normalized_path}."
                )
            file.path = normalized_path
        elif file.path == "backend/pytest.ini":
            file.content = (
                re.sub(
                    r"(?im)^\s*pythonpath\s*=\s*src\s*$",
                    "pythonpath = .",
                    file.content,
                ).rstrip()
                + "\n"
            )
    manifest.validation_commands = [
        command.replace("PYTHONPATH=src ", "") for command in manifest.validation_commands
    ]


def _normalize_python_build_contract(manifest: WorkerFileManifest) -> None:
    if manifest.worker_kind != WorkerKind.BACKEND:
        return
    pyproject = next(
        (file for file in manifest.files if file.path == "backend/pyproject.toml"),
        None,
    )
    if pyproject is None:
        return
    build_section = (
        '[build-system]\nrequires = ["hatchling==1.27.0"]\n'
        'build-backend = "hatchling.build"\n\n'
    )
    section_match = re.search(
        r"(?ms)^\[build-system\]\s*\n.*?(?=^\[[^\n]+\]\s*$|\Z)",
        pyproject.content,
    )
    allowed_backend = re.search(
        r'(?m)^\s*build-backend\s*=\s*"(?:hatchling\.build|setuptools\.build_meta|flit_core\.buildapi)"\s*$',
        section_match.group(0) if section_match else "",
    )
    if section_match is None:
        pyproject.content = build_section + pyproject.content.lstrip()
    elif allowed_backend is None:
        pyproject.content = (
            pyproject.content[: section_match.start()]
            + build_section
            + pyproject.content[section_match.end() :].lstrip()
        )
    if "[tool.hatch.build.targets.wheel]" in pyproject.content:
        return
    package_roots = sorted(
        {
            "/".join(PurePosixPath(file.path).parts[1:3])
            for file in manifest.files
            if file.path.startswith("backend/src/")
            and PurePosixPath(file.path).name == "__init__.py"
            and len(PurePosixPath(file.path).parts) >= 4
        }
    )
    if not package_roots:
        return
    packages = ", ".join(json.dumps(root) for root in package_roots)
    pyproject.content = (
        pyproject.content.rstrip()
        + "\n\n[tool.hatch.build.targets.wheel]\n"
        + f"packages = [{packages}]\n"
    )


def _normalize_python_dependency_contracts(manifest: WorkerFileManifest) -> None:
    if manifest.worker_kind != WorkerKind.BACKEND:
        return
    source_text = "\n".join(
        file.content
        for file in manifest.files
        if PurePosixPath(file.path).suffix == ".py"
    )
    pwdlib_extras: set[str] = set()
    if "PasswordHash.recommended" in source_text or "Argon2Hasher" in source_text:
        pwdlib_extras.add("argon2")
    if "BcryptHasher" in source_text:
        pwdlib_extras.add("bcrypt")
    requires_greenlet = any(
        marker in source_text
        for marker in (
            "sqlalchemy.ext.asyncio",
            "AsyncSession",
            "async_sessionmaker",
            "create_async_engine",
        )
    )
    requires_itsdangerous = "SessionMiddleware" in source_text
    for file in manifest.files:
        if file.path not in {"backend/pyproject.toml", "backend/requirements.txt"}:
            continue
        if pwdlib_extras:
            file.content = _merge_python_requirement_extras(
                file.content,
                "pwdlib",
                pwdlib_extras,
            )
        if requires_greenlet:
            file.content = _ensure_python_requirement(
                file.content,
                file.path,
                "greenlet==3.1.1",
            )
        if requires_itsdangerous:
            file.content = _ensure_python_requirement(
                file.content,
                file.path,
                "itsdangerous==2.2.0",
            )


def _normalize_python_password_hash_contracts(manifest: WorkerFileManifest) -> None:
    if manifest.worker_kind != WorkerKind.BACKEND:
        return
    for file in manifest.files:
        path = PurePosixPath(file.path)
        if path.suffix != ".py" or "tests" in path.parts:
            continue
        if "PasswordHash.recommended()" not in file.content:
            continue
        file.content = file.content.replace(
            "PasswordHash.recommended()",
            "PasswordHash((Argon2Hasher(), BcryptHasher()))",
        )
        imports = []
        if "from pwdlib.hashers.argon2 import Argon2Hasher" not in file.content:
            imports.append("from pwdlib.hashers.argon2 import Argon2Hasher")
        if "from pwdlib.hashers.bcrypt import BcryptHasher" not in file.content:
            imports.append("from pwdlib.hashers.bcrypt import BcryptHasher")
        if not imports:
            continue
        password_import = re.search(r"(?m)^from pwdlib import PasswordHash\s*$", file.content)
        insertion = "\n".join(imports) + "\n"
        if password_import is None:
            file.content = insertion + file.content
            continue
        offset = password_import.end()
        file.content = file.content[:offset] + "\n" + insertion + file.content[offset:]


def _merge_python_requirement_extras(
    content: str,
    package: str,
    required_extras: set[str],
) -> str:
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_.-]){re.escape(package)}"
        r"(?:\[(?P<extras>[^\]\r\n]+)\])?==(?P<version>[^\"'\s,]+)"
    )

    def replacement(match: re.Match[str]) -> str:
        extras = {
            item.strip()
            for item in (match.group("extras") or "").split(",")
            if item.strip()
        }
        extras.update(required_extras)
        return f"{package}[{','.join(sorted(extras))}]=={match.group('version')}"

    return pattern.sub(replacement, content)


def _ensure_python_requirement(content: str, path: str, requirement: str) -> str:
    package = requirement.split("==", maxsplit=1)[0]
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_.-]){re.escape(package)}"
        r"(?:\[[^\]\r\n]+\])?==[^\"'\s,]+"
    )
    if pattern.search(content):
        return pattern.sub(requirement, content)
    if path.endswith("requirements.txt"):
        return content.rstrip() + f"\n{requirement}\n"
    dependencies = re.search(r"(?m)^(?P<indent>\s*)dependencies\s*=\s*\[", content)
    if dependencies is None:
        return content
    indent = dependencies.group("indent") + "  "
    insertion = f'\n{indent}"{requirement}",'
    return content[: dependencies.end()] + insertion + content[dependencies.end() :]


def _inject_missing_environment_examples(manifest: WorkerFileManifest) -> None:
    prefix = f"{manifest.worker_kind.value}/"
    env_path = f"{prefix}.env.example"
    env_file = next((file for file in manifest.files if file.path == env_path), None)
    source_text = "\n".join(
        file.content
        for file in manifest.files
        if file.path.startswith(prefix) and PurePosixPath(file.path).name != ".env.example"
    )
    patterns = (
        re.compile(r"import\.meta\.env\.([A-Z][A-Z0-9_]*)"),
        re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)"),
        re.compile(r"os\.(?:getenv|environ\.get)\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"),
    )
    variables = sorted({match for pattern in patterns for match in pattern.findall(source_text)})
    if not variables:
        return
    defaults = {
        "VITE_API_BASE_URL": "http://localhost:8000",
    }
    existing_variables = (
        {
            match.group(1)
            for match in re.finditer(
                r"(?m)^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=",
                env_file.content,
            )
        }
        if env_file is not None
        else set()
    )
    missing_variables = [name for name in variables if name not in existing_variables]
    if not missing_variables:
        return
    additions = "".join(f"{name}={defaults.get(name, '')}\n" for name in missing_variables)
    if env_file is not None:
        env_file.content = env_file.content.rstrip() + "\n" + additions
    else:
        manifest.files.append(
            GeneratedFileSpec(
                path=env_path,
                content=additions,
                worker_kind=manifest.worker_kind,
            )
        )
    manifest.files.sort(key=lambda item: item.path)


def _normalize_frontend_typescript_contracts(
    manifest: WorkerFileManifest,
    capability_id: str,
) -> None:
    if manifest.worker_kind != WorkerKind.FRONTEND or capability_id not in {
        "react-fastapi",
        "react-node",
        "react-vite",
    }:
        return
    for file in manifest.files:
        name = PurePosixPath(file.path).name.lower()
        if not (name.startswith("tsconfig") and name.endswith(".json")):
            continue
        try:
            config = json.loads(file.content)
        except json.JSONDecodeError:
            continue
        if not isinstance(config, dict):
            continue
        compiler_options = config.setdefault("compilerOptions", {})
        if not isinstance(compiler_options, dict):
            compiler_options = {}
            config["compilerOptions"] = compiler_options
        compiler_options["target"] = "ES2022"
        compiler_options["skipLibCheck"] = True
        compiler_options.setdefault("module", "ESNext")
        compiler_options.setdefault("moduleResolution", "Bundler")
        if name == "tsconfig.node.json":
            compiler_options["lib"] = ["ES2022"]
            types = compiler_options.setdefault("types", [])
            if isinstance(types, list) and "node" not in types:
                types.append("node")
        else:
            compiler_options.setdefault("lib", ["ES2022", "DOM", "DOM.Iterable"])
        file.content = json.dumps(config, indent=2) + "\n"


def _normalize_frontend_test_contracts(
    manifest: WorkerFileManifest,
    capability_id: str,
) -> None:
    if manifest.worker_kind != WorkerKind.FRONTEND or capability_id not in {
        "react-fastapi",
        "react-node",
        "react-vite",
    }:
        return
    for file in manifest.files:
        if PurePosixPath(file.path).suffix.lower() not in {".js", ".jsx", ".ts", ".tsx"}:
            continue
        file.content = re.sub(
            r"(import\s+['\"])@testing-library/jest-dom(['\"]\s*;?)",
            r"\1@testing-library/jest-dom/vitest\2",
            file.content,
        )
    test_files = [file for file in manifest.files if _is_test_path(file.path)]
    if not test_files:
        return

    vitest_globals = (
        "afterAll",
        "afterEach",
        "beforeAll",
        "beforeEach",
        "describe",
        "expect",
        "it",
        "test",
        "vi",
    )
    jest_dom_matchers = (
        "toBeChecked",
        "toBeDisabled",
        "toBeEmptyDOMElement",
        "toBeInTheDocument",
        "toBeInvalid",
        "toBeRequired",
        "toBeValid",
        "toBeVisible",
        "toContainElement",
        "toHaveAccessibleDescription",
        "toHaveAccessibleName",
        "toHaveAttribute",
        "toHaveClass",
        "toHaveFocus",
        "toHaveFormValues",
        "toHaveStyle",
        "toHaveTextContent",
        "toHaveValue",
    )
    for file in test_files:
        if "@playwright/test" in file.content:
            continue
        file.content = re.sub(
            r"\buserEvent\.upload\(",
            "userEvent.setup({ applyAccept: false }).upload(",
            file.content,
        )
        file.content = re.sub(
            r"\b(?P<query>get|find|query)ByRole\(\s*(['\"])video\2\s*,\s*"
            r"\{\s*name\s*:\s*(?P<name>[^,}]+)\s*\}\s*\)",
            lambda match: (
                f"{match.group('query')}ByLabelText({match.group('name').strip()})"
            ),
            file.content,
        )
        imported = _vitest_imported_names(file.content)
        missing = [
            name
            for name in vitest_globals
            if name not in imported and re.search(rf"\b{re.escape(name)}\s*\(", file.content)
        ]
        if missing:
            file.content = f"import {{ {', '.join(missing)} }} from 'vitest';\n" + file.content
        uses_jest_dom = any(
            re.search(rf"\.{re.escape(matcher)}\s*\(", file.content)
            for matcher in jest_dom_matchers
        )
        if uses_jest_dom and "@testing-library/jest-dom" not in file.content:
            file.content = "import '@testing-library/jest-dom/vitest';\n" + file.content

    runtime_text = "\n".join(
        file.content for file in manifest.files if not _is_test_path(file.path)
    )
    required_observers = [
        name
        for name in ("IntersectionObserver", "ResizeObserver")
        if re.search(rf"\b{re.escape(name)}\b", runtime_text)
    ]
    if not required_observers:
        return

    setup_path = "frontend/src/test/setup.ts"
    setup_file = next((file for file in manifest.files if file.path == setup_path), None)
    additions = "\n\n".join(
        _observer_test_polyfill(name)
        for name in required_observers
        if setup_file is None or name not in setup_file.content
    )
    if setup_file is None:
        setup_file = GeneratedFileSpec(
            path=setup_path,
            content=additions.rstrip() + "\n",
            worker_kind=WorkerKind.FRONTEND,
        )
        manifest.files.append(setup_file)
    elif additions:
        setup_file.content = setup_file.content.rstrip() + "\n\n" + additions.rstrip() + "\n"

    for file in test_files:
        if "@playwright/test" in file.content:
            continue
        import_path = posixpath.relpath(
            setup_path.removesuffix(".ts"),
            posixpath.dirname(file.path),
        )
        if not import_path.startswith("."):
            import_path = "./" + import_path
        setup_import = f"import '{import_path}';"
        if setup_import not in file.content:
            file.content = setup_import + "\n" + file.content
    manifest.files.sort(key=lambda item: item.path)


def _vitest_imported_names(content: str) -> set[str]:
    imported: set[str] = set()
    for match in re.finditer(
        r"import\s*\{(?P<names>[^}]+)\}\s*from\s*['\"]vitest['\"]",
        content,
        re.DOTALL,
    ):
        for item in match.group("names").split(","):
            name = item.strip().split(" as ", maxsplit=1)[-1].strip()
            if name:
                imported.add(name)
    return imported


def _observer_test_polyfill(name: str) -> str:
    entry_type = f"{name}Entry"
    return dedent(
        f"""
        if (!globalThis.{name}) {{
          class {name}Stub {{
            readonly root = null;
            readonly rootMargin = '0px';
            readonly thresholds = [0];
            disconnect() {{}}
            observe() {{}}
            unobserve() {{}}
            takeRecords(): {entry_type}[] {{ return []; }}
          }}
          Object.defineProperty(globalThis, '{name}', {{
            configurable: true,
            value: {name}Stub,
          }});
        }}
        """
    ).strip()


def _inject_missing_runtime_contracts(
    manifest: WorkerFileManifest,
    capability_id: str,
) -> None:
    baseline = deterministic_stack_files(
        capability_id,
        manifest.worker_kind,
        "Certified runtime contract.",
        "certified-runtime-contract",
    )
    if not baseline:
        return
    existing = {file.path for file in manifest.files}
    for path, content in baseline.items():
        if path in existing or not _is_runtime_contract_path(path):
            continue
        if path.endswith("vite.config.ts"):
            if _has_matching_path(existing, "frontend/vite.config", {".js", ".mjs", ".ts", ".mts"}):
                continue
            if any("@testing-library/" in file.content for file in manifest.files):
                setup_files = sorted(
                    item
                    for item in existing
                    if PurePosixPath(item).stem in {"setup", "setupTests", "test-setup"}
                    and PurePosixPath(item).suffix in {".ts", ".js"}
                )
                test_config: dict[str, Any] = {"environment": "jsdom", "globals": True}
                if setup_files:
                    test_config["setupFiles"] = [
                        "./" + item.removeprefix("frontend/") for item in setup_files
                    ]
                content = content.replace('from "vite"', 'from "vitest/config"').replace(
                    "plugins: [react()],",
                    f"plugins: [react()],\n  test: {json.dumps(test_config)},",
                )
        if path.endswith("tsconfig.json") and any(
            item.endswith((".js", ".jsx")) and "/src/" in item for item in existing
        ):
            config = json.loads(content)
            config["compilerOptions"]["allowJs"] = True
            content = json.dumps(config, indent=2) + "\n"
        manifest.files.append(
            GeneratedFileSpec(
                path=path,
                content=content,
                worker_kind=manifest.worker_kind,
            )
        )
        existing.add(path)
    manifest.files.sort(key=lambda item: item.path)


def _is_runtime_contract_path(path: str) -> bool:
    name = PurePosixPath(path).name
    return name in {
        "next.config.mjs",
        "package.json",
        "tsconfig.json",
        "vite-env.d.ts",
        "vite.config.ts",
    }


def _has_matching_path(paths: set[str], stem: str, suffixes: set[str]) -> bool:
    return any(
        str(PurePosixPath(path).with_suffix("")) == stem and PurePosixPath(path).suffix in suffixes
        for path in paths
    )


def _has_runtime_source(paths: set[str], prefix: str) -> bool:
    return any(
        path.startswith(prefix)
        and PurePosixPath(path).suffix in {".js", ".jsx", ".mjs", ".py", ".ts", ".tsx"}
        and not _is_test_path(path)
        and not {"test", "tests", "__tests__"}.intersection(PurePosixPath(path).parts)
        and ".config." not in PurePosixPath(path).name
        and not path.endswith(".d.ts")
        and PurePosixPath(path).stem not in {"setup", "setupTests", "test-setup"}
        for path in paths
    )


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    name = PurePosixPath(lowered).name
    return (
        name.startswith("test_")
        and name.endswith(".py")
        or any(marker in name for marker in (".test.", ".spec.", "_test."))
    )


def _dependency_policy(task: JobTask) -> str:
    package = trusted_node_package(task.capability_id, task.worker_kind) or {}
    policy = {
        section: package[section]
        for section in ("dependencies", "devDependencies", "engines")
        if section in package
    }
    optional = trusted_optional_node_dependencies(task.capability_id, task.worker_kind)
    if optional:
        policy["optional_if_used"] = optional
    return json.dumps(policy, separators=(",", ":"))


def worker_file_manifest_json(manifest: WorkerFileManifest) -> str:
    return json.dumps(
        {
            "summary": manifest.summary,
            "operation": manifest.operation or "replace",
            "files": [{"path": file.path, "content": file.content} for file in manifest.files],
            "deleted_files": manifest.deleted_files,
            "validation_commands": manifest.validation_commands,
            "notes": manifest.notes,
        },
        separators=(",", ":"),
    )


def checkpointed_worker_file_manifests(job: JobState) -> list[WorkerFileManifest]:
    state = job.manifest_state
    if not state:
        return []
    files = state.get("files", {})
    task_manifests = state.get("task_manifests", {})
    if not isinstance(files, dict) or not isinstance(task_manifests, dict):
        return []
    manifests: list[WorkerFileManifest] = []
    for task in job.tasks:
        task_record = task_manifests.get(task.task_id)
        if not isinstance(task_record, dict):
            continue
        task_files = []
        for path, record in files.items():
            if (
                isinstance(record, dict)
                and not record.get("deleted", False)
                and record.get("task_id") == task.task_id
                and isinstance(record.get("content"), str)
            ):
                task_files.append(
                    GeneratedFileSpec(
                        path=str(path),
                        content=str(record["content"]),
                        worker_kind=task.worker_kind,
                    )
                )
        if not task_files:
            continue
        manifests.append(
            WorkerFileManifest(
                worker_kind=task.worker_kind,
                summary=str(task_record.get("summary", "")),
                files=sorted(task_files, key=lambda item: item.path),
                operation=str(task_record.get("operation", "patch")),
                validation_commands=[
                    str(command) for command in task_record.get("validation_commands", [])
                ],
                notes=[str(note) for note in task_record.get("notes", [])],
            )
        )
    return manifests


def merge_file_specs(specs: list[GeneratedFileSpec]) -> dict[str, str]:
    files: dict[str, str] = {}
    owners: dict[str, set[WorkerKind]] = {}
    conflicts: dict[str, set[WorkerKind]] = {}
    for spec in specs:
        if spec.path in files and files[spec.path] != spec.content:
            conflicts.setdefault(spec.path, set()).update(
                {*owners.get(spec.path, set()), spec.worker_kind}
            )
            continue
        files[spec.path] = spec.content
        owners.setdefault(spec.path, set()).add(spec.worker_kind)
    if conflicts:
        raise ManifestConflictError(conflicts)
    return files


def _extract_json_payload(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", stripped):
        try:
            payload, _ = decoder.raw_decode(stripped[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "files" in payload:
            return payload
    return None


def _safe_relative_path(path: str) -> str | None:
    cleaned = path.replace("\\", "/").strip().lstrip("/")
    if not cleaned:
        return None
    candidate = PurePosixPath(cleaned)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    if any(part in BLOCKED_PATH_PARTS for part in candidate.parts):
        return None
    return candidate.as_posix()


def _fallback_files_for_worker(
    worker_kind: WorkerKind,
    project_prompt: str,
    project_id: str,
) -> dict[str, str]:
    if worker_kind == WorkerKind.DATABASE:
        return {
            "database/migrations/001_initial.sql": _sqlite_migration(),
        }
    if worker_kind == WorkerKind.FRONTEND:
        return {
            "frontend/package.json": _frontend_package(project_id),
            "frontend/vite.config.js": _frontend_vite_config(),
            "frontend/index.html": _frontend_index(project_id),
            "frontend/src/main.jsx": _frontend_main(),
            "frontend/src/App.jsx": _frontend_app(project_prompt, project_id),
            "frontend/src/styles.css": _frontend_styles(),
        }
    return {
        "backend/pyproject.toml": _backend_pyproject(project_id),
        "backend/src/app/__init__.py": "",
        "backend/src/app/main.py": _backend_main(project_prompt, project_id),
        "backend/tests/test_app.py": _backend_test(),
    }


def _fallback_validation_commands(worker_kind: WorkerKind) -> list[str]:
    if worker_kind == WorkerKind.DATABASE:
        return ["sqlite3 backend/local_app.sqlite3 < database/migrations/001_initial.sql"]
    if worker_kind == WorkerKind.FRONTEND:
        return ["cd frontend && npm ci && npm run build"]
    return [
        (
            "cd backend && uv sync --locked --group dev --no-editable "
            "&& uv run --locked --no-sync python -m pytest"
        )
    ]


def _sqlite_migration() -> str:
    return (
        dedent(
            """
        create table if not exists records (
          record_id text primary key,
          kind text not null,
          title text not null,
          status text not null default 'active',
          payload text not null default '{}',
          created_at text not null
        );

        create table if not exists analytics_events (
          event_id text primary key,
          record_id text references records(record_id),
          event_type text not null,
          severity text not null default 'info',
          payload text not null default '{}',
          created_at text not null
        );

        create index if not exists idx_records_kind_status on records(kind, status);
        create index if not exists idx_analytics_type_severity
          on analytics_events(event_type, severity);
        """
        ).strip()
        + "\n"
    )


def _database_readme(project_prompt: str) -> str:
    return (
        dedent(
            f"""
        # Local Database

        This MVP uses SQLite so the generated software can run on localhost without external
        credentials.

        Original request:

        > {project_prompt}

        The schema stores generic domain records and analytics events. Domain-specific agents can
        extend these tables when the prompt requires richer models.
        """
        ).strip()
        + "\n"
    )


def _backend_pyproject(project_id: str) -> str:
    package_name = _slugify(project_id)
    return (
        dedent(
            f"""
        [project]
        name = "{package_name}-backend"
        version = "0.1.0"
        requires-python = ">=3.11"
        dependencies = [
          "fastapi==0.115.12",
          "uvicorn[standard]==0.34.2"
        ]

        [dependency-groups]
        dev = ["httpx==0.28.1", "pytest==8.3.5"]

        [build-system]
        requires = ["hatchling"]
        build-backend = "hatchling.build"

        [tool.hatch.build.targets.wheel]
        packages = ["src/app"]

        [tool.pytest.ini_options]
        pythonpath = ["src"]
        testpaths = ["tests"]
        """
        ).strip()
        + "\n"
    )


def _backend_main(project_prompt: str, project_id: str) -> str:
    prompt_literal = repr(project_prompt)
    project_literal = repr(_titleize(project_id))
    return (
        dedent(
            f"""
        from __future__ import annotations

        from uuid import uuid4

        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel, Field


        PROJECT_NAME = {project_literal}
        PROJECT_PROMPT = {prompt_literal}
        records: list[dict] = []


        class RecordIn(BaseModel):
            kind: str = Field(default="item", min_length=1, max_length=80)
            title: str = Field(min_length=1, max_length=200)
            status: str = Field(default="active", min_length=1, max_length=80)
            payload: dict = Field(default_factory=dict)


        app = FastAPI(title=PROJECT_NAME, version="0.1.0")
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )


        @app.get("/api/health")
        def health() -> dict:
            return {{"status": "ok"}}


        @app.get("/api/blueprint")
        def blueprint() -> dict:
            return {{
                "project": PROJECT_NAME,
                "prompt": PROJECT_PROMPT,
                "storage": "memory",
                "capabilities": ["records", "localhost API"],
            }}


        @app.get("/api/records")
        def list_records() -> list[dict]:
            return list(reversed(records[-100:]))


        @app.post("/api/records", status_code=201)
        def create_record(record: RecordIn) -> dict:
            row = {{
                "record_id": str(uuid4()),
                "kind": record.kind,
                "title": record.title,
                "status": record.status,
                "payload": record.payload,
            }}
            records.append(row)
            return row
        """
        ).strip()
        + "\n"
    )


def _backend_test() -> str:
    return (
        dedent(
            """
        from fastapi.testclient import TestClient

        from app.main import app


        client = TestClient(app)


        def test_health_and_record_flow():
            health = client.get("/api/health")
            assert health.status_code == 200
            assert health.json()["status"] == "ok"

            created = client.post(
                "/api/records",
                json={"kind": "task", "title": "First local record", "payload": {"priority": "high"}},
            )
            assert created.status_code == 201

            records = client.get("/api/records")
            assert records.status_code == 200
            assert any(item["record_id"] == created.json()["record_id"] for item in records.json())
        """
        ).strip()
        + "\n"
    )


def _frontend_package(project_id: str) -> str:
    return (
        json.dumps(
            {
                "name": f"{_slugify(project_id)}-frontend",
                "version": "0.1.0",
                "private": True,
                "type": "module",
                "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
                "dependencies": {
                    "@vitejs/plugin-react": "latest",
                    "vite": "latest",
                    "react": "latest",
                    "react-dom": "latest",
                },
                "devDependencies": {},
            },
            indent=2,
        )
        + "\n"
    )


def _frontend_vite_config() -> str:
    return (
        dedent(
            """
        import { defineConfig } from 'vite';
        import react from '@vitejs/plugin-react';

        export default defineConfig({
          plugins: [react()],
          server: {
            port: 5173,
            proxy: {
              '/api': 'http://localhost:8000'
            }
          }
        });
        """
        ).strip()
        + "\n"
    )


def _frontend_index(project_id: str) -> str:
    title = _titleize(project_id)
    return (
        dedent(
            f"""
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="UTF-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0" />
            <title>{title}</title>
          </head>
          <body>
            <div id="root"></div>
            <script type="module" src="/src/main.jsx"></script>
          </body>
        </html>
        """
        ).strip()
        + "\n"
    )


def _frontend_main() -> str:
    return (
        dedent(
            """
        import React, { useEffect, useState } from 'react';
        import { createRoot } from 'react-dom/client';
        import './styles.css';
        import App from './App.jsx';

        createRoot(document.getElementById('root')).render(
          <React.StrictMode>
            <App />
          </React.StrictMode>
        );
        """
        ).strip()
        + "\n"
    )


def _frontend_app(project_prompt: str, project_id: str) -> str:
    prompt_literal = json.dumps(project_prompt)
    title_literal = json.dumps(_titleize(project_id))
    return (
        dedent(
            f"""
        import {{ useEffect, useState }} from 'react';

        const projectPrompt = {prompt_literal};
        const projectTitle = {title_literal};

        export default function App() {{
          const [blueprint, setBlueprint] = useState(null);
          const [records, setRecords] = useState([]);
          const [analytics, setAnalytics] = useState({{ records: 0, events: 0, severities: {{}} }});
          const [title, setTitle] = useState('');
          const [status, setStatus] = useState('Loading local API...');

          async function refresh() {{
            const [blueprintResponse, recordsResponse, analyticsResponse] = await Promise.all([
              fetch('/api/blueprint'),
              fetch('/api/records'),
              fetch('/api/analytics/summary')
            ]);
            setBlueprint(await blueprintResponse.json());
            setRecords(await recordsResponse.json());
            setAnalytics(await analyticsResponse.json());
            setStatus('Local API connected');
          }}

          async function createRecord(event) {{
            event.preventDefault();
            if (!title.trim()) return;
            await fetch('/api/records', {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify({{
                kind: 'workspace-item',
                title,
                payload: {{ source: 'frontend' }}
              }})
            }});
            setTitle('');
            await refresh();
          }}

          useEffect(() => {{
            refresh().catch(() => setStatus('Start the FastAPI backend on port 8000'));
          }}, []);

          return (
            <main className="shell">
              <section className="hero">
                <p className="eyebrow">Local MVP generated by Agentic Forge</p>
                <h1>{{projectTitle}}</h1>
                <p>{{blueprint?.prompt || projectPrompt}}</p>
                <span className="status">{{status}}</span>
              </section>

              <section className="metrics">
                <article><strong>{{records.length}}</strong><span>Visible records</span></article>
                <article><strong>{{analytics.events}}</strong><span>Analytics events</span></article>
                <article><strong>{{Object.keys(analytics.severities || {{}}).length}}</strong><span>Severity groups</span></article>
              </section>

              <section className="workspace">
                <form onSubmit={{createRecord}}>
                  <label htmlFor="record-title">Create local record</label>
                  <div>
                    <input
                      id="record-title"
                      value={{title}}
                      onChange={{(event) => setTitle(event.target.value)}}
                      placeholder="Add an item for this generated app"
                    />
                    <button type="submit">Save</button>
                  </div>
                </form>

                <div className="records">
                  {{records.length === 0 ? <p>No records yet. Add one to verify local persistence.</p> : null}}
                  {{records.map((record) => (
                    <article key={{record.record_id}}>
                      <strong>{{record.title}}</strong>
                      <span>{{record.kind}} · {{record.status}}</span>
                    </article>
                  ))}}
                </div>
              </section>
            </main>
          );
        }}
        """
        ).strip()
        + "\n"
    )


def _frontend_styles() -> str:
    return (
        dedent(
            """
        :root {
          color-scheme: dark;
          font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
          background: #07111f;
          color: #eff7ff;
        }

        body {
          margin: 0;
          min-height: 100vh;
          background:
            radial-gradient(circle at top left, rgba(95, 200, 255, 0.24), transparent 28rem),
            #07111f;
        }

        button, input {
          font: inherit;
        }

        .shell {
          width: min(1120px, calc(100% - 32px));
          margin: 0 auto;
          padding: 48px 0;
        }

        .hero, .workspace, .metrics article {
          border: 1px solid rgba(144, 202, 255, 0.18);
          border-radius: 24px;
          background: rgba(10, 23, 39, 0.78);
          box-shadow: 0 24px 80px rgba(0, 0, 0, 0.24);
        }

        .hero {
          padding: clamp(28px, 5vw, 54px);
        }

        .eyebrow {
          color: #7dd3fc;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          font-size: 0.78rem;
          font-weight: 800;
        }

        h1 {
          max-width: 840px;
          margin: 0 0 16px;
          font-size: clamp(2.4rem, 8vw, 5.6rem);
          line-height: 0.92;
        }

        .hero p:not(.eyebrow) {
          max-width: 760px;
          color: #b8cce0;
          line-height: 1.7;
        }

        .status {
          display: inline-flex;
          margin-top: 18px;
          padding: 8px 12px;
          border-radius: 999px;
          background: rgba(125, 211, 252, 0.12);
          color: #bae6fd;
        }

        .metrics {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 14px;
          margin: 18px 0;
        }

        .metrics article {
          padding: 22px;
        }

        .metrics strong {
          display: block;
          font-size: 2.25rem;
        }

        .metrics span, .records span {
          color: #91a7bd;
        }

        .workspace {
          padding: 24px;
        }

        form label {
          display: block;
          margin-bottom: 10px;
          color: #d8ecff;
          font-weight: 800;
        }

        form div {
          display: flex;
          gap: 10px;
        }

        input {
          flex: 1;
          border: 1px solid rgba(144, 202, 255, 0.24);
          border-radius: 14px;
          padding: 13px 14px;
          background: #0c1828;
          color: #eff7ff;
        }

        button {
          border: 0;
          border-radius: 14px;
          padding: 0 18px;
          background: #38bdf8;
          color: #03111d;
          font-weight: 900;
          cursor: pointer;
        }

        .records {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          gap: 12px;
          margin-top: 18px;
        }

        .records article {
          border: 1px solid rgba(144, 202, 255, 0.14);
          border-radius: 18px;
          padding: 16px;
          background: rgba(255, 255, 255, 0.04);
        }

        .records strong {
          display: block;
          margin-bottom: 6px;
        }
        """
        ).strip()
        + "\n"
    )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:48] or "generated-project"


def _titleize(value: str) -> str:
    words = re.sub(r"[^a-zA-Z0-9]+", " ", value).strip().split()
    return " ".join(word.capitalize() for word in words[:8]) or "Generated App"
