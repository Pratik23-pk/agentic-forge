import json
import os
from pathlib import Path

import pytest

from software_developer_agent.agents.workers.base import DeveloperWorker
from software_developer_agent.artifacts.file_manifest import extract_worker_file_manifest
from software_developer_agent.artifacts.project_generator import ProjectArtifactGenerator
from software_developer_agent.capabilities.registry import resolve_project_spec
from software_developer_agent.config.settings import Settings
from software_developer_agent.memory.manifest_checkpoint import ManifestCheckpointManager
from software_developer_agent.models.job_state import (
    JobRequest,
    JobState,
    JobTask,
    TaskStatus,
    WorkerKind,
)
from software_developer_agent.sandbox.preview_manager import PreviewManager

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DOCKER_REGRESSION") != "1",
    reason="Opt-in regression requires Docker, registry access, and Playwright Chromium.",
)

HERITAGE_FILES = {
    "frontend/index.html": (
        '<!doctype html><html lang="en"><head><title>Heritage Gallery</title></head>'
        '<body><div id="root"></div><script type="module" src="/src/main.tsx"></script>'
        "</body></html>"
    ),
    "frontend/src/main.tsx": (
        "import { createRoot } from 'react-dom/client';\n"
        "import App from './App';\n"
        "createRoot(document.getElementById('root')!).render(<App />);\n"
    ),
    "frontend/src/App.tsx": """
import { useState } from 'react';
const places = [{ name: 'Taj Mahal', description: 'A marble monument in Agra.' }];
export default function App() {
  const [expanded, setExpanded] = useState(false);
  return <main>
    <h1>India Heritage Gallery</h1>
    {places.map(place => <article key={place.name}>
      <h3>{place.name}</h3>
      <img src="/heritage.svg" alt={place.name} width="400" height="240" />
      <button onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>Explore</button>
      {expanded && <p>{place.description}</p>}
    </article>)}
  </main>;
}
""",
    "frontend/src/App.test.tsx": """
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import App from './App';
describe('heritage gallery', () => {
  it('renders dynamic headings, local images, and an interactive description', () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: /Taj Mahal/i })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Taj Mahal' })).toHaveAttribute('src', '/heritage.svg');
    fireEvent.click(screen.getByRole('button', { name: 'Explore' }));
    expect(screen.getByText('A marble monument in Agra.')).toBeVisible();
  });
});
""",
    "frontend/src/test/setup.ts": "import '@testing-library/jest-dom/vitest';\n",
    "frontend/public/heritage.svg": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 240">'
        '<rect width="400" height="240" fill="#bde0fa"/>'
        '<path d="M130 200V130H270V200ZM150 130Q200 20 250 130Z" fill="#fff"/>'
        '<path d="M75 200V95H95V200ZM305 200V95H325V200Z" fill="#fff"/>'
        '<path d="M182 200V167Q200 145 218 167V200Z" fill="#254665"/></svg>'
    ),
}


class _HeritageWorker(DeveloperWorker):
    worker_kind = WorkerKind.FRONTEND

    def execute(self, task: JobTask, tool_context: str = "") -> str:
        return json.dumps(
            {
                "summary": "Heritage regression fixture with intentionally missing runtime contracts.",
                "operation": "replace",
                "files": [
                    {"path": path, "content": content} for path, content in HERITAGE_FILES.items()
                ],
            }
        )


def test_missing_contracts_dynamic_jsx_and_preview_work_without_retry(tmp_path: Path) -> None:
    from playwright.sync_api import expect, sync_playwright

    settings = Settings(
        _env_file=None,
        app_env="development",
        enable_persistence=False,
        enable_llm_calls=False,
        enable_human_checkpoints=False,
        langsmith_tracing=False,
        enable_artifact_validation=True,
        artifact_validation_sandbox_mode="docker",
        enable_live_preview=True,
        preview_sandbox_mode="docker",
        generated_projects_dir=tmp_path / "generated",
        artifacts_dir=tmp_path / "artifacts",
        preview_cache_dir=tmp_path / "previews",
        preview_startup_timeout_seconds=90,
    )
    prompt = "Build a one-page React heritage gallery without database or deployment."
    spec = resolve_project_spec(prompt, {"capability_id": "react-vite"})
    task = JobTask(
        worker_kind=WorkerKind.FRONTEND,
        title="Heritage",
        instructions=prompt,
        capability_id=spec.capability_id,
        adapter_ids=spec.adapter_ids,
        max_attempts=4,
    )
    job = JobState(
        request=JobRequest(prompt=prompt, project_id="heritage-runtime-regression"),
        tasks=[task],
        project_spec=spec.to_dict(),
    )
    result = _HeritageWorker(settings=settings).run(task)
    assert result.status == TaskStatus.SUCCEEDED, result.errors
    assert result.attempt == 1
    assert task.transport_attempts == 1
    manifest = extract_worker_file_manifest(result.output, WorkerKind.FRONTEND)
    task.attempt = result.attempt
    ManifestCheckpointManager(settings).commit(job, task, manifest)
    job.add_worker_result(result)

    artifacts = ProjectArtifactGenerator(settings).generate(job)
    folder = next(artifact for artifact in artifacts if artifact.kind == "folder")
    validation = folder.metadata["validation"]
    assert validation["passed"], json.dumps(validation, indent=2)
    assert "docker_sandbox:passed" in validation["checks"]
    assert any(
        finding["code"] == "dynamic_heading_requires_runtime_verification"
        for finding in validation["advisories"]
    )
    assert (Path(folder.path) / "frontend/src/App.tsx").read_text() == HERITAGE_FILES[
        "frontend/src/App.tsx"
    ]
    manager = PreviewManager(settings)
    try:
        preview = manager.start(job, Path(folder.path))
        assert preview.status == "running"
        assert {check.name for check in preview.checks} == {"http_smoke", "browser_smoke"}
        assert all(check.passed for check in preview.checks), [
            check.to_dict() for check in preview.checks
        ]
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(preview.services[0].url)
            expect(page.get_by_role("heading", name="Taj Mahal")).to_be_visible()
            photo = page.get_by_role("img", name="Taj Mahal")
            expect(photo).to_be_visible()
            page.wait_for_function("document.querySelector('img').naturalWidth > 0")
            page.get_by_role("button", name="Explore").click()
            expect(page.get_by_text("A marble monument in Agra.")).to_be_visible()
            browser.close()
    finally:
        manager.stop_all()
    assert task.attempt == 1
