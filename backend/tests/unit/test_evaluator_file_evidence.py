import json

from software_developer_agent.agents.evaluator_agent import EvaluatorAgent
from software_developer_agent.models.job_state import (
    GuardrailFinding,
    GuardrailReport,
    JobArtifact,
    JobRequest,
    JobState,
    JobTask,
    TaskStatus,
    WorkerKind,
    WorkerResult,
)


def test_evaluator_retries_worker_that_returns_only_text() -> None:
    job = JobState(request=JobRequest(prompt="Build a webapp", project_id="demo"))
    task = JobTask(worker_kind=WorkerKind.FRONTEND, title="UI", instructions="Build UI")
    task.status = TaskStatus.SUCCEEDED
    job.tasks = [task]
    job.add_worker_result(
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.FRONTEND,
            status=TaskStatus.SUCCEEDED,
            summary="frontend worker completed",
            output="Implementation plan only.",
        )
    )

    result = EvaluatorAgent().evaluate(job)

    assert not result.passed
    assert result.retry_targets == [WorkerKind.FRONTEND]
    assert "missing_file_manifest:frontend" in result.checks


def test_evaluator_accepts_manifest_and_artifacts() -> None:
    job = JobState(request=JobRequest(prompt="Build a webapp", project_id="demo"))
    task = JobTask(worker_kind=WorkerKind.FRONTEND, title="UI", instructions="Build UI")
    task.status = TaskStatus.SUCCEEDED
    job.tasks = [task]
    job.add_worker_result(
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.FRONTEND,
            status=TaskStatus.SUCCEEDED,
            summary="frontend worker completed",
            output=json.dumps(
                {
                    "summary": "Generated UI.",
                    "files": [{"path": "frontend/src/App.jsx", "content": "export default App"}],
                    "validation_commands": ["cd frontend && npm run build"],
                }
            ),
        )
    )
    job.add_artifact(
        JobArtifact(
            artifact_id="project-folder",
            kind="folder",
            name="demo",
            path="/tmp/demo",
            url="/api/jobs/demo/files",
            metadata={"validation": {"passed": True, "results": []}},
        )
    )
    job.add_artifact(
        JobArtifact(
            artifact_id="project-zip",
            kind="zip",
            name="demo.zip",
            path="/tmp/demo.zip",
            url="/api/jobs/demo/download",
        )
    )

    result = EvaluatorAgent().evaluate(job)

    assert result.passed
    assert "file_manifest:frontend:1" in result.checks


def test_evaluator_prefers_accepted_checkpoint_over_stale_transport_failure() -> None:
    job = JobState(request=JobRequest(prompt="Build a webapp", project_id="demo"))
    task = JobTask(worker_kind=WorkerKind.FRONTEND, title="UI", instructions="Build UI")
    task.status = TaskStatus.SUCCEEDED
    task.attempt = 1
    job.tasks = [task]
    job.add_worker_result(
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.FRONTEND,
            status=TaskStatus.SUCCEEDED,
            summary="accepted checkpoint",
            output=json.dumps(
                {
                    "summary": "Generated UI.",
                    "files": [{"path": "frontend/src/App.jsx", "content": "export default App"}],
                }
            ),
            attempt=1,
        )
    )
    job.manifest_state = {
        "files": {
            "frontend/src/App.jsx": {
                "task_id": task.task_id,
                "worker_kind": "frontend",
                "attempt": 1,
                "content": "export default App",
                "deleted": False,
            }
        },
        "task_manifests": {
            task.task_id: {
                "worker_kind": "frontend",
                "attempt": 1,
                "operation": "patch",
                "summary": "accepted checkpoint",
                "validation_commands": [],
                "notes": [],
            }
        },
    }
    job.add_worker_result(
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.FRONTEND,
            status=TaskStatus.FAILED,
            summary="later transport failure",
            errors=["network unavailable"],
            attempt=1,
        )
    )
    for artifact in (
        JobArtifact(
            artifact_id="project-folder",
            kind="folder",
            name="demo",
            path="/tmp/demo",
            url="/api/jobs/demo/files",
            metadata={"validation": {"passed": True, "results": []}},
        ),
        JobArtifact(
            artifact_id="project-zip",
            kind="zip",
            name="demo.zip",
            path="/tmp/demo.zip",
            url="/api/jobs/demo/download",
        ),
    ):
        job.add_artifact(artifact)

    result = EvaluatorAgent().evaluate(job)

    assert result.passed
    assert "worker_succeeded:frontend" in result.checks


def test_evaluator_uses_latest_guardrail_report_per_name() -> None:
    job = JobState(request=JobRequest(prompt="Build a webapp", project_id="demo"))
    task = JobTask(worker_kind=WorkerKind.FRONTEND, title="UI", instructions="Build UI")
    task.status = TaskStatus.SUCCEEDED
    job.tasks = [task]
    job.add_worker_result(
        WorkerResult(
            task_id=task.task_id,
            worker_kind=WorkerKind.FRONTEND,
            status=TaskStatus.SUCCEEDED,
            summary="frontend worker completed",
            output=json.dumps(
                {
                    "summary": "Generated UI.",
                    "files": [{"path": "frontend/src/App.jsx", "content": "export default App"}],
                }
            ),
        )
    )
    job.add_guardrail_report(
        GuardrailReport(
            name="dlp_scan",
            passed=False,
            findings=[
                GuardrailFinding(
                    name="dlp_email",
                    passed=False,
                    severity="high",
                    message="Old blocked finding",
                )
            ],
        )
    )
    job.add_guardrail_report(
        GuardrailReport(
            name="dlp_scan",
            passed=True,
            findings=[
                GuardrailFinding(
                    name="dlp_email_false_positive",
                    passed=True,
                    severity="info",
                    message="Suppressed false positive",
                    metadata={"classification": "suppressed_false_positive"},
                )
            ],
        )
    )
    job.add_artifact(
        JobArtifact(
            artifact_id="project-folder",
            kind="folder",
            name="demo",
            path="/tmp/demo",
            url="/api/jobs/demo/files",
            metadata={"validation": {"passed": True, "results": []}},
        )
    )
    job.add_artifact(
        JobArtifact(
            artifact_id="project-zip",
            kind="zip",
            name="demo.zip",
            path="/tmp/demo.zip",
            url="/api/jobs/demo/download",
        )
    )

    result = EvaluatorAgent().evaluate(job)

    assert result.passed
