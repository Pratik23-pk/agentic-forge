import os
from pathlib import Path

import pytest

from software_developer_agent.capabilities.registry import resolve_project_spec
from software_developer_agent.config.settings import Settings
from software_developer_agent.models.job_state import JobRequest, JobState, ReleaseStatus
from software_developer_agent.sandbox.preview_manager import PreviewManager

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DOCKER_REGRESSION") != "1",
    reason="Opt-in regression requires Docker, registry access, and Playwright Chromium.",
)


def test_preview_gateway_connects_dynamic_frontend_and_backend_ports(tmp_path: Path) -> None:
    from playwright.sync_api import expect, sync_playwright

    project = tmp_path / "generated" / "connectivity"
    backend = project / "backend"
    frontend = project / "frontend"
    (backend / "app").mkdir(parents=True)
    (frontend / "src").mkdir(parents=True)
    (backend / "requirements.txt").write_text(
        "fastapi==0.115.6\nuvicorn==0.34.0\n",
        encoding="utf-8",
    )
    (backend / "app" / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/api/pieces')\n"
        "def pieces(): return {'pieces': ['white-king', 'black-king']}\n",
        encoding="utf-8",
    )
    (frontend / "package.json").write_text(
        '{"scripts":{"dev":"vite"},"dependencies":{"@vitejs/plugin-react":"4.3.4",'
        '"vite":"6.0.7","typescript":"5.7.3","react":"19.0.0",'
        '"react-dom":"19.0.0"},"devDependencies":{}}',
        encoding="utf-8",
    )
    (frontend / "index.html").write_text(
        '<div id="root"></div><script type="module" src="/src/main.tsx"></script>',
        encoding="utf-8",
    )
    (frontend / "src" / "main.tsx").write_text(
        "import React from 'react';\n"
        "import { createRoot } from 'react-dom/client';\n"
        "const base = import.meta.env.VITE_API_BASE_URL ?? '';\n"
        "function App(){ const [pieces,setPieces]=React.useState<string[]>([]);"
        "React.useEffect(()=>{void fetch(`${base}/api/pieces`).then(r=>r.json()).then(d=>setPieces(d.pieces));},[]);"
        "return <h1>{pieces.length === 2 ? 'Playable board ready' : 'Loading board'}</h1> }\n"
        "createRoot(document.getElementById('root')!).render(<App/>);\n",
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        app_env="development",
        preview_sandbox_mode="docker",
        generated_projects_dir=tmp_path / "generated",
        preview_cache_dir=tmp_path / "previews",
        preview_startup_timeout_seconds=90,
    )
    spec = resolve_project_spec("Build a React and FastAPI chess application")
    job = JobState(
        request=JobRequest(prompt="Build a React and FastAPI chess application"),
        project_spec=spec.to_dict(),
        release_status=ReleaseStatus.VERIFIED,
    )
    manager = PreviewManager(settings)
    try:
        preview = manager.start(job, project)
        assert preview.status == "running"
        assert all(check.passed for check in preview.checks), [
            check.to_dict() for check in preview.checks
        ]
        assert job.release_status == ReleaseStatus.VERIFIED
        frontend_url = next(
            service.url for service in preview.services if service.name == "frontend"
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(frontend_url)
            expect(page.get_by_role("heading", name="Playable board ready")).to_be_visible()
            browser.close()
    finally:
        manager.stop_all()
