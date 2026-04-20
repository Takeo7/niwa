"""Pure functions over ``Session`` for the ``Run`` resource.

Three helpers are exposed:

* ``create_run`` — insert a new ``Run`` row in ``running`` state with an
  ``event_type="started"`` entry. The caller must pass the associated task
  id; no coupling with the HTTP layer.
* ``complete_run`` — transition a ``Run`` to ``completed``, fill in the exit
  code / outcome / ``finished_at``, and write the matching ``completed``
  event. Used by the echo executor today and by the real adapter later.
* ``list_runs_for_task`` — read-only helper for the ``GET /api/tasks/{id}/runs``
  endpoint. Raises ``TaskNotFound`` when the task does not exist so the API
  can return ``404`` instead of an empty list for a ghost id.

Timestamps use ``datetime.now(timezone.utc)`` directly — the brief calls out
that microsecond granularity is needed for the race test and for ordering
assertions, which ``func.now()`` cannot provide on SQLite (seconds only).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Run, RunEvent, Task
from .tasks import TaskNotFound, get_task


def create_run(
    session: Session,
    task_id: int,
    *,
    model: str,
    artifact_root: str = "",
) -> Run:
    """Insert a new ``running`` run plus its ``started`` event.

    Does **not** commit — the caller owns the transaction so the executor
    can group the task transition, run creation and event writes into a
    single atomic unit of work.
    """

    now = datetime.now(timezone.utc)
    run = Run(
        task_id=task_id,
        status="running",
        model=model,
        started_at=now,
        artifact_root=artifact_root,
    )
    session.add(run)
    session.flush()  # Populate run.id without committing.

    session.add(
        RunEvent(
            run_id=run.id,
            event_type="started",
            payload_json=None,
        )
    )
    return run


def complete_run(
    session: Session,
    run: Run,
    *,
    exit_code: int,
    outcome: str,
) -> Run:
    """Transition ``run`` to ``completed`` and append its ``completed`` event.

    Mutates ``run`` in place and writes the event row in the same session;
    again, the caller is responsible for the commit.
    """

    run.status = "completed"
    run.finished_at = datetime.now(timezone.utc)
    run.exit_code = exit_code
    run.outcome = outcome

    session.add(
        RunEvent(
            run_id=run.id,
            event_type="completed",
            payload_json=None,
        )
    )
    return run


def list_runs_for_task(session: Session, task_id: int) -> list[Run]:
    """Return every run for ``task_id`` ordered by ``created_at`` ASC.

    Raises ``TaskNotFound`` when the task id does not exist so the API layer
    can distinguish "task missing" (``404``) from "task has no runs yet"
    (``200`` + ``[]``).
    """

    # ``get_task`` raises ``TaskNotFound``; re-use it instead of re-querying.
    get_task(session, task_id)

    stmt = (
        select(Run)
        .where(Run.task_id == task_id)
        .order_by(Run.created_at.asc(), Run.id.asc())
    )
    return list(session.scalars(stmt).all())


__all__ = [
    "TaskNotFound",
    "complete_run",
    "create_run",
    "list_runs_for_task",
]
