"""Operations API — kill switch and admin endpoints (Phase 6, SEC-07)."""

from __future__ import annotations

import os
import signal
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.deps import require_auth
from ..models import Run, RunEvent, Task
from ..services.audit import log_event
from .deps import get_session

router = APIRouter(prefix="/ops", tags=["ops"])


class KillSwitchResult(BaseModel):
    cancelled_tasks: int
    waiting_tasks_cancelled: int
    queued_tasks_cancelled: int
    running_tasks_marked: int
    running_processes_signalled: int


RUNNING_TASK_STATUSES = (
    "triaging",
    "planning",
    "waiting_approval",
    "executing",
    "verifying",
    "reviewing",
    "running",
)


def _signal_process(pid: int) -> bool:
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except ProcessLookupError:
            return False


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
    running = db.query(Task).filter(Task.status.in_(RUNNING_TASK_STATUSES)).all()
    running_ids = [t.id for t in running]
    active_runs = (
        db.query(Run)
        .filter(Run.task_id.in_(running_ids), Run.status == "running")
        .all()
        if running_ids
        else []
    )
    signalled = 0
    now = datetime.now(timezone.utc)
    for run in active_runs:
        if run.pid is not None and _signal_process(run.pid):
            signalled += 1
        run.status = "cancelled"
        run.finished_at = now
        run.outcome = "kill_switch"
        db.add(RunEvent(run_id=run.id, event_type="cancelled", payload_json=None))

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
            "running_processes_signalled": signalled,
        },
    )

    return KillSwitchResult(
        cancelled_tasks=len(queued) + len(waiting) + len(running),
        queued_tasks_cancelled=len(queued),
        waiting_tasks_cancelled=len(waiting),
        running_tasks_marked=len(running),
        running_processes_signalled=signalled,
    )
