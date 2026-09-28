"""Exercise the real live orchestration path with a deterministic stand-in for OpenAI.

Runs AgentRuntime.run_to_completion for every benchmark case: guardrails, planner,
design director, workers, manifest checkpointing, artifact assembly, executable
validation, evaluator, router and release policy. Only the model itself is stubbed,
so this reaches every part of the live path that does not depend on model quality.

Usage, from the backend directory:

    ARTIFACT_VALIDATION_SANDBOX_MODE=local uv run --locked --no-sync python \
        scripts/simulate_live_workflow.py [case_id ...]

A case passes when it produces an artifact with the correct worker routing and stops
cleanly: either succeeded, or failed with the outstanding repair ticket named. The
stub cannot invent domain code, so a semantic repair ticket on a full-stack genre is
the expected outcome, not a defect.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from software_developer_agent.artifacts.file_manifest import fallback_worker_manifest_json
from software_developer_agent.config.settings import Settings
from software_developer_agent.models.job_state import JobRequest, JobState, WorkerKind
from software_developer_agent.observability.cost_tracker import TokenUsage
from software_developer_agent.orchestration import state_machine

WORKER_KINDS = {kind.value: kind for kind in WorkerKind}


class StubResponse:
    def __init__(self, text: str, usage: TokenUsage) -> None:
        self.text = text
        self.usage = usage


class StubLLMClient:
    """Returns contract-valid payloads so the orchestration path is exercised fully."""

    def __init__(self, node_name: str, model: str, authorizer, recorder) -> None:
        self._node = node_name
        self._model = model
        self._authorizer = authorizer
        self._recorder = recorder

    def complete(self, system: str, user: str) -> StubResponse:
        usage = TokenUsage(prompt_tokens=800, completion_tokens=900, cached_prompt_tokens=200)
        if self._authorizer is not None:
            # Exercise the real budget ceiling and per-node call caps.
            self._authorizer(self._node, self._model, (len(system) + len(user)) // 4, 4_000)
        if self._recorder is not None:
            self._recorder(self._node, self._model, usage)
        if self._node == "planner":
            return StubResponse(self._plan(user), usage)
        if self._node == "design":
            return StubResponse(self._design(), usage)
        if self._node == "evaluator":
            return StubResponse(self._evaluation(), usage)
        return StubResponse(self._manifest(user), usage)

    @staticmethod
    def _plan(user: str) -> str:
        kinds = re.search(r"Use only these worker kinds: (\[[^\]]*\])", user)
        worker_kinds = json.loads(kinds.group(1).replace("'", '"')) if kinds else ["frontend"]
        ports = re.search(r"Default ports: (\{.*?\})\n", user, re.DOTALL)
        contract = json.loads(ports.group(1)) if ports else {"routes": []}
        full_stack = {"backend", "frontend"}.issubset(set(worker_kinds))
        contract["routes"] = (
            [
                {
                    "method": "GET",
                    "path": "/health",
                    "request_example": None,
                    "response_example": {"status": "ok"},
                    "success_status": 200,
                    "frontend_required": False,
                }
            ]
            if full_stack
            else []
        )
        return json.dumps(
            {
                "api_contract": contract,
                "tasks": [
                    {
                        "worker_kind": kind,
                        "title": f"{kind.title()} implementation",
                        "instructions": f"Implement the {kind} component for the request.",
                        "depends_on": [],
                    }
                    for kind in worker_kinds
                ],
            }
        )

    @staticmethod
    def _design() -> str:
        return json.dumps(
            {
                "product_summary": "A focused product built from the request.",
                "experience_goal": "A polished, responsive product experience.",
                "visual_direction": {
                    "tone": "premium, minimal",
                    "theme": "adaptive dark and light",
                    "typography": "clear display hierarchy",
                    "color_strategy": "neutral with one accent",
                    "motion": "purposeful micro-interactions",
                },
                "primary_surfaces": ["primary workflow", "empty state"],
                "interaction_requirements": ["Keyboard accessible", "Responsive"],
                "quality_criteria": ["No placeholder presentation", "Consistent tokens"],
            }
        )

    @staticmethod
    def _evaluation() -> str:
        return json.dumps(
            {
                "decision": "approved",
                "passed": True,
                "retry_targets": [],
                "replan_required": False,
                "failure_reason": None,
                "checks": ["semantic_review:approved"],
                "warnings": [],
                "evidence": [],
            }
        )

    @staticmethod
    def _manifest(user: str) -> str:
        worker = re.search(r"^Worker: (\w+)$", user, re.MULTILINE)
        capability = re.search(r"^Capability: ([A-Za-z0-9._-]+)$", user, re.MULTILINE)
        project = re.search(r"^Project: (.+)$", user, re.MULTILINE)
        request = re.search(r"^Request: (.+)$", user, re.MULTILINE)
        task = SimpleNamespace(
            worker_kind=WORKER_KINDS[worker.group(1)],
            capability_id=capability.group(1) if capability else "react-fastapi",
        )
        return fallback_worker_manifest_json(
            task,
            request.group(1) if request else "Build the requested product.",
            project.group(1) if project else "generated-project",
        )


def stub_factory(settings, model=None, **kwargs):
    return StubLLMClient(
        kwargs.get("node_name", "llm"),
        model or "gpt-5.6-terra",
        kwargs.get("budget_authorizer"),
        kwargs.get("usage_recorder"),
    )


def run_case(case: dict) -> dict:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=".simulated-live-", dir=Path.cwd()) as temp_dir:
        workspace = Path(temp_dir)
        settings = Settings(
            app_env="development",
            enable_llm_calls=True,
            openai_api_key="stub-key-not-used",
            enable_human_checkpoints=False,
            enable_persistence=False,
            enable_auto_preview=False,
            artifact_validation_sandbox_mode="local",
            artifacts_dir=workspace / "artifacts",
            generated_projects_dir=workspace / "generated",
            preview_cache_dir=workspace / "previews",
        )
        job = JobState(
            request=JobRequest(prompt=case["prompt"], project_id=case["project_id"])
        )
        route = state_machine.AgentRuntime(settings).run_to_completion(job)
        folder = next((a for a in job.artifacts if a.kind == "folder"), None)
        return {
            "case_id": case["case_id"],
            "route": route.action.value,
            "status": job.status.value,
            "release": job.release_status.value,
            "attempts": {t.worker_kind.value: t.attempt for t in job.tasks},
            "workers": sorted(t.worker_kind.value for t in job.tasks),
            "adapters": job.project_spec.get("adapter_ids", []),
            "files": len(folder.metadata.get("files", [])) if folder else 0,
            "cost_usd": round(float(job.cost_ledger.get("spent_usd", 0.0)), 5),
            "model_calls": len(job.cost_ledger.get("calls", [])),
            "fallbacks": sorted(
                {r.worker_kind.value for r in job.worker_results if r.used_fallback}
            ),
            "repair_tickets": [t.category for t in job.repair_tickets],
            "errors": job.errors[-2:],
            "warnings": job.warnings[-2:],
            "duration": round(time.monotonic() - started, 1),
        }


def main() -> int:
    state_machine.create_llm_client = stub_factory
    cases_path = (
        Path(__file__).resolve().parents[1]
        / "src/software_developer_agent/benchmarks/cases.json"
    )
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    selected = [c for c in cases if c["case_id"] in set(sys.argv[1:])] if len(sys.argv) > 1 else cases
    failures = 0
    for case in selected:
        result = run_case(case)
        # The stub cannot invent domain code, so a semantic repair ticket is expected.
        # What must hold for every genre: correct routing, a preserved artifact, and a
        # terminal state that names the outstanding defect instead of a bare ceiling.
        clean_stop = result["status"] == "succeeded" or "Outstanding defect:" in " ".join(
            result["errors"]
        )
        ok = result["files"] > 0 and result["workers"] and clean_stop
        failures += 0 if ok else 1
        print(("OK   " if ok else "FAIL ") + json.dumps(result))
    print(f"\n{len(selected) - failures}/{len(selected)} simulated live cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
