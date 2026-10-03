from fastapi import FastAPI
from fastapi.testclient import TestClient

from software_developer_agent.api.routes import jobs as jobs_routes
from software_developer_agent.models.job_state import (
    ApprovalGate,
    HumanFeedbackRequest,
    HumanFeedbackStatus,
    JobStatus,
)
from software_developer_agent.orchestration.conditional_router import RouteAction, RouteDecision
from software_developer_agent.orchestration.redis_queue import InMemoryJobQueue
from software_developer_agent.persistence.job_store import InMemoryJobStore


def _client(monkeypatch, runtime_type):
    store = InMemoryJobStore()
    queue = InMemoryJobQueue()
    monkeypatch.setattr(jobs_routes, "get_job_store", lambda: store)
    monkeypatch.setattr(jobs_routes, "get_job_queue", lambda: queue)
    monkeypatch.setattr(jobs_routes, "AgentRuntime", runtime_type)
    app = FastAPI()
    app.include_router(jobs_routes.router, prefix="/api")
    return TestClient(app), store, queue


def test_submit_returns_accepted_before_background_result(monkeypatch) -> None:
    class SuccessfulRuntime:
        def run_to_completion(self, job):
            job.set_status(JobStatus.SUCCEEDED)
            return RouteDecision(RouteAction.SUCCESS, "done")

    client, store, queue = _client(monkeypatch, SuccessfulRuntime)

    response = client.post(
        "/api/jobs",
        json={"prompt": "Build a local API", "run_immediately": True},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "running"
    assert response.json()["route"]["action"] == "accepted"
    stored = store.get(response.json()["job_id"])
    assert stored is not None
    assert stored.status == JobStatus.SUCCEEDED
    assert queue.pop_next() is None


def test_background_pipeline_exception_becomes_failed_job(monkeypatch) -> None:
    class FailingRuntime:
        def run_to_completion(self, job):
            raise RuntimeError("planner unavailable")

    client, store, _ = _client(monkeypatch, FailingRuntime)

    response = client.post(
        "/api/jobs",
        json={"prompt": "Build a local API", "run_immediately": True},
    )

    assert response.status_code == 202
    stored = store.get(response.json()["job_id"])
    assert stored is not None
    assert stored.status == JobStatus.FAILED
    assert stored.artifacts == []
    assert "planner unavailable" in stored.errors[0]


def test_submit_generates_readable_unique_name_for_legacy_placeholder(monkeypatch) -> None:
    class SuccessfulRuntime:
        def run_to_completion(self, job):
            job.set_status(JobStatus.SUCCEEDED)
            return RouteDecision(RouteAction.SUCCESS, "done")

    client, store, _ = _client(monkeypatch, SuccessfulRuntime)

    response = client.post(
        "/api/jobs",
        json={
            "prompt": "Build an India gaming industry showcase",
            "project_id": "build-27a",
            "run_immediately": True,
        },
    )

    payload = response.json()
    stored = store.get(payload["job_id"])
    assert stored is not None
    assert stored.request.project_id.startswith("India Gaming Industry ")
    assert stored.request.metadata["project_name_generated"] is True


def test_submit_preserves_user_project_name(monkeypatch) -> None:
    class SuccessfulRuntime:
        def run_to_completion(self, job):
            job.set_status(JobStatus.SUCCEEDED)
            return RouteDecision(RouteAction.SUCCESS, "done")

    client, store, _ = _client(monkeypatch, SuccessfulRuntime)

    response = client.post(
        "/api/jobs",
        json={
            "prompt": "Build a gallery",
            "project_id": "Bharat Play Atlas",
            "run_immediately": True,
        },
    )

    stored = store.get(response.json()["job_id"])
    assert stored is not None
    assert stored.request.project_id == "Bharat Play Atlas"
    assert stored.request.metadata["project_name_generated"] is False


def test_stale_feedback_submission_reconciles_to_advancing_job(monkeypatch) -> None:
    class UnusedRuntime:
        pass

    client, store, _ = _client(monkeypatch, UnusedRuntime)
    job = jobs_routes.JobState(
        request=jobs_routes.JobRequest(prompt="Build a restaurant site"),
        status=JobStatus.EVALUATING,
    )
    store.save(job)

    response = client.post(
        f"/api/jobs/{job.job_id}/feedback",
        json={"decision": "approve", "checkpoint_id": "stale-checkpoint"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == JobStatus.EVALUATING.value
    assert response.json()["route"]["action"] == "checkpoint_reconciled"


def test_resolved_feedback_submission_is_idempotent(monkeypatch) -> None:
    class UnusedRuntime:
        pass

    client, store, _ = _client(monkeypatch, UnusedRuntime)
    job = jobs_routes.JobState(
        request=jobs_routes.JobRequest(prompt="Build a restaurant site"),
        status=JobStatus.SUCCEEDED,
    )
    checkpoint = HumanFeedbackRequest(
        gate=ApprovalGate.RELEASE,
        worker_kind=None,
        task_id=None,
        attempt=0,
        title="Release",
        prompt="Approve",
        summary="Ready",
        visual_type="structured_json",
        visual_content="{}",
    )
    job.add_feedback_request(checkpoint)
    job.resolve_active_feedback(HumanFeedbackStatus.APPROVED)
    job.set_status(JobStatus.SUCCEEDED)
    store.save(job)

    response = client.post(
        f"/api/jobs/{job.job_id}/feedback",
        json={"decision": "approve", "checkpoint_id": checkpoint.checkpoint_id},
    )

    assert response.status_code == 202
    assert response.json()["route"]["action"] == "checkpoint_reconciled"


def test_feedback_rejects_a_different_active_checkpoint(monkeypatch) -> None:
    class UnusedRuntime:
        pass

    client, store, _ = _client(monkeypatch, UnusedRuntime)
    job = jobs_routes.JobState(request=jobs_routes.JobRequest(prompt="Build a site"))
    job.add_feedback_request(
        HumanFeedbackRequest(
            gate=ApprovalGate.PRODUCT_CONTRACT,
            worker_kind=None,
            task_id=None,
            attempt=0,
            title="Scope",
            prompt="Approve",
            summary="Ready",
            visual_type="structured_json",
            visual_content="{}",
        )
    )
    store.save(job)

    response = client.post(
        f"/api/jobs/{job.job_id}/feedback",
        json={"decision": "approve", "checkpoint_id": "different-checkpoint"},
    )

    assert response.status_code == 409
    assert "checkpoint changed" in response.json()["detail"].lower()


def test_run_resumes_an_orphaned_persisted_job(monkeypatch) -> None:
    class SuccessfulRuntime:
        def run_to_completion(self, job):
            job.set_status(JobStatus.SUCCEEDED)
            return RouteDecision(RouteAction.SUCCESS, "resumed")

    client, store, _ = _client(monkeypatch, SuccessfulRuntime)
    job = jobs_routes.JobState(
        request=jobs_routes.JobRequest(prompt="Resume me"),
        status=JobStatus.EVALUATING,
    )
    store.save(job)

    response = client.post(f"/api/jobs/{job.job_id}/run")

    assert response.status_code == 202
    assert store.get(job.job_id).status == JobStatus.SUCCEEDED


def test_run_rejects_a_job_present_in_the_active_queue(monkeypatch) -> None:
    class UnusedRuntime:
        pass

    client, store, queue = _client(monkeypatch, UnusedRuntime)
    job = jobs_routes.JobState(
        request=jobs_routes.JobRequest(prompt="Still running"),
        status=JobStatus.RUNNING,
    )
    store.save(job)
    queue.update(job)

    response = client.post(f"/api/jobs/{job.job_id}/run")

    assert response.status_code == 409
    assert response.json()["detail"] == "Job is already running."
