"""Operations API — kill switch and admin endpoints (Phase 6, SEC-07)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.deps import require_auth
from ..models import Task
from ..services.audit import log_event
from .deps import get_session

router = APIRouter(prefix="/ops", tags=["ops"])


class KillSwitchResult(BaseModel):
    cancelled_tasks: int
    waiting_tasks_cancelled: int
    queued_tasks_cancelled: int
    running_tasks_marked: int


@router.post(
    "/kill-switch",
    response_model=KillSwitchResult,
    dependencies=[Depends(require_auth)],
)
def kill_switch(request: Request, db: Session = Depends(get_session)) -> KillSwitchResult:
    """Cancel ALL active tasks (queued, waiting_input, running).

    Running tasks are marked ``cancelled``; the executor checks status before
    each step and bails out. Returns counts per state moved.
    """
    queued = db.query(Task).filter(Task.status == "queued").all()
    waiting = db.query(Task).filter(Task.status == "waiting_input").all()
    running = db.query(Task).filter(Task.status == "running").all()

    for t in queued + waiting + running:
        t.status = "cancelled"

    db.commit()

    ip = request.client.host if request.client else None
    log_event(
        db,
        actor_type="user",
        action="ops.kill_switch",
        ip_address=ip,
        payload={
            "queued": len(queued),
            "waiting_input": len(waiting),
            "running": len(running),
        },
    )

    return KillSwitchResult(
        cancelled_tasks=len(queued) + len(waiting) + len(running),
        queued_tasks_cancelled=len(queued),
        waiting_tasks_cancelled=len(waiting),
        running_tasks_marked=len(running),
    )
