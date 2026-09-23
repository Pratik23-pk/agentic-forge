# ruff: noqa: I001

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any


CONTROL_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = CONTROL_ROOT.parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
STATE_PATH = CONTROL_ROOT / "state.json"
RESULTS_ROOT = CONTROL_ROOT / "results"
LOG_PATH = CONTROL_ROOT / "campaign.log"
CASES_PATH = CONTROL_ROOT / "cases.json"
DEFAULT_BUDGET_CAP_USD = 12.0

sys.path.insert(0, str(BACKEND_ROOT / "src"))

from software_developer_agent.benchmarks.runner import (
    _run_case,
    _run_live_case,
    _score_case,
)
from software_developer_agent.capabilities.models import ProjectSpec
from software_developer_agent.config.settings import Settings
from software_developer_agent.models.job_state import (
    JobRequest,
    JobState,
    JobTask,
    WorkerKind,
)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {message}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def load_cases() -> list[dict[str, Any]]:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("Campaign cases must be a non-empty JSON list.")
    identifiers = [str(case["case_id"]) for case in payload]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Campaign case IDs must be unique.")
    return payload


def initial_state(cases: list[dict[str, Any]], budget_cap_usd: float) -> dict[str, Any]:
    return {
        "version": 1,
        "created_at": time.time(),
        "updated_at": time.time(),
        "budget_cap_usd": budget_cap_usd,
        "spent_usd": 0.0,
        "mode": None,
        "status": "ready",
        "cases": {
            str(case["case_id"]): {
                "category": str(case["category"]),
                "status": "pending",
                "attempts": 0,
                "result_path": None,
                "passed": None,
                "cost_usd": 0.0,
            }
            for case in cases
        },
    }


def load_state(cases: list[dict[str, Any]], budget_cap_usd: float) -> dict[str, Any]:
    if not STATE_PATH.exists():
        state = initial_state(cases, budget_cap_usd)
        atomic_json(STATE_PATH, state)
        return state
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    state["budget_cap_usd"] = min(float(state.get("budget_cap_usd", budget_cap_usd)), budget_cap_usd)
    known = state.setdefault("cases", {})
    for case in cases:
        case_id = str(case["case_id"])
        known.setdefault(
            case_id,
            {
                "category": str(case["category"]),
                "status": "pending",
                "attempts": 0,
                "result_path": None,
                "passed": None,
                "cost_usd": 0.0,
            },
        )
    return state


def save_state(state: dict[str, Any]) -> None:
    state["updated_at"] = time.time()
    atomic_json(STATE_PATH, state)


def campaign_status(state: dict[str, Any]) -> str:
    entries = list(state["cases"].values())
    if any(entry.get("status") == "running" for entry in entries):
        return "running"
    if any(entry.get("passed") is False for entry in entries):
        return "needs_repair"
    if any(entry.get("status") != "completed" for entry in entries):
        return "in_progress"
    return "completed"


def run_preflight(cases: list[dict[str, Any]], state: dict[str, Any]) -> int:
    state["mode"] = "preflight"
    state["status"] = "running"
    save_state(state)
    failures = 0
    for case in cases:
        case_id = str(case["case_id"])
        log(f"preflight:start case={case_id}")
        result = _run_case(case, execute=True)
        payload = asdict(result)
        result_path = RESULTS_ROOT / "preflight" / f"{case_id}.json"
        atomic_json(result_path, payload)
        log(
            f"preflight:finish case={case_id} passed={result.passed} "
            f"score={result.score} duration={result.duration_seconds}s"
        )
        if not result.passed:
            failures += 1
    state["status"] = "preflight_passed" if failures == 0 else "preflight_failed"
    save_state(state)
    return 0 if failures == 0 else 1


def run_live(cases: list[dict[str, Any]], state: dict[str, Any]) -> int:
    maximum_run_cost = float(Settings().maximum_run_budget_usd)
    state["mode"] = "live"
    state["status"] = "running"
    save_state(state)
    failures = 0
    for case in cases:
        case_id = str(case["case_id"])
        entry = state["cases"][case_id]
        if entry.get("status") == "completed":
            continue
        spent = float(state.get("spent_usd", 0.0))
        cap = float(state["budget_cap_usd"])
        if spent + maximum_run_cost > cap:
            state["status"] = "budget_stopped"
            save_state(state)
            log(
                f"live:budget-stop spent=${spent:.6f} reserve=${maximum_run_cost:.2f} "
                f"cap=${cap:.2f}"
            )
            return 2
        entry["status"] = "running"
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        save_state(state)
        log(
            f"live:start case={case_id} category={case['category']} "
            f"campaign_spent=${spent:.6f}"
        )
        try:
            result = _run_live_case(case)
            payload = asdict(result)
        except Exception as exc:  # noqa: BLE001
            payload = {
                "case_id": case_id,
                "capability_id": str(case["capability_id"]),
                "passed": False,
                "score": 0.0,
                "failure_reason": f"{type(exc).__name__}: {exc}",
                "cost_usd": 0.0,
            }
        result_path = RESULTS_ROOT / "live" / f"{case_id}.attempt-{entry['attempts']}.json"
        atomic_json(result_path, payload)
        run_cost = float(payload.get("cost_usd", 0.0))
        state["spent_usd"] = round(float(state.get("spent_usd", 0.0)) + run_cost, 8)
        entry["status"] = "completed"
        entry["result_path"] = str(result_path)
        entry["passed"] = bool(payload.get("passed", False))
        entry["cost_usd"] = round(float(entry.get("cost_usd", 0.0)) + run_cost, 8)
        entry["failure_reason"] = payload.get("failure_reason")
        save_state(state)
        log(
            f"live:finish case={case_id} passed={entry['passed']} "
            f"status={payload.get('job_status')} release={payload.get('release_status')} "
            f"score={payload.get('score')} cost=${run_cost:.6f} "
            f"campaign_spent=${state['spent_usd']:.6f}"
        )
        if not entry["passed"]:
            failures += 1
    state["status"] = campaign_status(state)
    save_state(state)
    return 0 if failures == 0 else 1


def reset_live(cases: list[dict[str, Any]], state: dict[str, Any]) -> None:
    state["status"] = "ready"
    state["mode"] = None
    for case in cases:
        entry = state["cases"][str(case["case_id"])]
        entry.update(
            status="pending",
            result_path=None,
            passed=None,
            failure_reason=None,
        )
    save_state(state)
    log("live:reset pending cases; cumulative cost preserved")


def reset_failed(cases: list[dict[str, Any]], state: dict[str, Any]) -> None:
    reset_count = 0
    for case in cases:
        entry = state["cases"][str(case["case_id"])]
        if entry.get("passed") is not False:
            continue
        entry.update(
            status="pending",
            result_path=None,
            passed=None,
            failure_reason=None,
        )
        reset_count += 1
    state["status"] = "ready"
    state["mode"] = None
    save_state(state)
    log(f"live:reset-failed count={reset_count}; cumulative cost preserved")


def reassess_live(cases: list[dict[str, Any]], state: dict[str, Any]) -> int:
    failures = 0
    for case in cases:
        case_id = str(case["case_id"])
        entry = state["cases"][case_id]
        result_path_value = entry.get("result_path")
        if entry.get("status") != "completed" or not result_path_value:
            failures += 1
            log(f"live:reassess-skip case={case_id} reason=no-completed-result")
            continue
        result_path = Path(str(result_path_value))
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        artifact_path_value = payload.get("artifact_path")
        artifact_root = Path(str(artifact_path_value)) if artifact_path_value else None
        if artifact_root is None or not artifact_root.is_dir():
            failures += 1
            log(f"live:reassess-skip case={case_id} reason=no-preserved-artifact")
            continue
        blueprint = json.loads(
            (artifact_root / "artifacts" / "blueprint.json").read_text(encoding="utf-8")
        )
        risk_report = json.loads(
            (artifact_root / "artifacts" / "risk-report.json").read_text(encoding="utf-8")
        )
        spec = ProjectSpec.from_dict(blueprint["project_spec"])
        job = JobState(
            request=JobRequest(prompt=str(case["prompt"]), project_id=str(case["project_id"])),
            project_spec=spec.to_dict(),
            tasks=[
                JobTask(
                    worker_kind=WorkerKind(worker_kind),
                    title=f"{worker_kind.title()} certification",
                    instructions="Reassess preserved live artifact.",
                    capability_id=spec.capability_id,
                )
                for worker_kind in case.get("expected_workers", [])
            ],
        )
        job.approval_state["benchmark_validation"] = risk_report.get("validation", {})
        files = {
            path.relative_to(artifact_root).as_posix(): path
            for path in artifact_root.rglob("*")
            if path.is_file()
        }
        score, checks = _score_case(case, spec, artifact_root, files, job)
        passed = bool(
            payload.get("job_status") == "succeeded"
            and payload.get("release_status") == "verified"
            and score >= 12.0
        )
        payload.update(
            passed=passed,
            score=score,
            checks=checks,
            failure_reason=None
            if passed
            else "Preserved live artifact does not meet the current certification threshold.",
        )
        atomic_json(result_path, payload)
        entry["passed"] = passed
        entry["failure_reason"] = payload["failure_reason"]
        failures += int(not passed)
        log(f"live:reassess case={case_id} passed={passed} score={score} cost=$0.000000")
    state["status"] = campaign_status(state)
    save_state(state)
    return 0 if failures == 0 else 1


def print_status(state: dict[str, Any]) -> None:
    summary: dict[str, dict[str, int]] = {}
    for entry in state["cases"].values():
        category = str(entry["category"])
        category_summary = summary.setdefault(category, {"passed": 0, "failed": 0, "pending": 0})
        if entry.get("passed") is True:
            category_summary["passed"] += 1
        elif entry.get("status") == "completed":
            category_summary["failed"] += 1
        else:
            category_summary["pending"] += 1
    print(
        json.dumps(
            {
                "status": state.get("status"),
                "mode": state.get("mode"),
                "spent_usd": state.get("spent_usd"),
                "budget_cap_usd": state.get("budget_cap_usd"),
                "categories": summary,
            },
            indent=2,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the isolated Agentic Forge regression campaign.")
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--preflight", action="store_true")
    operation.add_argument("--live", action="store_true")
    operation.add_argument("--status", action="store_true")
    operation.add_argument("--reset-live", action="store_true")
    operation.add_argument("--reset-failed", action="store_true")
    operation.add_argument("--reassess", action="store_true")
    parser.add_argument(
        "--budget-cap-usd",
        type=float,
        default=float(os.getenv("CAMPAIGN_BUDGET_CAP_USD", DEFAULT_BUDGET_CAP_USD)),
    )
    parser.add_argument("--case", action="append", dest="case_ids")
    arguments = parser.parse_args()
    if arguments.budget_cap_usd <= 0:
        raise ValueError("Campaign budget cap must be positive.")
    cases = load_cases()
    if arguments.case_ids:
        selected = set(arguments.case_ids)
        cases = [case for case in cases if str(case["case_id"]) in selected]
        missing = selected - {str(case["case_id"]) for case in cases}
        if missing:
            raise ValueError(f"Unknown campaign cases: {', '.join(sorted(missing))}")
    state = load_state(cases, arguments.budget_cap_usd)
    os.chdir(PROJECT_ROOT)
    if arguments.status:
        print_status(state)
        return 0
    if arguments.reset_live:
        reset_live(cases, state)
        return 0
    if arguments.reset_failed:
        reset_failed(cases, state)
        return 0
    if arguments.reassess:
        return reassess_live(cases, state)
    if arguments.preflight:
        return run_preflight(cases, state)
    return run_live(cases, state)


if __name__ == "__main__":
    raise SystemExit(main())
