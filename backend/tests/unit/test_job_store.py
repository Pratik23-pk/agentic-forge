from software_developer_agent.models.job_state import JobRequest, JobState, JobStatus
from software_developer_agent.persistence.job_store import InMemoryJobStore


def test_in_memory_job_store_lists_recent_first() -> None:
    store = InMemoryJobStore()
    first = JobState(request=JobRequest(prompt="First"))
    second = JobState(request=JobRequest(prompt="Second"))
    second.set_status(JobStatus.RUNNING)

    store.save(first)
    store.save(second)

    assert store.get(first.job_id) == first
    assert store.list_recent()[0] == second
