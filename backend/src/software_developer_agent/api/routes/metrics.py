from dataclasses import asdict

from fastapi import APIRouter

from software_developer_agent.observability.metrics import metrics

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("")
def get_metrics() -> dict[str, int | float]:
    return asdict(metrics.snapshot())
