import json

import pytest

from software_developer_agent.artifacts.file_manifest import (
    GeneratedFileSpec,
    ManifestConflictError,
    WorkerFileManifest,
    WorkerManifestContractError,
    WorkerManifestScopeError,
    collect_worker_file_manifests,
    extract_worker_file_manifest,
    fallback_worker_manifest_json,
    merge_file_specs,
    normalize_worker_manifest,
    validate_worker_manifest_contract,
    validate_worker_manifest_scope,
    worker_manifest_prompt,
)
from software_developer_agent.models.job_state import (
    JobRequest,
    JobState,
    JobTask,
    TaskStatus,
    WorkerKind,
    WorkerResult,
)


def test_extract_worker_file_manifest_from_json() -> None:
    output = json.dumps(
        {
            "summary": "Generated backend API.",
            "files": [
                {"path": "backend/src/app/main.py", "content": "from fastapi import FastAPI\n"},
                {"path": "../secrets.txt", "content": "blocked"},
            ],
            "validation_commands": ["cd backend && pytest"],
        }
    )

    manifest = extract_worker_file_manifest(output, WorkerKind.BACKEND)

    assert manifest.summary == "Generated backend API."
    assert [file.path for file in manifest.files] == ["backend/src/app/main.py"]
    assert manifest.validation_commands == ["cd backend && pytest"]


def test_fallback_worker_manifest_contains_real_files() -> None:
    task = JobTask(
        worker_kind=WorkerKind.FRONTEND,
        title="Frontend",
        instructions="Build a local webapp",
    )

    manifest = extract_worker_file_manifest(
        fallback_worker_manifest_json(task, "Build a local webapp", "demo"),
        WorkerKind.FRONTEND,
    )

    assert any(file.path == "frontend/src/App.tsx" for file in manifest.files)
    assert any("npm run build" in command for command in manifest.validation_commands)


def test_worker_manifest_prompt_does_not_default_to_sqlite() -> None:
    task = JobTask(
        worker_kind=WorkerKind.BACKEND,
        title="Backend",
        instructions="Request: Build an in-memory game API",
    )

    prompt = worker_manifest_prompt(task, "Build an in-memory game API", "game")

    assert "when no database is specified, use local SQLite" not in prompt
    assert "Never default to SQLite" in prompt
    assert "Explicit exclusions override defaults" in prompt
    assert "never minify generated code" in prompt
    assert "Never delete, skip, or weaken a valid test" in prompt


def test_pwdlib_recommended_hashing_receives_argon2_extra() -> None:
    manifest = WorkerFileManifest(
        worker_kind=WorkerKind.BACKEND,
        summary="Authentication backend",
        operation="replace",
        files=[
            GeneratedFileSpec(
                "backend/pyproject.toml",
                '[project]\nname="auth-api"\nversion="1.0.0"\ndependencies=["pwdlib==0.3.0"]\n',
                WorkerKind.BACKEND,
            ),
            GeneratedFileSpec(
                "backend/src/app/security.py",
                "from pwdlib import PasswordHash\npassword_hash = PasswordHash.recommended()\n",
                WorkerKind.BACKEND,
            ),
        ],
    )

    normalized = normalize_worker_manifest(manifest, "react-fastapi")
    pyproject = next(
        file.content for file in normalized.files if file.path == "backend/pyproject.toml"
    )

    assert '"pwdlib[argon2]==0.3.0"' in pyproject


def test_async_sqlalchemy_receives_greenlet_runtime_dependency() -> None:
    manifest = WorkerFileManifest(
        worker_kind=WorkerKind.BACKEND,
        summary="Async persistence backend",
        operation="replace",
        files=[
            GeneratedFileSpec(
                "backend/pyproject.toml",
                (
                    '[project]\nname="async-api"\nversion="1.0.0"\n'
                    'dependencies=["sqlalchemy==2.0.36","asyncpg==0.30.0"]\n'
                ),
                WorkerKind.BACKEND,
            ),
            GeneratedFileSpec(
                "backend/src/app/main.py",
                "from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine\n",
                WorkerKind.BACKEND,
            ),
        ],
    )

    normalized = normalize_worker_manifest(manifest, "react-fastapi")
    pyproject = next(
        file.content for file in normalized.files if file.path == "backend/pyproject.toml"
    )

    assert '"greenlet==3.1.1"' in pyproject


def test_pwdlib_bcrypt_support_preserves_argon2_and_bcrypt_extras() -> None:
    manifest = WorkerFileManifest(
        worker_kind=WorkerKind.BACKEND,
        summary="Seed-compatible authentication backend",
        operation="replace",
        files=[
            GeneratedFileSpec(
                "backend/requirements.txt",
                "pwdlib[argon2]==0.2.1\n",
                WorkerKind.BACKEND,
            ),
            GeneratedFileSpec(
                "backend/app/security.py",
                (
                    "from pwdlib import PasswordHash\n"
                    "from pwdlib.hashers.argon2 import Argon2Hasher\n"
                    "from pwdlib.hashers.bcrypt import BcryptHasher\n"
                    "password_hash = PasswordHash((Argon2Hasher(), BcryptHasher()))\n"
                ),
                WorkerKind.BACKEND,
            ),
        ],
    )

    normalized = normalize_worker_manifest(manifest, "react-fastapi")
    requirements = next(
        file.content for file in normalized.files if file.path == "backend/requirements.txt"
    )

    assert requirements == "pwdlib[argon2,bcrypt]==0.2.1\n"


def test_worker_manifest_scope_rejects_cross_worker_files() -> None:
    manifest = WorkerFileManifest(
        worker_kind=WorkerKind.FRONTEND,
        summary="invalid",
        files=[
            GeneratedFileSpec(
                path="backend/src/app/main.py",
                content="app = object()",
                worker_kind=WorkerKind.FRONTEND,
            )
        ],
    )

    with pytest.raises(WorkerManifestScopeError, match="outside frontend/"):
        validate_worker_manifest_scope(manifest)


def test_worker_manifest_scope_allows_component_readme() -> None:
    manifest = WorkerFileManifest(
        worker_kind=WorkerKind.DATABASE,
        summary="database migration and operating notes",
        files=[
            GeneratedFileSpec(
                path="database/README.md",
                content="# Database setup\n",
                worker_kind=WorkerKind.DATABASE,
            ),
            GeneratedFileSpec(
                path="database/migrations/001_initial.sql",
                content="create table example (id bigint primary key);\n",
                worker_kind=WorkerKind.DATABASE,
            ),
        ],
    )

    validate_worker_manifest_scope(manifest)


def test_merge_file_specs_rejects_conflicting_content() -> None:
    specs = [
        GeneratedFileSpec("backend/main.py", "one", WorkerKind.BACKEND),
        GeneratedFileSpec("backend/main.py", "two", WorkerKind.BACKEND),
    ]

    with pytest.raises(ManifestConflictError, match="backend/main.py"):
        merge_file_specs(specs)


def test_collect_worker_file_manifests_drops_stale_success_after_failed_retry() -> None:
    task = JobTask(
        worker_kind=WorkerKind.BACKEND,
        title="Backend",
        instructions="Build backend",
    )
    job = JobState(request=JobRequest(prompt="Build an API"), tasks=[task])
    job.worker_results = [
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.BACKEND,
            status=TaskStatus.SUCCEEDED,
            summary="First attempt",
            output=json.dumps(
                {
                    "summary": "Generated backend.",
                    "files": [
                        {
                            "path": "backend/src/app/main.py",
                            "content": "app = object()\n",
                        }
                    ],
                }
            ),
        ),
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.BACKEND,
            status=TaskStatus.FAILED,
            summary="Retry failed",
            errors=["Request timed out."],
            attempt=2,
        ),
    ]

    assert collect_worker_file_manifests(job) == []


def _react_manifest(files: dict[str, str]) -> WorkerFileManifest:
    return WorkerFileManifest(
        worker_kind=WorkerKind.FRONTEND,
        summary="Custom application",
        operation="replace",
        files=[
            GeneratedFileSpec(path, content, WorkerKind.FRONTEND) for path, content in files.items()
        ],
    )


def test_runtime_contract_preserves_javascript_vite_config() -> None:
    manifest = _react_manifest(
        {
            "frontend/index.html": '<div id="root"></div>',
            "frontend/vite.config.mjs": "export default { server: { port: 5100 } };",
            "frontend/src/main.jsx": "import './App.jsx';",
            "frontend/src/App.jsx": "export default function App() { return <h1>Custom</h1>; }",
            "frontend/src/App.test.jsx": "test('renders', () => {});",
        }
    )

    normalize_worker_manifest(manifest, "react-vite")
    validate_worker_manifest_contract(manifest, "react-vite")
    files = {file.path: file.content for file in manifest.files}

    assert "frontend/vite.config.ts" not in files
    assert "port: 5100" in files["frontend/vite.config.mjs"]
    assert json.loads(files["frontend/tsconfig.json"])["compilerOptions"]["allowJs"] is True


def test_dom_test_contract_injects_environment_and_preserves_setup() -> None:
    manifest = _react_manifest(
        {
            "frontend/src/App.test.tsx": "import { render } from '@testing-library/react';",
            "frontend/src/test/setup.ts": "import '@testing-library/jest-dom/vitest';",
        }
    )

    normalize_worker_manifest(manifest, "react-vite")
    files = {file.path: file.content for file in manifest.files}

    assert 'from "vitest/config"' in files["frontend/vite.config.ts"]
    assert '"environment": "jsdom"' in files["frontend/vite.config.ts"]
    assert '"./src/test/setup.ts"' in files["frontend/vite.config.ts"]
    assert "frontend/src/App.tsx" not in files


def test_backend_requirements_are_not_replaced_with_incompatible_packaging() -> None:
    manifest = WorkerFileManifest(
        worker_kind=WorkerKind.BACKEND,
        summary="API",
        files=[
            GeneratedFileSpec(path, content, WorkerKind.BACKEND)
            for path, content in {
                "backend/requirements.txt": "fastapi==0.115.0\n",
                "backend/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
                "backend/tests/test_app.py": "def test_app(): assert True\n",
            }.items()
        ],
    )

    normalize_worker_manifest(manifest, "fastapi-api")
    validate_worker_manifest_contract(manifest, "fastapi-api")

    assert "backend/pyproject.toml" not in {file.path for file in manifest.files}


def test_backend_requirements_normalize_src_layout_to_importable_root() -> None:
    manifest = WorkerFileManifest(
        worker_kind=WorkerKind.BACKEND,
        summary="API",
        files=[
            GeneratedFileSpec(path, content, WorkerKind.BACKEND)
            for path, content in {
                "backend/requirements.txt": "fastapi==0.115.0\n",
                "backend/src/app/__init__.py": "",
                "backend/src/app/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
                "backend/tests/test_app.py": "from app.main import app\n",
                "backend/pytest.ini": "[pytest]\npythonpath = src\n",
            }.items()
        ],
        validation_commands=["PYTHONPATH=src python -m pytest"],
    )

    normalize_worker_manifest(manifest, "fastapi-api")

    files = {file.path: file.content for file in manifest.files}
    assert "backend/app/main.py" in files
    assert "backend/src/app/main.py" not in files
    assert files["backend/pytest.ini"] == "[pytest]\npythonpath = .\n"
    assert manifest.validation_commands == ["python -m pytest"]


@pytest.mark.parametrize("package", ["{broken", "[]", "null"])
@pytest.mark.parametrize("operation", ["replace", "patch"])
def test_contract_rejects_invalid_package_on_initial_and_repair(package, operation) -> None:
    manifest = _react_manifest({"frontend/package.json": package})
    manifest.operation = operation

    normalize_worker_manifest(manifest, "react-vite")

    with pytest.raises(WorkerManifestContractError, match="package.json"):
        validate_worker_manifest_contract(manifest, "react-vite")


def test_test_files_cannot_impersonate_entry_or_runtime_source() -> None:
    manifest = _react_manifest(
        {
            "frontend/index.html": '<div id="root"></div>',
            "frontend/src/main.test.tsx": "test('entry', () => {});",
            "frontend/src/setupTests.ts": "export {};",
        }
    )
    normalize_worker_manifest(manifest, "react-vite")

    with pytest.raises(WorkerManifestContractError) as error:
        validate_worker_manifest_contract(manifest, "react-vite")

    assert "entry point is required" in str(error.value)
    assert "runtime source is required" in str(error.value)


def test_setup_file_alone_does_not_satisfy_focused_test_contract() -> None:
    manifest = _react_manifest(
        {
            "frontend/index.html": '<div id="root"></div>',
            "frontend/src/main.tsx": "import './App';",
            "frontend/src/test/setup.ts": "export {};",
        }
    )
    normalize_worker_manifest(manifest, "react-vite")

    with pytest.raises(WorkerManifestContractError, match="focused frontend test"):
        validate_worker_manifest_contract(manifest, "react-vite")


def test_trusted_versions_cannot_be_overridden_in_other_dependency_groups() -> None:
    manifest = _react_manifest(
        {
            "frontend/package.json": json.dumps(
                {
                    "dependencies": {"vite": "1.0.0", "@testing-library/jest-dom": "7.0.1"},
                    "devDependencies": {"react": "1.0.0"},
                    "optionalDependencies": {"react-dom": "1.0.0"},
                }
            ),
        }
    )

    normalize_worker_manifest(manifest, "react-vite")
    package = json.loads(
        next(file.content for file in manifest.files if file.path.endswith("package.json"))
    )

    assert package["dependencies"]["react"] == "19.2.8"
    assert package["devDependencies"]["@testing-library/jest-dom"] == "6.9.1"
    assert package["devDependencies"]["@types/node"] == "24.3.0"
    assert package["scripts"]["build"] == "tsc && vite build"
    assert package["scripts"]["test"] == "vitest run"
    assert "react" not in package["devDependencies"]
    assert "react-dom" not in package["optionalDependencies"]
    assert "vite" not in package["dependencies"]
    assert "@testing-library/jest-dom" not in package["dependencies"]


def test_react_normalizer_imports_vitest_globals_before_first_validation() -> None:
    manifest = _react_manifest(
        {
            "frontend/src/App.test.tsx": (
                "describe('gallery', () => { it('renders', () => expect(true).toBe(true)); });\n"
            ),
        }
    )

    normalize_worker_manifest(manifest, "react-vite")
    files = {file.path: file.content for file in manifest.files}

    assert "import { describe, expect, it } from 'vitest';" in files["frontend/src/App.test.tsx"]


def test_react_normalizer_installs_observer_test_contract() -> None:
    manifest = _react_manifest(
        {
            "frontend/src/App.tsx": (
                "export function App() { new IntersectionObserver(() => {}); return <main />; }\n"
            ),
            "frontend/src/App.test.tsx": "test('renders', () => {});\n",
        }
    )

    normalize_worker_manifest(manifest, "react-vite")
    files = {file.path: file.content for file in manifest.files}

    assert "globalThis.IntersectionObserver" in files["frontend/src/test/setup.ts"]
    assert "import './test/setup';" in files["frontend/src/App.test.tsx"]
    assert "import { test } from 'vitest';" in files["frontend/src/App.test.tsx"]


def test_react_normalizer_imports_jest_dom_matcher_types() -> None:
    manifest = _react_manifest(
        {
            "frontend/src/App.test.tsx": (
                "import { expect, test } from 'vitest';\n"
                "test('renders', () => expect(document.body).toBeInTheDocument());\n"
            ),
        }
    )

    normalize_worker_manifest(manifest, "react-vite")
    files = {file.path: file.content for file in manifest.files}

    assert files["frontend/src/App.test.tsx"].startswith(
        "import '@testing-library/jest-dom/vitest';\n"
    )


def test_react_normalizer_rewrites_bare_jest_dom_setup_import() -> None:
    manifest = _react_manifest(
        {
            "frontend/src/test-setup.ts": (
                "import '@testing-library/jest-dom'\n"
                "import { afterEach } from 'vitest'\n"
            ),
            "frontend/src/App.test.tsx": (
                "import { test } from 'vitest';\ntest('ok', () => {});\n"
            ),
        }
    )

    normalize_worker_manifest(manifest, "react-vite")
    files = {file.path: file.content for file in manifest.files}

    assert "import '@testing-library/jest-dom/vitest'" in files["frontend/src/test-setup.ts"]
    assert "import '@testing-library/jest-dom'\n" not in files["frontend/src/test-setup.ts"]


def test_react_normalizer_preserves_intentionally_invalid_upload_fixture() -> None:
    manifest = _react_manifest(
        {
            "frontend/src/App.test.tsx": (
                "import userEvent from '@testing-library/user-event';\n"
                "await userEvent.upload(input, new File(['x'], 'wrong.mov', "
                "{ type: 'video/quicktime' }));\n"
            ),
        }
    )

    normalize_worker_manifest(manifest, "react-vite")
    files = {file.path: file.content for file in manifest.files}

    assert "userEvent.setup({ applyAccept: false }).upload(" in files[
        "frontend/src/App.test.tsx"
    ]


def test_react_normalizer_uses_accessible_label_for_native_video() -> None:
    manifest = _react_manifest(
        {
            "frontend/src/player.test.tsx": (
                "const player = await screen.findByRole('video', "
                "{ name: 'Play A Quiet Current' });\n"
            ),
        }
    )

    normalize_worker_manifest(manifest, "react-vite")
    files = {file.path: file.content for file in manifest.files}

    assert "findByLabelText('Play A Quiet Current')" in files[
        "frontend/src/player.test.tsx"
    ]
    assert "findByRole('video'" not in files["frontend/src/player.test.tsx"]


def test_react_normalizer_does_not_inject_vitest_into_playwright_spec() -> None:
    manifest = _react_manifest(
        {
            "frontend/tests/playback.spec.ts": (
                "import { expect, test } from '@playwright/test';\n"
                "test('plays', async ({ page }) => expect(page).toBeTruthy());\n"
            ),
        }
    )

    normalize_worker_manifest(manifest, "react-vite")
    files = {file.path: file.content for file in manifest.files}

    assert "from 'vitest'" not in files["frontend/tests/playback.spec.ts"]


def test_react_normalizer_injects_referenced_environment_example() -> None:
    manifest = _react_manifest(
        {
            "frontend/src/api.ts": (
                "export const baseUrl = import.meta.env.VITE_API_BASE_URL;\n"
            ),
            "frontend/src/App.test.tsx": "import { test } from 'vitest';\ntest('ok', () => {});\n",
        }
    )

    normalize_worker_manifest(manifest, "react-fastapi")
    files = {file.path: file.content for file in manifest.files}

    assert files["frontend/.env.example"] == "VITE_API_BASE_URL=http://localhost:8000\n"


def test_backend_normalizer_merges_missing_environment_example_variables() -> None:
    manifest = WorkerFileManifest(
        worker_kind=WorkerKind.BACKEND,
        summary="Backend",
        files=[
            GeneratedFileSpec(
                path="backend/.env.example",
                content="DATABASE_URL=postgresql://localhost/app\n",
                worker_kind=WorkerKind.BACKEND,
            ),
            GeneratedFileSpec(
                path="backend/app/main.py",
                content=(
                    "import os\n"
                    "database_url = os.getenv('DATABASE_URL')\n"
                    "test_database_url = os.getenv('TEST_DATABASE_URL')\n"
                ),
                worker_kind=WorkerKind.BACKEND,
            ),
        ],
        operation="replace",
    )

    normalize_worker_manifest(manifest, "react-fastapi")
    files = {file.path: file.content for file in manifest.files}

    assert files["backend/.env.example"] == (
        "DATABASE_URL=postgresql://localhost/app\nTEST_DATABASE_URL=\n"
    )


def test_react_normalizer_hardens_referenced_node_tsconfig() -> None:
    manifest = _react_manifest(
        {
            "frontend/tsconfig.node.json": json.dumps(
                {"compilerOptions": {"composite": True}, "include": ["vite.config.ts"]}
            ),
            "frontend/src/App.test.tsx": "import { test } from 'vitest';\ntest('ok', () => {});\n",
        }
    )

    normalize_worker_manifest(manifest, "react-vite")
    files = {file.path: file.content for file in manifest.files}
    config = json.loads(files["frontend/tsconfig.node.json"])

    assert config["compilerOptions"]["target"] == "ES2022"
    assert config["compilerOptions"]["lib"] == ["ES2022"]
    assert config["compilerOptions"]["skipLibCheck"] is True
    assert config["compilerOptions"]["types"] == ["node"]


def test_manifest_contract_rejects_invalid_typescript_config() -> None:
    manifest = _react_manifest(
        {
            "frontend/tsconfig.node.json": "not-json",
        }
    )

    with pytest.raises(WorkerManifestContractError, match="Invalid frontend/tsconfig.node.json"):
        validate_worker_manifest_contract(manifest, "react-vite")
