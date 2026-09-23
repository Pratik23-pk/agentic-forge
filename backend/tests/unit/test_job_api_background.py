from fastapi import FastAPI
from fastapi.testclient import TestClient

from software_developer_agent.api.routes import jobs as jobs_routes
from software_developer_agent.models.job_state import JobStatus
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
