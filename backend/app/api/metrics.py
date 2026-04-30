"""Observability metrics endpoint (Phase 8, QA-06).

GET /api/metrics — returns task counts by status, active run count,
executor heartbeat (last seen), and basic project summary.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..models import Project, Run, Task
from .deps import get_session

router = APIRouter(prefix="/metrics", tags=["metrics"])


class MetricsResponse(BaseModel):
    total_projects: int
    total_tasks: int
    tasks_by_status: dict[str, int]
    active_runs: int


@router.get("", response_model=MetricsResponse)
def get_metrics(db: Session = Depends(get_session)) -> MetricsResponse:
    total_projects = db.scalar(select(func.count(Project.id))) or 0
    total_tasks = db.scalar(select(func.count(Task.id))) or 0

    rows = db.execute(
        select(Task.status, func.count(Task.id)).group_by(Task.status)
    ).all()
    tasks_by_status = {row[0]: row[1] for row in rows}

    active_runs = db.scalar(
        select(func.count(Run.id)).where(Run.status == "running")
    ) or 0

    return MetricsResponse(
        total_projects=total_projects,
        total_tasks=total_tasks,
        tasks_by_status=tasks_by_status,
        active_runs=active_runs,
    )
