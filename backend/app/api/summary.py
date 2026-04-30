"""GET /api/summary — cross-project stats for the dashboard (Phase 3, UI-01)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Task
from .deps import get_session


router = APIRouter(prefix="/summary", tags=["summary"])


class SummaryResponse(BaseModel):
    total_tasks: int
    queued: int
    running: int
    waiting_input: int
    waiting_approval: int
    done: int
    failed: int
    cancelled: int


@router.get("", response_model=SummaryResponse)
def get_summary(session: Session = Depends(get_session)) -> SummaryResponse:
    """Return task counts grouped by status across all projects."""
    rows = session.execute(
        select(Task.status, func.count(Task.id))
        .group_by(Task.status)
    ).all()
    counts: dict[str, int] = {row[0]: row[1] for row in rows}
    total = sum(counts.values())
    return SummaryResponse(
        total_tasks=total,
        queued=counts.get("queued", 0),
        running=counts.get("running", 0),
        waiting_input=counts.get("waiting_input", 0),
        waiting_approval=counts.get("waiting_approval", 0),
        done=counts.get("done", 0),
        failed=counts.get("failed", 0),
        cancelled=counts.get("cancelled", 0),
    )
