from software_developer_agent.models.job_state import JobRequest, JobState
from software_developer_agent.orchestration.redis_queue import RedisJobQueue


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    def lpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).insert(0, value)

    def lpop(self, key: str) -> str | None:
        values = self.lists.setdefault(key, [])
        if not values:
            return None
        return values.pop(0)

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        values = self.lists.setdefault(key, [])
        return values[start : end + 1]

    def ltrim(self, key: str, start: int, end: int) -> None:
        self.lists[key] = self.lists.setdefault(key, [])[start : end + 1]

    def lrem(self, key: str, count: int, value: str) -> None:
        self.lists[key] = [item for item in self.lists.setdefault(key, []) if item != value]


def test_redis_queue_restores_submitted_job() -> None:
    queue = RedisJobQueue(FakeRedis())
    job = JobState(request=JobRequest(prompt="Build API"))

    queue.submit(job)
    restored = queue.pop_next()

    assert restored is not None
    assert restored.job_id == job.job_id
    assert queue.list_jobs()[0].job_id == job.job_id
