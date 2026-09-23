import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from software_developer_agent.artifacts.validation import (
    ProjectValidationReport,
    ProjectValidator,
    _backend_runtime_connectivity_findings,
    _backend_manifest_findings,
    _backend_references_query_parameter,
    _documented_path_exists,
    _documents_pyproject_install,
    _excerpt,
    _execution_safety_findings,
    _frontend_implements_request_field,
    _frontend_references_query_parameter,
    _frontend_references_route,
    _frontend_route_methods,
    _frontend_runtime_connectivity_findings,
    _frontend_test_contract_findings,
    _is_operational_route,
    _is_runtime_security_path,
    _looks_like_infrastructure_failure,
    _migration_ownership_findings,
    _persistence_integration_findings,
    _synthetic_smoke_environment,
)
from software_developer_agent.capabilities.registry import resolve_project_spec
from software_developer_agent.capabilities.validation_adapters import validate_with_adapters
from software_developer_agent.config.settings import Settings
from software_developer_agent.models.job_state import JobRequest, JobState, WorkerKind


def test_validator_requires_frontend_lockfile(tmp_path) -> None:
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend/package.json").write_text(
        '{"scripts":{"test":"vitest","build":"vite build"}}',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    job = JobState(request=JobRequest(prompt="Build a React frontend"))
    validator = ProjectValidator(Settings(app_env="development", enable_artifact_validation=False))

    report = validator.validate(tmp_path, job)

    assert not report.passed
    assert report.retry_targets == [WorkerKind.FRONTEND]
    assert "package-lock.json is missing" in (report.failure_reason or "")


def test_validation_excerpt_preserves_middle_error_and_removes_ansi_noise() -> None:
    output = (
        "test summary\n"
        + "<div>rendered markup</div>\n" * 300
        + "\x1b[31mTestingLibraryElementError: Unable to find Checkout complete\x1b[0m\n"
        + "<span>more rendered markup</span>\n" * 300
        + "src/App.test.tsx:10:20\n"
    )

    excerpt = _excerpt(output, limit=1_000)

    assert "Unable to find Checkout complete" in excerpt
    assert "src/App.test.tsx:10:20" in excerpt
    assert "\x1b[" not in excerpt
    assert len(excerpt) <= 1_050


def test_vitest_setup_rejects_bare_jest_dom_import() -> None:
    findings = _frontend_test_contract_findings(
        {
            "frontend/package.json": json.dumps(
                {
                    "scripts": {"test": "vitest run", "build": "vite build"},
                    "devDependencies": {"vitest": "4.1.11"},
                }
            ),
            "frontend/src/test-setup.ts": "import '@testing-library/jest-dom'\n",
        }
    )

    assert findings == [
        "frontend/src/test-setup.ts must import @testing-library/jest-dom/vitest when Vitest is used."
    ]


def test_contract_query_parameter_detection_rejects_renamed_reserved_parameter() -> None:
    frontend = "fetch(`/api/admin/analytics?from_=${start}&to=${end}`)"
    backend = "def analytics(from_: date, to: date): return {}"

    assert not _frontend_references_query_parameter(frontend, "from")
    assert _frontend_references_query_parameter(frontend, "to")
    assert not _backend_references_query_parameter(backend, "from")
    assert _backend_references_query_parameter(backend, "to")
    assert _backend_references_query_parameter(
        'def analytics(from_: date = Query(alias="from")): return {}',
        "from",
    )


def test_contract_accepts_form_data_for_multipart_wrapper() -> None:
    assert _frontend_implements_request_field(
        "const body = new FormData(); body.append('video', file);",
        "multipart_form_data",
    )
    assert not _frontend_implements_request_field("const body = {};", "multipart_form_data")


def test_synthetic_smoke_environment_uses_non_secret_validation_values(tmp_path) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / ".env.example").write_text(
        "DATABASE_URL=\nJWT_SECRET=\nJWT_EXPIRES_MINUTES=480\n"
        "ENABLE_SIGNUP=true\nCORS_ORIGIN=http://localhost:5173\n",
        encoding="utf-8",
    )

    environment = _synthetic_smoke_environment(backend)

    assert environment["DATABASE_URL"].startswith("postgresql+psycopg://validator:")
    assert len(environment["JWT_SECRET"]) >= 32
    assert environment["CORS_ORIGIN"] == "http://127.0.0.1:9"
    assert environment["JWT_EXPIRES_MINUTES"] == "1"
    assert environment["ENABLE_SIGNUP"] == "false"
    assert "localhost:5173" not in environment.values()


def _valid_backend_pyproject(*dependencies: str) -> str:
    dependency_lines = ",".join(json.dumps(dependency) for dependency in dependencies)
    return (
        '[build-system]\nrequires=["setuptools==75.0.0"]\n'
        'build-backend="setuptools.build_meta"\n'
        '[project]\nname="demo"\nversion="1.0.0"\n'
        f'dependencies=[{dependency_lines}]\n'
    )


def test_backend_manifest_requires_greenlet_for_async_sqlalchemy() -> None:
    files = {"backend/pyproject.toml": Path("backend/pyproject.toml")}
    text_files = {
        "backend/pyproject.toml": _valid_backend_pyproject(
            "sqlalchemy==2.0.36",
            "asyncpg==0.30.0",
        ),
        "backend/src/app/main.py": (
            "from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine\n"
            "from fastapi.middleware.cors import CORSMiddleware\n"
            "app.add_middleware(CORSMiddleware, "
            "allow_origins=['http://localhost:5173','http://127.0.0.1:5173'])\n"
        ),
    }

    findings = _backend_manifest_findings(
        files,
        text_files,
        resolve_project_spec("Build a React and FastAPI application"),
    )

    assert "Async SQLAlchemy backends must declare the certified greenlet runtime dependency." in findings


def test_backend_manifest_rejects_bcrypt_seeds_with_argon2_only_runtime() -> None:
    files = {"backend/pyproject.toml": Path("backend/pyproject.toml")}
    text_files = {
        "backend/pyproject.toml": _valid_backend_pyproject("pwdlib[argon2]==0.2.1"),
        "backend/src/app/main.py": (
            "from pwdlib import PasswordHash\n"
            "password_hash = PasswordHash.recommended()\n"
            "from fastapi.middleware.cors import CORSMiddleware\n"
            "app.add_middleware(CORSMiddleware, "
            "allow_origins=['http://localhost:5173','http://127.0.0.1:5173'])\n"
        ),
        "database/seed/001.sql": (
            "INSERT INTO users(password_hash) VALUES "
            "('$2b$12$LQv3c1yqBW1Qm8tT4QjK/eG9Yj0x6mQ9QkJ5Q9Q0J8Qj8v7X0XG2u');"
        ),
    }

    findings = _backend_manifest_findings(
        files,
        text_files,
        resolve_project_spec("Build a React and FastAPI application with login"),
    )

    assert any("Bcrypt seed passwords are incompatible" in finding for finding in findings)


def test_backend_manifest_rejects_pgcrypto_bcrypt_seeds_with_argon2_only_runtime() -> None:
    files = {"backend/pyproject.toml": Path("backend/pyproject.toml")}
    text_files = {
        "backend/pyproject.toml": _valid_backend_pyproject("pwdlib[argon2]==0.2.1"),
        "backend/src/app/main.py": (
            "from pwdlib import PasswordHash\n"
            "password_hash = PasswordHash.recommended()\n"
            "from fastapi.middleware.cors import CORSMiddleware\n"
            "app.add_middleware(CORSMiddleware, "
            "allow_origins=['http://localhost:5173','http://127.0.0.1:5173'])\n"
        ),
        "database/seed.sql": (
            "INSERT INTO users(password_hash) VALUES "
            "(crypt('change-me', gen_salt('bf')));"
        ),
    }

    findings = _backend_manifest_findings(
        files,
        text_files,
        resolve_project_spec("Build a React and FastAPI application with login"),
    )

    assert any("Bcrypt seed passwords are incompatible" in finding for finding in findings)


def test_backend_manifest_requires_complete_fastapi_cors_contract() -> None:
    files = {"backend/pyproject.toml": Path("backend/pyproject.toml")}
    text_files = {
        "backend/pyproject.toml": _valid_backend_pyproject("fastapi==0.115.6"),
        "backend/src/app/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
    }

    findings = _backend_manifest_findings(
        files,
        text_files,
        resolve_project_spec("Build a React and FastAPI application"),
    )

    assert any("must install CORSMiddleware" in finding for finding in findings)


def test_backend_manifest_accepts_documented_dynamic_cors_origins() -> None:
    files = {"backend/pyproject.toml": Path("backend/pyproject.toml")}
    text_files = {
        "backend/pyproject.toml": _valid_backend_pyproject("fastapi==0.115.6"),
        "backend/src/app/main.py": (
            "import os\n"
            "from fastapi.middleware.cors import CORSMiddleware\n"
            "CORS_ORIGINS = os.getenv('CORS_ORIGINS', 'http://localhost:5173').split(',')\n"
            "app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS)\n"
        ),
        "backend/.env.example": "CORS_ORIGINS=http://localhost:5173\n",
    }

    findings = _backend_manifest_findings(
        files,
        text_files,
        resolve_project_spec("Build a React and FastAPI application"),
    )

    assert not any("CORS" in finding for finding in findings)


def test_backend_manifest_rejects_documented_but_unused_cors_origins() -> None:
    files = {"backend/pyproject.toml": Path("backend/pyproject.toml")}
    text_files = {
        "backend/pyproject.toml": _valid_backend_pyproject("fastapi==0.115.6"),
        "backend/src/app/main.py": (
            "from fastapi.middleware.cors import CORSMiddleware\n"
            "app.add_middleware(CORSMiddleware, "
            "allow_origins=['http://localhost:5173'])\n"
        ),
        "backend/.env.example": "CORS_ORIGINS=http://localhost:5173\n",
    }

    findings = _backend_manifest_findings(
        files,
        text_files,
        resolve_project_spec("Build a React and FastAPI application"),
    )

    assert any("CORS_ORIGINS" in finding for finding in findings)


def test_backend_manifest_rejects_fixed_dual_localhost_cors_origins() -> None:
    files = {"backend/pyproject.toml": Path("backend/pyproject.toml")}
    text_files = {
        "backend/pyproject.toml": _valid_backend_pyproject("fastapi==0.115.6"),
        "backend/src/app/main.py": (
            "from fastapi.middleware.cors import CORSMiddleware\n"
            "app.add_middleware(CORSMiddleware, allow_origins=["
            "'http://localhost:5173','http://127.0.0.1:5173'])\n"
        ),
    }

    findings = _backend_manifest_findings(
        files,
        text_files,
        resolve_project_spec("Build a React and FastAPI application"),
    )

    assert any("fixed localhost origins" in finding for finding in findings)


def test_frontend_runtime_rejects_hardcoded_local_api_origin() -> None:
    findings = _frontend_runtime_connectivity_findings(
        {"frontend/src/api.ts": "export const baseUrl = 'http://localhost:8000';\n"},
        resolve_project_spec("Build a React and FastAPI application"),
    )

    assert any("hardcodes a localhost runtime URL" in finding for finding in findings)


def test_frontend_runtime_accepts_same_origin_or_environment_api_base() -> None:
    findings = _frontend_runtime_connectivity_findings(
        {
            "frontend/src/api.ts": (
                "export const baseUrl = import.meta.env.VITE_API_BASE_URL ?? '';\n"
                "export const games = () => fetch(`${baseUrl}/api/games`);\n"
            )
        },
        resolve_project_spec("Build a React and FastAPI application"),
    )

    assert findings == []


def test_frontend_runtime_ignores_build_tool_proxy_configuration() -> None:
    findings = _frontend_runtime_connectivity_findings(
        {
            "frontend/vite.config.ts": (
                "export default { server: { proxy: { '/api': "
                "{ target: 'http://localhost:8000' } } } };\n"
            )
        },
        resolve_project_spec("Build a React and FastAPI application"),
    )

    assert findings == []


def test_node_backend_rejects_fixed_cors_configuration() -> None:
    text_files = {
        "backend/package.json": json.dumps(
            {
                "scripts": {"test": "vitest run", "build": "tsc"},
                "dependencies": {"cors": "2.8.5", "express": "5.1.0"},
            }
        ),
        "backend/src/app.ts": (
            "import cors from 'cors';\n"
            "app.use(cors({ origin: 'http://localhost:5173' }));\n"
        ),
    }

    findings = _backend_runtime_connectivity_findings(
        text_files,
        resolve_project_spec("Build a React and Express application"),
    )

    assert any("Express CORS must consume" in finding for finding in findings)


def test_database_worker_migration_rejects_second_backend_migration_system() -> None:
    files = {
        "database/migrations/001.sql": SimpleNamespace(),
        "backend/alembic/versions/0001_initial.py": SimpleNamespace(),
    }

    findings = _migration_ownership_findings(files)

    assert len(findings) == 1
    assert "second migration system" in findings[0]
    assert _migration_ownership_findings(
        {"database/migrations/001.sql": SimpleNamespace()}
    ) == []


def test_python_smoke_environment_does_not_change_test_environment(tmp_path) -> None:
    backend = tmp_path / "backend"
    app = backend / "src" / "app"
    tests = backend / "tests"
    app.mkdir(parents=True)
    tests.mkdir()
    (backend / "pyproject.toml").write_text(
        '[project]\nname="demo"\nversion="1.0.0"\n',
        encoding="utf-8",
    )
    (backend / ".env.example").write_text("JWT_SECRET=\n", encoding="utf-8")
    (app / "main.py").write_text("app = object()\n", encoding="utf-8")
    validator = ProjectValidator(Settings(app_env="test", enable_persistence=False))
    spec = resolve_project_spec("Build a FastAPI backend", {"capability_id": "fastapi-api"})

    script = validator._python_sandbox_script(tmp_path, backend, spec)

    assert "/tmp/venv/bin/python -m pytest -vv --tb=long && env JWT_SECRET=" in script


def test_docker_execution_retries_transient_infrastructure(tmp_path, monkeypatch) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run", "build": "vite build"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "software_developer_agent.artifacts.validation.shutil.which",
        lambda _: "/usr/local/bin/docker",
    )
    calls: list[dict[str, object]] = []

    class RecordingValidator(ProjectValidator):
        def _run(self, report, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(failure_kind=None)

        def _validate_node_audits_in_docker(self, *args, **kwargs):
            return None

    validator = RecordingValidator(
        Settings(
            app_env="development",
            enable_persistence=False,
            artifact_infrastructure_retry_attempts=2,
        )
    )
    report = ProjectValidationReport(passed=True)

    validator._validate_in_docker(
        tmp_path,
        report,
        resolve_project_spec("Build a React frontend"),
        [WorkerKind.FRONTEND],
    )

    assert calls[0]["infrastructure_retries"] == 2
    docker_script = calls[0]["command"][-1]
    assert docker_script.index("npm run build") < docker_script.index("npm test")
    assert "build_status" in docker_script
    assert "test_status" in docker_script


def test_node_validation_separates_production_and_development_audits(tmp_path) -> None:
    component = tmp_path / "frontend"
    component.mkdir()
    (component / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run", "build": "vite build"}}),
        encoding="utf-8",
    )
    calls: list[tuple[str, list[str], bool]] = []

    class RecordingValidator(ProjectValidator):
        def _run(self, report, *, name, command, blocking=True, **kwargs):
            calls.append((name, command, blocking))

    report = ProjectValidationReport(passed=True)
    RecordingValidator(Settings(app_env="test", enable_persistence=False))._validate_node_component(
        component,
        report,
        worker_kind=WorkerKind.FRONTEND,
        result_prefix="frontend",
    )

    assert calls[-3:] == [
        (
            "frontend_production_dependency_audit",
            [calls[-3][1][0], "audit", "--omit=dev", "--audit-level=high"],
            True,
        ),
        (
            "frontend_development_critical_audit",
            [calls[-2][1][0], "audit", "--audit-level=critical"],
            True,
        ),
        (
            "frontend_development_high_advisory",
            [calls[-1][1][0], "audit", "--audit-level=high"],
            False,
        ),
    ]


def test_nonblocking_dependency_advisory_is_recorded_without_failing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "software_developer_agent.artifacts.validation.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="high advisory", stderr=""),
    )
    report = ProjectValidationReport(passed=True)

    ProjectValidator(Settings(app_env="test", enable_persistence=False))._run(
        report,
        name="frontend_development_high_advisory",
        worker_kind=WorkerKind.FRONTEND,
        command=["npm", "audit"],
        cwd=tmp_path,
        blocking=False,
    )

    assert report.passed
    assert report.checks == ["frontend_development_high_advisory:advisory"]
    assert report.results[0].passed is False


def test_runtime_security_path_excludes_test_fixtures_but_not_application_code() -> None:
    assert not _is_runtime_security_path("frontend/src/App.test.tsx")
    assert not _is_runtime_security_path("backend/tests/test_api.py")
    assert not _is_runtime_security_path("database/seed.sql")
    assert not _is_runtime_security_path("backend/fixtures/users.py")
    assert _is_runtime_security_path("frontend/src/App.tsx")
    assert _is_runtime_security_path("backend/app/main.py")


def test_validation_report_round_trips_adapter_findings() -> None:
    report = ProjectValidationReport(
        passed=False,
        adapter_findings=[
            {
                "adapter_id": "commerce",
                "code": "exact_money_missing",
                "message": "Exact money representation is missing.",
                "worker_kind": "backend",
                "blocking": True,
            }
        ],
    )

    restored = ProjectValidationReport.from_dict(report.to_dict())

    assert restored.adapter_findings == report.adapter_findings


def test_execution_safety_allows_fixed_python_import_probe() -> None:
    findings = _execution_safety_findings(
        {
            "backend/tests/test_project_root_import.py": (
                "import subprocess\nimport sys\n"
                "result = subprocess.run([sys.executable, '-c', "
                "'from app.main import app; assert app is not None'], check=False)\n"
            )
        }
    )

    assert findings == []


def test_execution_safety_allows_test_fixture_cleanup_in_sandbox() -> None:
    findings = _execution_safety_findings(
        {
            "backend/tests/test_upload.py": (
                "import os\n"
                "def test_cleanup(tmp_path):\n"
                "    os.remove(tmp_path / 'upload.mp4')\n"
            )
        }
    )

    assert findings == []


def test_execution_safety_blocks_dynamic_python_subprocess() -> None:
    findings = _execution_safety_findings(
        {
            "backend/tests/test_command.py": (
                "import subprocess\n"
                "def run(command):\n    return subprocess.run(command, shell=True)\n"
            )
        }
    )

    assert findings == [
        "backend/tests/test_command.py contains unsafe generated-code operation: shell execution."
    ]


def test_audit_timeout_never_targets_worker_retry(tmp_path, monkeypatch) -> None:
    attempts = 0

    def timeout(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise subprocess.TimeoutExpired(
            cmd=args[0],
            timeout=kwargs["timeout"],
            output="",
            stderr="registry request pending",
        )

    monkeypatch.setattr(
        "software_developer_agent.artifacts.validation.subprocess.run",
        timeout,
    )
    report = ProjectValidationReport(passed=True)
    validator = ProjectValidator(
        Settings(
            app_env="test",
            enable_persistence=False,
            artifact_infrastructure_retry_attempts=2,
        )
    )

    validator._run(
        report,
        name="frontend_production_dependency_audit",
        worker_kind=WorkerKind.FRONTEND,
        command=["npm", "audit", "--omit=dev"],
        cwd=tmp_path,
        phase="dependency_security",
        failure_kind="security",
        infrastructure_retries=2,
        infrastructure_failure_is_advisory=True,
        incomplete_blocks_release=True,
    )

    assert attempts == 3
    assert report.passed
    assert not report.release_ready
    assert report.retry_targets == []
    assert report.failure_kind is None
    assert report.results[-1].timed_out
    assert report.results[-1].failure_kind == "infrastructure"
    assert report.advisories[0]["blocking_publication"] is True


def test_real_dependency_audit_finding_remains_blocking(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "software_developer_agent.artifacts.validation.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="critical vulnerability in example-package",
            stderr="",
        ),
    )
    report = ProjectValidationReport(passed=True)

    ProjectValidator(Settings(app_env="test", enable_persistence=False))._run(
        report,
        name="frontend_production_dependency_audit",
        worker_kind=WorkerKind.FRONTEND,
        command=["npm", "audit", "--omit=dev"],
        cwd=tmp_path,
        phase="dependency_security",
        failure_kind="security",
        infrastructure_failure_is_advisory=True,
        incomplete_blocks_release=True,
    )

    assert not report.passed
    assert not report.release_ready
    assert report.failure_kind == "security"
    assert report.retry_targets == [WorkerKind.FRONTEND]


def test_validator_scans_hidden_configuration_files(tmp_path) -> None:
    (tmp_path / "backend/src/app").mkdir(parents=True)
    (tmp_path / "backend/pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n",
        encoding="utf-8",
    )
    (tmp_path / "backend/src/app/main.py").write_text("app = object()\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        "DATABASE_URL=sqlite:///./local.sqlite3\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    job = JobState(
        request=JobRequest(prompt="Build a local API. No database or persistence."),
    )
    validator = ProjectValidator(Settings(app_env="development", enable_artifact_validation=False))

    report = validator.validate(tmp_path, job)

    assert not report.passed
    assert "Database configuration was not positively requested" in (report.failure_reason or "")


def test_validator_targets_only_frontend_for_missing_frontend_env_example(tmp_path) -> None:
    (tmp_path / "frontend/src").mkdir(parents=True)
    (tmp_path / "frontend/package.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "version": "0.1.0",
                "scripts": {"test": "vitest run", "build": "vite build"},
                "dependencies": {"vite": "7.0.0", "vitest": "3.0.0"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "frontend/package-lock.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "version": "0.1.0",
                "lockfileVersion": 3,
                "packages": {"": {"name": "demo", "version": "0.1.0"}},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "frontend/src/api.ts").write_text(
        "export const apiBase = import.meta.env.VITE_API_BASE_URL;\n",
        encoding="utf-8",
    )
    (tmp_path / "frontend/src/App.test.tsx").write_text("export {};\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "npm ci\nnpm test\nnpm run build\n",
        encoding="utf-8",
    )
    job = JobState(request=JobRequest(prompt="Build a React frontend"))

    report = ProjectValidator(
        Settings(app_env="development", enable_artifact_validation=False)
    ).validate(tmp_path, job)

    assert not report.passed
    assert report.retry_targets == [WorkerKind.FRONTEND]
    assert "frontend/.env.example is missing" in (report.failure_reason or "")


def test_frontend_contract_method_detection() -> None:
    frontend_source = """
    fetch('/api/quote', {
      method: 'POST',
      body: JSON.stringify({mode: 'random'})
    })
    """

    assert _frontend_route_methods(frontend_source, "/api/quote") == {"POST"}


def test_frontend_contract_does_not_borrow_method_from_later_route() -> None:
    frontend_source = """
    const products = () => request('/api/products');
    const checkout = () => request('/api/checkout', { method: 'POST' });
    """

    assert _frontend_route_methods(frontend_source, "/api/products") == {"GET"}
    assert _frontend_route_methods(frontend_source, "/api/checkout") == {"POST"}


def test_frontend_contract_allows_get_and_post_on_same_route() -> None:
    frontend_source = """
    const listMovies = () => request('/api/movies');
    const uploadMovie = (body: FormData) => request('/api/movies', { method: 'POST', body });
    """

    assert _frontend_route_methods(frontend_source, "/api/movies") == {"GET", "POST"}


def test_frontend_contract_infers_method_from_typed_request_wrapper() -> None:
    frontend_source = """
    async function request<T>(path: string, body: object): Promise<T> {
      return fetch(`${base}${path}`, {
        method: 'POST',
        body: JSON.stringify(body)
      }).then(response => response.json());
    }
    export const createGame = (level: number) => request('/api/games', { level });
    """

    assert _frontend_route_methods(frontend_source, "/api/games") == {"POST"}


def test_frontend_contract_does_not_borrow_method_from_variable_routes() -> None:
    frontend_source = (
        "const api={products:()=>request('/api/products'),"
        "add:()=>request(cartItems,{method:'POST'}),"
        "update:()=>request(`${cartItems}/${id}`,{method:'PATCH'}),"
        "remove:()=>request(`${cartItems}/${id}`,{method:'DELETE'})};"
    )

    assert _frontend_route_methods(frontend_source, "/api/products") == {"GET"}


def test_frontend_contract_resolves_static_route_aliases() -> None:
    frontend_source = """
    const cartResource=`/${['api','cart'].join('/')}`;
    const cartItems=`${cartResource}/items`;
    const api={
      cart:()=>request(cartResource),
      add:()=>request(cartItems,{method:'POST'}),
      update:(id:string)=>request(`${cartItems}/${id}`,{method:'PATCH'})
    };
    """

    assert _frontend_references_route(frontend_source, "/api/cart")
    assert _frontend_route_methods(frontend_source, "/api/cart") == {"GET"}
    assert _frontend_route_methods(frontend_source, "/api/cart/items") == {"POST"}
    assert _frontend_route_methods(frontend_source, "/api/cart/items/{product_id}") == {"PATCH"}


def test_frontend_contract_route_matching_respects_endpoint_boundaries() -> None:
    frontend_source = "request('/api/cart/items',{method:'POST'})"

    assert not _frontend_references_route(frontend_source, "/api/cart")


def test_frontend_contract_matches_dynamic_query_values_by_route_path() -> None:
    frontend_source = "request(`/api/analytics?from=${from}&to=${to}`)"

    assert _frontend_references_route(
        frontend_source,
        "/api/analytics?from=2025-01-01&to=2025-01-31",
    )


def test_frontend_contract_matches_template_literal_route_parameters() -> None:
    frontend_source = "fetch(`/api/products/${productId}`)"

    assert _frontend_references_route(frontend_source, "/api/products/{product_id}")


def test_operational_contract_routes_do_not_require_frontend_calls() -> None:
    assert _is_operational_route({"path": "/health", "method": "GET"})
    assert _is_operational_route({"path": "/api/internal/status", "frontend_required": False})
    assert not _is_operational_route({"path": "/api/products", "method": "GET"})


def test_database_request_requires_runtime_connection_code() -> None:
    spec = resolve_project_spec("Build a FastAPI app with a PostgreSQL database")

    findings = _persistence_integration_findings(
        {
            "backend/src/app/main.py": "app = FastAPI()",
            "backend/requirements.txt": "psycopg==3.2.3",
            "backend/.env.example": "DATABASE_URL=",
        },
        spec,
    )

    assert findings == [
        (
            "The request requires database persistence, but backend runtime code does not "
            "configure or open a database connection."
        )
    ]


def test_database_request_accepts_runtime_connection_code() -> None:
    spec = resolve_project_spec("Build a FastAPI app with a PostgreSQL database")

    findings = _persistence_integration_findings(
        {"backend/src/app/main.py": "connection = psycopg.connect(DATABASE_URL)"},
        spec,
    )

    assert findings == []


def test_readme_bare_manifest_path_resolves_inside_component(tmp_path) -> None:
    backend_manifest = tmp_path / "backend/requirements.txt"

    assert _documented_path_exists(
        "requirements.txt",
        {"backend/requirements.txt": backend_manifest},
    )


def test_readme_local_env_path_resolves_to_committed_example(tmp_path) -> None:
    env_example = tmp_path / "frontend/.env.example"

    assert _documented_path_exists(
        "frontend/.env",
        {"frontend/.env.example": env_example},
    )


def test_readme_pyproject_install_accepts_optional_dependency_group() -> None:
    assert _documents_pyproject_install('python -m pip install ".[test]"')


def test_validator_rejects_unpinned_frontend_dependencies(tmp_path) -> None:
    (tmp_path / "frontend/src").mkdir(parents=True)
    (tmp_path / "frontend/package.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "version": "0.1.0",
                "scripts": {"test": "vitest run", "build": "vite build"},
                "dependencies": {"react": "^18.3.1"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "frontend/package-lock.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "version": "0.1.0",
                "lockfileVersion": 3,
                "packages": {"": {"name": "demo", "version": "0.1.0"}},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "frontend/src/App.test.tsx").write_text("export {};\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "npm ci\nnpm test\nnpm run build\n",
        encoding="utf-8",
    )
    job = JobState(request=JobRequest(prompt="Build a React frontend"))

    report = ProjectValidator(
        Settings(app_env="development", enable_artifact_validation=False)
    ).validate(tmp_path, job)

    assert not report.passed
    assert "must use an exact version" in (report.failure_reason or "")


def test_validator_rejects_unsafe_generated_test_script(tmp_path) -> None:
    (tmp_path / "frontend/src").mkdir(parents=True)
    (tmp_path / "frontend/package.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "version": "0.1.0",
                "scripts": {"test": "vitest run; rm -rf /", "build": "vite build"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "frontend/package-lock.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "version": "0.1.0",
                "lockfileVersion": 3,
                "packages": {"": {"name": "demo", "version": "0.1.0"}},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "frontend/src/App.test.tsx").write_text("export {};\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "npm ci\nnpm test\nnpm run build\n",
        encoding="utf-8",
    )
    job = JobState(request=JobRequest(prompt="Build a React frontend"))

    report = ProjectValidator(
        Settings(app_env="development", enable_artifact_validation=False)
    ).validate(tmp_path, job)

    assert not report.passed
    assert "unsupported command" in (report.failure_reason or "")


def test_validator_cleans_backend_build_metadata(tmp_path) -> None:
    egg_info = tmp_path / "backend/src/demo.egg-info"
    egg_info.mkdir(parents=True)
    (egg_info / "PKG-INFO").write_text("Name: demo\n", encoding="utf-8")

    ProjectValidator._clean_validation_outputs(tmp_path)

    assert not egg_info.exists()


def test_react_adapter_detects_heading_query_semantic_mismatch(tmp_path) -> None:
    source = tmp_path / "frontend/src"
    source.mkdir(parents=True)
    (source / "App.tsx").write_text(
        (
            "export function App() { return <main><p>India Heritage Gallery</p>"
            "<h1>Beautiful places</h1></main>; }\n"
        ),
        encoding="utf-8",
    )
    (source / "App.test.tsx").write_text(
        "screen.getByRole('heading', { name: /india heritage gallery/i });\n",
        encoding="utf-8",
    )
    spec = resolve_project_spec("Build a React frontend", {"capability_id": "react-vite"})

    result = validate_with_adapters(tmp_path, spec)

    assert [finding.code for finding in result.blocking_findings] == ["test_heading_role_mismatch"]


def test_react_adapter_defers_data_driven_heading_to_runtime(tmp_path) -> None:
    source = tmp_path / "frontend/src"
    source.mkdir(parents=True)
    (source / "App.tsx").write_text(
        (
            "const places = [{ name: 'Taj Mahal' }];\n"
            "export function App() { return <main>{places.map((place) => "
            "<h3 key={place.name}>{place.name}</h3>)}</main>; }\n"
        ),
        encoding="utf-8",
    )
    (source / "App.test.tsx").write_text(
        "screen.getByRole('heading', { name: /taj mahal/i });\n",
        encoding="utf-8",
    )
    spec = resolve_project_spec("Build a React frontend", {"capability_id": "react-vite"})

    result = validate_with_adapters(tmp_path, spec)

    assert result.blocking_findings == []
    assert [finding.code for finding in result.advisories] == [
        "dynamic_heading_requires_runtime_verification"
    ]


def test_react_adapter_detects_ambiguous_singular_alt_query(tmp_path) -> None:
    source = tmp_path / "frontend/src"
    source.mkdir(parents=True)
    (source / "App.tsx").write_text(
        (
            "export function App() { return <><img alt='Heritage place' />"
            "<img alt='Heritage place' /></>; }\n"
        ),
        encoding="utf-8",
    )
    (source / "App.test.tsx").write_text(
        "screen.getByAltText(/heritage place/i);\n",
        encoding="utf-8",
    )
    spec = resolve_project_spec("Build a React frontend", {"capability_id": "react-vite"})

    result = validate_with_adapters(tmp_path, spec)

    assert [finding.code for finding in result.blocking_findings] == [
        "singular_alt_query_is_ambiguous"
    ]


def test_auth_adapter_requires_server_enforcement_and_negative_tests(tmp_path) -> None:
    (tmp_path / "backend/src").mkdir(parents=True)
    (tmp_path / "backend/tests").mkdir(parents=True)
    (tmp_path / "backend/src/main.py").write_text(
        "def dashboard(): return {'role': 'admin'}\n",
        encoding="utf-8",
    )
    (tmp_path / "backend/tests/test_main.py").write_text(
        "def test_dashboard(): assert True\n",
        encoding="utf-8",
    )
    spec = resolve_project_spec(
        "Build a React website with login and an admin-only dashboard",
        {"capability_id": "react-fastapi"},
    )

    result = validate_with_adapters(tmp_path, spec)

    assert {finding.code for finding in result.blocking_findings} == {
        "server_authorization_unproven",
        "authorization_tests_missing",
    }


def test_auth_adapter_recognizes_standard_pytest_test_module(tmp_path) -> None:
    (tmp_path / "backend/src").mkdir(parents=True)
    (tmp_path / "backend/tests").mkdir(parents=True)
    (tmp_path / "backend/src/main.py").write_text(
        (
            "def require_admin(authorization: str):\n"
            "    if not authorization.startswith('Bearer '):\n"
            "        raise HTTPException(status_code=401, detail='Unauthorized')\n"
            "    raise HTTPException(status_code=403, detail='Forbidden')\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "backend/tests/test_main.py").write_text(
        (
            "def test_wrong_role_is_forbidden(client):\n"
            "    response = client.get('/admin', headers={'Authorization': 'Bearer member'})\n"
            "    assert response.status_code == 403\n"
        ),
        encoding="utf-8",
    )
    spec = resolve_project_spec(
        "Build a React website with login and an admin-only dashboard",
        {"capability_id": "react-fastapi"},
    )

    result = validate_with_adapters(tmp_path, spec)

    assert result.blocking_findings == []


def test_auth_adapter_recognizes_shared_fastapi_error_helper(tmp_path) -> None:
    (tmp_path / "backend/app").mkdir(parents=True)
    (tmp_path / "backend/tests").mkdir(parents=True)
    (tmp_path / "backend/app/main.py").write_text(
        (
            "def current_user(authorization):\n"
            "    if not authorization.startswith('Bearer '):\n"
            "        raise api_error(401, 'authentication_required', 'Bearer required')\n"
            "    return jwt.decode(authorization[7:], 'secret', algorithms=['HS256'])\n"
            "def require_curator(user):\n"
            "    if user.role != 'curator':\n"
            "        raise api_error(403, 'curator_required', 'Curator required')\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "backend/tests/test_api.py").write_text(
        (
            "def test_anonymous_and_wrong_role_are_rejected(client):\n"
            "    assert client.get('/films').status_code == 401\n"
            "    assert client.post('/films', headers={'Authorization': 'Bearer member'}).status_code == 403\n"
        ),
        encoding="utf-8",
    )
    spec = resolve_project_spec(
        "Build a video platform with sign in and member and curator roles",
        {"capability_id": "react-fastapi"},
    )

    result = validate_with_adapters(tmp_path, spec)

    assert "server_authorization_unproven" not in {
        finding.code for finding in result.blocking_findings
    }


def test_auth_adapter_recognizes_status_as_last_error_helper_argument(tmp_path) -> None:
    (tmp_path / "backend/app").mkdir(parents=True)
    (tmp_path / "backend/tests").mkdir(parents=True)
    (tmp_path / "backend/app/main.py").write_text(
        (
            "def current_user(authorization):\n"
            "    if not authorization.startswith('Bearer '):\n"
            "        raise api_error('authentication_required', 'Bearer required', 401)\n"
            "    return jwt.decode(authorization[7:], 'secret', algorithms=['HS256'])\n"
            "def require_admin(user):\n"
            "    if user.role != 'admin':\n"
            "        raise api_error('admin_required', 'Admin required', 403)\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "backend/tests/test_api.py").write_text(
        (
            "def test_auth_and_role_rejections(client):\n"
            "    assert client.get('/admin').status_code == 401\n"
            "    assert client.get('/admin', headers={'Authorization': 'Bearer member'}).status_code == 403\n"
        ),
        encoding="utf-8",
    )
    spec = resolve_project_spec(
        "Build a wallet commerce app with login and an admin-only dashboard",
        {"capability_id": "react-fastapi"},
    )

    result = validate_with_adapters(tmp_path, spec)

    assert "server_authorization_unproven" not in {
        finding.code for finding in result.blocking_findings
    }


def test_auth_adapter_recognizes_domain_error_helper(tmp_path) -> None:
    (tmp_path / "backend/app").mkdir(parents=True)
    (tmp_path / "backend/tests").mkdir(parents=True)
    (tmp_path / "backend/app/main.py").write_text(
        (
            "def current_user(authorization):\n"
            "    if not authorization.startswith('Bearer '):\n"
            "        raise detail_error(401, 'authentication required')\n"
            "    return jwt.decode(authorization[7:], 'secret', algorithms=['HS256'])\n"
            "def require_admin(user):\n"
            "    if user.role != 'admin':\n"
            "        raise detail_error(403, 'admin role required')\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "backend/tests/test_api.py").write_text(
        (
            "def test_auth_and_role_rejections(client):\n"
            "    assert client.get('/admin').status_code == 401\n"
            "    assert client.get('/admin', headers={'Authorization': 'Bearer member'}).status_code == 403\n"
        ),
        encoding="utf-8",
    )
    spec = resolve_project_spec(
        "Build a wallet commerce app with login and an admin-only dashboard",
        {"capability_id": "react-fastapi"},
    )

    result = validate_with_adapters(tmp_path, spec)

    assert "server_authorization_unproven" not in {
        finding.code for finding in result.blocking_findings
    }


def test_commerce_adapter_recognizes_integer_minor_unit_fields(tmp_path) -> None:
    (tmp_path / "backend/app").mkdir(parents=True)
    (tmp_path / "backend/tests").mkdir(parents=True)
    (tmp_path / "backend/app/models.py").write_text(
        (
            "class Product:\n"
            "    price_minor: int\n"
            "class User:\n"
            "    wallet_balance_minor: int\n"
            "class Transaction:\n"
            "    amount_minor: int\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "backend/tests/test_checkout.py").write_text(
        "def test_duplicate_and_insufficient_balance(): assert True\n",
        encoding="utf-8",
    )
    spec = resolve_project_spec(
        "Build a shopping cart with checkout payments and transaction history",
        {"capability_id": "react-fastapi"},
    )

    result = validate_with_adapters(tmp_path, spec)

    assert "exact_money_missing" not in {
        finding.code for finding in result.blocking_findings
    }


def test_commerce_adapter_requires_duplicate_and_conflict_tests(tmp_path) -> None:
    (tmp_path / "backend/app").mkdir(parents=True)
    (tmp_path / "backend/tests").mkdir(parents=True)
    (tmp_path / "backend/app/models.py").write_text(
        "class Product:\n    price_minor: int\n",
        encoding="utf-8",
    )
    (tmp_path / "backend/tests/test_checkout.py").write_text(
        "def test_balance_is_recorded(): assert True\n",
        encoding="utf-8",
    )
    spec = resolve_project_spec(
        "Build a shopping cart with checkout payments and transaction history",
        {"capability_id": "react-fastapi"},
    )

    result = validate_with_adapters(tmp_path, spec)

    assert "transaction_edge_tests_missing" in {
        finding.code for finding in result.blocking_findings
    }


def test_auth_adapter_recognizes_custom_api_error_exception(tmp_path) -> None:
    (tmp_path / "backend/app").mkdir(parents=True)
    (tmp_path / "backend/tests").mkdir(parents=True)
    (tmp_path / "backend/app/main.py").write_text(
        (
            "def require_user(authorization):\n"
            "    if not authorization.startswith('Bearer '):\n"
            "        raise ApiError(401, 'unauthenticated', 'Bearer required')\n"
            "    return jwt.decode(authorization[7:], 'secret', algorithms=['HS256'])\n"
            "def require_curator(user):\n"
            "    if user.role != 'curator':\n"
            "        raise ApiError(403, 'forbidden', 'Curator required')\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "backend/tests/test_api.py").write_text(
        (
            "def test_auth_and_role_rejections(client):\n"
            "    assert client.get('/films').status_code == 401\n"
            "    assert client.post('/films', headers={'Authorization': 'Bearer member'}).status_code == 403\n"
        ),
        encoding="utf-8",
    )
    spec = resolve_project_spec(
        "Build a video platform with sign in and member and curator roles",
        {"capability_id": "react-fastapi"},
    )

    result = validate_with_adapters(tmp_path, spec)

    assert "server_authorization_unproven" not in {
        finding.code for finding in result.blocking_findings
    }


def test_auth_adapter_recognizes_fastapi_status_constants(tmp_path) -> None:
    (tmp_path / "backend/app").mkdir(parents=True)
    (tmp_path / "backend/tests").mkdir(parents=True)
    (tmp_path / "backend/app/security.py").write_text(
        (
            "def current_user(credentials):\n"
            "    if credentials is None:\n"
            "        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Authentication required')\n"
            "    return jwt.decode(credentials.credentials, 'secret', algorithms=['HS256'])\n"
            "def require_curator(user):\n"
            "    if user.role != 'curator':\n"
            "        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Curator required')\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "backend/tests/test_api.py").write_text(
        (
            "def test_auth_rejection(client):\n"
            "    assert client.get('/films').status_code == 401\n"
        ),
        encoding="utf-8",
    )
    spec = resolve_project_spec(
        "Build a video platform with sign in and member and curator roles",
        {"capability_id": "react-fastapi"},
    )

    result = validate_with_adapters(tmp_path, spec)

    assert "server_authorization_unproven" not in {
        finding.code for finding in result.blocking_findings
    }


def test_video_adapter_requires_real_playback_surface(tmp_path) -> None:
    source = tmp_path / "frontend/src"
    source.mkdir(parents=True)
    (source / "App.tsx").write_text(
        "export function App() { return <main>Movie catalog</main>; }\n",
        encoding="utf-8",
    )
    spec = resolve_project_spec(
        "Build a React video platform",
        {"capability_id": "react-vite"},
    )

    result = validate_with_adapters(tmp_path, spec)

    assert "playback_surface_missing" in {finding.code for finding in result.blocking_findings}


def test_persistence_adapter_requires_migration_and_runtime_connection(tmp_path) -> None:
    (tmp_path / "backend/src").mkdir(parents=True)
    (tmp_path / "backend/src/main.py").write_text(
        "def health(): return {'ok': True}\n",
        encoding="utf-8",
    )
    spec = resolve_project_spec(
        "Build a React and FastAPI app with a Supabase database",
        {"capability_id": "react-fastapi"},
    )

    result = validate_with_adapters(tmp_path, spec)

    assert {finding.code for finding in result.blocking_findings} == {
        "migration_missing",
        "runtime_persistence_missing",
    }


def test_commerce_adapter_accepts_typed_integer_money_fields(tmp_path) -> None:
    (tmp_path / "backend/src").mkdir(parents=True)
    (tmp_path / "backend/tests").mkdir(parents=True)
    (tmp_path / "backend/src/main.py").write_text(
        "class Wallet:\n    wallet_balance: int\n    price: int\n",
        encoding="utf-8",
    )
    (tmp_path / "backend/tests/test_checkout.py").write_text(
        "def test_insufficient_balance():\n    assert 'insufficient' != 'duplicate'\n",
        encoding="utf-8",
    )
    spec = resolve_project_spec(
        "Build a FastAPI shopping cart with a wallet and checkout",
        {"capability_id": "fastapi-api"},
    )

    result = validate_with_adapters(tmp_path, spec)

    assert "exact_money_missing" not in {finding.code for finding in result.blocking_findings}


def test_commerce_adapter_rejects_floating_point_money_fields(tmp_path) -> None:
    (tmp_path / "backend/src").mkdir(parents=True)
    (tmp_path / "backend/src/main.py").write_text(
        "class Wallet:\n    wallet_balance: float\n    price: float\n",
        encoding="utf-8",
    )
    spec = resolve_project_spec(
        "Build a FastAPI shopping cart with a wallet and checkout",
        {"capability_id": "fastapi-api"},
    )

    result = validate_with_adapters(tmp_path, spec)

    assert "exact_money_missing" in {finding.code for finding in result.blocking_findings}


def test_file_upload_adapter_rejects_frontend_limit_above_backend(tmp_path) -> None:
    (tmp_path / "backend/app").mkdir(parents=True)
    (tmp_path / "frontend/src").mkdir(parents=True)
    (tmp_path / "backend/app/main.py").write_text(
        (
            "MAX_UPLOAD_BYTES = int(os.getenv('MAX_UPLOAD_BYTES', '104857600'))\n"
            "async def upload(file: UploadFile):\n"
            "    if file.content_type != 'video/mp4': raise ValueError\n"
            "    if file_size > MAX_UPLOAD_BYTES: raise ValueError\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "frontend/src/App.tsx").write_text(
        (
            "const MAX_BYTES = 500 * 1024 * 1024;\n"
            "const body = new FormData();\n"
            "if (file.size > MAX_BYTES) throw new Error('too large');\n"
        ),
        encoding="utf-8",
    )
    spec = resolve_project_spec(
        "Build a React and FastAPI video upload platform",
        {"capability_id": "react-fastapi"},
    )

    result = validate_with_adapters(tmp_path, spec)

    assert "upload_limit_mismatch" in {
        finding.code for finding in result.blocking_findings
    }


def test_file_upload_adapter_accepts_frontend_limit_at_backend_limit(tmp_path) -> None:
    (tmp_path / "backend/app").mkdir(parents=True)
    (tmp_path / "frontend/src").mkdir(parents=True)
    (tmp_path / "backend/app/main.py").write_text(
        (
            "MAX_UPLOAD_BYTES = int(os.getenv('MAX_UPLOAD_BYTES', '104857600'))\n"
            "async def upload(file: UploadFile):\n"
            "    if file.content_type != 'video/mp4': raise ValueError\n"
            "    if file_size > MAX_UPLOAD_BYTES: raise ValueError\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "frontend/src/App.tsx").write_text(
        (
            "const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;\n"
            "const body = new FormData();\n"
            "if (file.size > MAX_UPLOAD_BYTES) throw new Error('too large');\n"
        ),
        encoding="utf-8",
    )
    spec = resolve_project_spec(
        "Build a React and FastAPI video upload platform",
        {"capability_id": "react-fastapi"},
    )

    result = validate_with_adapters(tmp_path, spec)

    assert "upload_limit_mismatch" not in {
        finding.code for finding in result.blocking_findings
    }


def test_registry_peer_resolution_crash_is_infrastructure_not_worker_defect() -> None:
    """npm arborist aborts with a null peer node when registry metadata is unreachable."""

    crash = "npm error Cannot read properties of null (reading 'edgesOut')"

    assert _looks_like_infrastructure_failure("", crash)
    assert _looks_like_infrastructure_failure(crash, "")
    assert _looks_like_infrastructure_failure(
        "", "npm error request to https://registry.npmjs.org/react failed"
    )
    assert not _looks_like_infrastructure_failure("", "TypeError: Cannot read properties of null")


def test_lockfile_generation_falls_back_when_npm_peer_resolver_crashes(
    tmp_path, monkeypatch
) -> None:
    """An npm arborist crash must retry with the escape hatch, not fail a worker."""

    attempts: list[list[str]] = []

    def fake_run(command, **kwargs):
        attempts.append(list(command))
        if "--legacy-peer-deps" in command:
            return SimpleNamespace(returncode=0, stdout="added 86 packages", stderr="")
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="npm error Cannot read properties of null (reading 'edgesOut')",
        )

    monkeypatch.setattr(
        "software_developer_agent.artifacts.validation.subprocess.run", fake_run
    )
    validator = ProjectValidator(Settings(app_env="development"))
    report = ProjectValidationReport(passed=True)

    generated = validator._generate_lockfile(
        report,
        component="frontend",
        worker_kind=WorkerKind.FRONTEND,
        command=["npm", "install", "--package-lock-only"],
        cwd=tmp_path,
    )

    assert generated is True
    assert report.passed is True
    assert report.retry_targets == []
    assert "frontend_lockfile_generation:peer_resolver_fallback" in report.checks
    assert attempts[-1][-1] == "--legacy-peer-deps"


def test_lockfile_generation_does_not_fall_back_on_a_real_conflict(tmp_path, monkeypatch) -> None:
    """A genuine peer conflict must still fail so the worker can correct it."""

    monkeypatch.setattr(
        "software_developer_agent.artifacts.validation.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="npm error ERESOLVE unable to resolve dependency tree"
        ),
    )
    validator = ProjectValidator(Settings(app_env="development"))
    report = ProjectValidationReport(passed=True)

    generated = validator._generate_lockfile(
        report,
        component="frontend",
        worker_kind=WorkerKind.FRONTEND,
        command=["npm", "install", "--package-lock-only"],
        cwd=tmp_path,
    )

    assert generated is False
    assert report.passed is False
    assert WorkerKind.FRONTEND in report.retry_targets


def test_build_outputs_are_removed_even_when_validation_raises(tmp_path) -> None:
    """node_modules and dist must never reach the published folder or ZIP."""

    for component in ("frontend", "backend"):
        (tmp_path / component / "node_modules" / "left-pad").mkdir(parents=True)
        (tmp_path / component / "node_modules" / "left-pad" / "index.js").write_text(
            "module.exports = 1;", encoding="utf-8"
        )
        (tmp_path / component / "dist").mkdir(parents=True)
        (tmp_path / component / "dist" / "bundle.js").write_text("1;", encoding="utf-8")

    class ExplodingValidator(ProjectValidator):
        def _validate_project(self, root, job):
            raise ValueError("Unable to locate backend application entry point.")

    validator = ExplodingValidator(Settings(app_env="development", enable_persistence=False))
    job = JobState(request=JobRequest(prompt="Build a React and Node app"))

    try:
        validator.validate(tmp_path, job)
    except ValueError:
        pass

    survivors = [path.as_posix() for path in tmp_path.rglob("*") if path.is_file()]
    assert not any("node_modules" in path for path in survivors)
    assert not any("/dist/" in path for path in survivors)


def test_node_backend_skips_the_python_contract_workflow(tmp_path) -> None:
    """A Node backend has no importable Python module; its own tests cover the contract."""

    for component in ("frontend", "backend"):
        (tmp_path / component).mkdir()
    (tmp_path / "backend" / "package.json").write_text('{"name":"api"}', encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "Backend: http://127.0.0.1:8000\nFrontend: http://127.0.0.1:5173\n", encoding="utf-8"
    )
    validator = ProjectValidator(Settings(app_env="development", enable_persistence=False))
    report = ProjectValidationReport(passed=True)

    validator._validate_contract(
        tmp_path,
        tmp_path / "tmp",
        {
            "backend_port": 8000,
            "frontend_port": 5173,
            "routes": [
                {"method": "GET", "path": "/health", "success_status": 200}
            ],
        },
        report,
    )

    assert report.passed
    assert "backend_contract_workflow:covered_by_node_tests" in report.checks


def test_contract_validation_reports_all_missing_frontend_routes(tmp_path) -> None:
    for component in ("frontend", "backend"):
        (tmp_path / component).mkdir()
    (tmp_path / "frontend" / "src").mkdir()
    (tmp_path / "frontend" / "src" / "App.tsx").write_text(
        "export function App() { return <main />; }\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "Backend: http://127.0.0.1:8000\nFrontend: http://127.0.0.1:5173\n",
        encoding="utf-8",
    )
    report = ProjectValidationReport(passed=True)

    ProjectValidator(
        Settings(app_env="test", enable_persistence=False)
    )._validate_contract(
        tmp_path,
        None,
        {
            "backend_port": 8000,
            "frontend_port": 5173,
            "routes": [
                {"method": "GET", "path": "/api/auth/me"},
                {"method": "GET", "path": "/api/movies/{movie_id}"},
            ],
        },
        report,
    )

    assert not report.passed
    assert "/api/auth/me" in (report.failure_reason or "")
    assert "/api/movies/{movie_id}" in (report.failure_reason or "")


def test_contract_accepts_backend_supplied_hypermedia_route(tmp_path) -> None:
    for component in ("frontend", "backend"):
        (tmp_path / component).mkdir()
    (tmp_path / "frontend" / "src").mkdir()
    (tmp_path / "frontend" / "src" / "App.tsx").write_text(
        "fetch('/api/movies');\nconst items = [];\n"
        "export const Player = ({ movie }) => <video src={movie.stream_url} />;\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "Backend: http://127.0.0.1:8000\nFrontend: http://127.0.0.1:5173\n",
        encoding="utf-8",
    )
    report = ProjectValidationReport(passed=True)

    ProjectValidator(
        Settings(app_env="test", enable_persistence=False)
    )._validate_contract(
        tmp_path,
        None,
        {
            "backend_port": 8000,
            "frontend_port": 5173,
            "routes": [
                {
                    "method": "GET",
                    "path": "/api/movies",
                    "response_example": {
                        "items": [
                            {
                                "id": "uuid",
                                "stream_url": "/api/movies/uuid/stream",
                            }
                        ]
                    },
                },
                {
                    "method": "GET",
                    "path": "/api/movies/{movie_id}/stream",
                    "response_example": "binary video bytes",
                },
            ],
        },
        report,
    )

    assert report.passed
    assert "frontend_contract_reference" in report.checks


def test_contract_rejects_unconsumed_backend_supplied_hypermedia_route(tmp_path) -> None:
    for component in ("frontend", "backend"):
        (tmp_path / component).mkdir()
    (tmp_path / "frontend" / "src").mkdir()
    (tmp_path / "frontend" / "src" / "App.tsx").write_text(
        "fetch('/api/movies');\nconst items = [];\n"
        "export const Player = () => <video />;\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "Backend: http://127.0.0.1:8000\nFrontend: http://127.0.0.1:5173\n",
        encoding="utf-8",
    )
    report = ProjectValidationReport(passed=True)

    ProjectValidator(
        Settings(app_env="test", enable_persistence=False)
    )._validate_contract(
        tmp_path,
        None,
        {
            "backend_port": 8000,
            "frontend_port": 5173,
            "routes": [
                {
                    "method": "GET",
                    "path": "/api/movies",
                    "response_example": {
                        "items": [
                            {"stream_url": "/api/movies/uuid/stream"}
                        ]
                    },
                },
                {
                    "method": "GET",
                    "path": "/api/movies/{movie_id}/stream",
                },
            ],
        },
        report,
    )

    assert not report.passed
    assert "/api/movies/{movie_id}/stream" in (report.failure_reason or "")
