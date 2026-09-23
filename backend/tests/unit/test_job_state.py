from software_developer_agent.models.job_state import (
    ApprovalGate,
    EvaluationResult,
    HumanFeedbackRequest,
    HumanFeedbackStatus,
    JobRequest,
    JobState,
    JobTask,
    ReleaseStatus,
    RepairTicket,
    TaskStatus,
    WorkerKind,
    WorkerResult,
    job_state_from_dict,
)


def test_job_state_round_trips_tool_calls() -> None:
    job = JobState(request=JobRequest(prompt="Build a backend API"))
    task = JobTask(worker_kind=WorkerKind.BACKEND, title="API", instructions="Implement API")
    job.tasks = [task]
    job.add_worker_result(
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.BACKEND,
            status=TaskStatus.SUCCEEDED,
            summary="done",
            tool_calls=[{"tool": "search", "status": "skipped"}],
        )
    )

    restored = job_state_from_dict(job.to_dict())

    assert restored.job_id == job.job_id
    assert restored.tasks[0].worker_kind == WorkerKind.BACKEND
    assert restored.worker_results[0].tool_calls[0]["tool"] == "search"


def test_job_state_round_trips_human_feedback_request() -> None:
    job = JobState(request=JobRequest(prompt="Build dashboard"))
    task = JobTask(worker_kind=WorkerKind.FRONTEND, title="UI", instructions="Build UI")
    job.tasks = [task]
    request = HumanFeedbackRequest(
        gate=ApprovalGate.WORKER_REVIEW,
        worker_kind=WorkerKind.FRONTEND,
        task_id=task.task_id,
        attempt=1,
        title="Frontend review",
        prompt="Does this match expectations?",
        summary="frontend worker completed",
        visual_type="svg_data_uri",
        visual_content="data:image/svg+xml;utf8,<svg />",
    )
    job.add_feedback_request(request)

    restored = job_state_from_dict(job.to_dict())

    assert restored.active_feedback_request_id == request.checkpoint_id
    assert restored.feedback_requests[0].status == HumanFeedbackStatus.PENDING
    assert restored.feedback_requests[0].worker_kind == WorkerKind.FRONTEND
    assert restored.feedback_requests[0].gate == ApprovalGate.WORKER_REVIEW


def test_job_state_round_trips_checkpointed_manifest_state() -> None:
    job = JobState(request=JobRequest(prompt="Build a frontend"))
    job.manifest_generation = 2
    job.manifest_state = {
        "revision": 3,
        "files": {"frontend/src/App.tsx": {"content": "export {};\n"}},
    }
    job.verified_manifest_state = dict(job.manifest_state)
    job.verified_validation = {"passed": True, "release_ready": True}
    job.manifest_transaction = {
        "base": {"revision": 2, "files": {}},
        "fingerprints": {"frontend": "abc"},
    }

    restored = job_state_from_dict(job.to_dict())

    assert restored.manifest_generation == 2
    assert restored.manifest_state == job.manifest_state
    assert restored.verified_manifest_state == job.verified_manifest_state
    assert restored.verified_validation == job.verified_validation
    assert restored.manifest_transaction == job.manifest_transaction


def test_job_state_round_trips_release_risk() -> None:
    job = JobState(
        request=JobRequest(prompt="Build an app"),
        release_status=ReleaseStatus.QUARANTINED,
        risk_findings=[{"name": "api_key", "blocking": True}],
        quarantine_preview_consumed=True,
    )

    restored = job_state_from_dict(job.to_dict())

    assert restored.release_status == ReleaseStatus.QUARANTINED
    assert restored.risk_findings[0]["blocking"] is True
    assert restored.quarantine_preview_consumed is True


def test_job_state_round_trips_replan_required() -> None:
    job = JobState(
        request=JobRequest(prompt="Build dashboard"),
        request_policy={
            "requested_capabilities": ["analytics"],
            "excluded_capabilities": ["database"],
        },
        api_contract={"routes": [{"method": "GET", "path": "/api/metrics"}]},
        artifact_errors=["draft failed"],
        validation_results=[{"name": "frontend_build", "passed": False}],
    )
    job.evaluation = EvaluationResult(passed=False, replan_required=True)

    restored = job_state_from_dict(job.to_dict())

    assert restored.evaluation is not None
    assert restored.evaluation.replan_required
    assert restored.request_policy["excluded_capabilities"] == ["database"]
    assert restored.api_contract["routes"][0]["path"] == "/api/metrics"
    assert restored.artifact_errors == ["draft failed"]
    assert restored.validation_results[0]["name"] == "frontend_build"


def test_job_state_round_trips_repair_kernel_state() -> None:
    job = JobState(
        request=JobRequest(prompt="Build a game"),
        warnings=["Planner used a deterministic fallback."],
    )
    task = JobTask(
        worker_kind=WorkerKind.FRONTEND,
        title="Game UI",
        instructions="Build it",
        adapter_ids=["core", "stack:react-vite", "browser-game"],
        transport_attempts=2,
        repair_rejections=1,
    )
    job.tasks = [task]
    job.worker_results = [
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.FRONTEND,
            status=TaskStatus.SUCCEEDED,
            summary="Certified checkpoint",
            used_fallback=True,
        )
    ]
    ticket = RepairTicket(
        source="adapter_validation",
        worker_kind=WorkerKind.FRONTEND,
        category="test_contract",
        summary="Heading contract mismatch",
        fingerprint="abc123",
        occurrence=2,
        strategy="escalated_patch",
        target_files=["frontend/src/App.test.tsx"],
    )
    job.add_repair_ticket(ticket)

    restored = job_state_from_dict(job.to_dict())

    assert restored.tasks[0].adapter_ids[-1] == "browser-game"
    assert restored.tasks[0].transport_attempts == 2
    assert restored.tasks[0].repair_rejections == 1
    assert restored.worker_results[0].used_fallback
    assert restored.warnings == ["Planner used a deterministic fallback."]
    assert restored.active_repair_ticket(WorkerKind.FRONTEND).strategy == "escalated_patch"
