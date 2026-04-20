"""Executor pipeline — pure functions over a SQLAlchemy ``Session``.

Three building blocks compose the pipeline:

1. ``claim_next_task`` atomically flips the oldest ``queued`` task to
   ``running`` and returns it. "Atomic" here means safe against two
   executor instances racing: SQLite has no ``SELECT ... FOR UPDATE``, so
   we open a ``BEGIN IMMEDIATE`` transaction (which grabs the reserved
   write lock) and issue an ``UPDATE ... WHERE id = ? AND status = 'queued'``
   that affects zero rows when a competitor already won. Returning ``None``
   in that case signals "nothing to claim".
2. ``run_echo`` does the actual echo: create the ``Run``, skip the work,
   mark the run ``completed``, transition the task ``running → done``, and
   write the matching event rows. Everything happens inside the caller's
   transaction so a partial failure rolls back the whole claim.
3. ``process_pending`` drains the queue by calling the first two in a loop
   until ``claim_next_task`` yields ``None``. One task = one transaction.

Commits are owned by this module, not by the helpers in ``services/runs.py``
and ``services/tasks.py``, because the brief demands that task transition
and run creation land together or not at all.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text, update
from sqlalchemy.orm import Session

from ..models import Run, Task, TaskEvent
from ..services.runs import complete_run, create_run


logger = logging.getLogger("niwa.executor")

ECHO_MODEL = "echo"


def claim_next_task(session: Session) -> Task | None:
    """Atomically take ownership of the oldest ``queued`` task.

    Uses SQLite's ``BEGIN IMMEDIATE`` to grab the reserved write lock before
    issuing the conditional ``UPDATE``. When another executor has already
    flipped the target row, the ``UPDATE`` affects zero rows and we return
    ``None``; the caller treats that as "queue empty for us".

    The returned task is guaranteed to be in ``running`` state and belongs
    to this session — safe to pass into ``run_echo`` directly.
    """

    # Close any prior implicit transaction so ``BEGIN IMMEDIATE`` is fresh.
    # SQLAlchemy's autobegin would otherwise leave a deferred transaction in
    # place and our explicit BEGIN would 400-out.
    if session.in_transaction():
        session.rollback()

    # ``BEGIN IMMEDIATE`` upgrades this connection to a reserved lock right
    # away — no other writer can slip in between the SELECT and the UPDATE.
    session.execute(text("BEGIN IMMEDIATE"))

    try:
        # Pick the oldest queued task. FOR UPDATE is unavailable on SQLite;
        # the reserved lock above is what guarantees exclusivity.
        row = session.execute(
            text(
                "SELECT id FROM tasks WHERE status = 'queued' "
                "ORDER BY created_at ASC, id ASC LIMIT 1"
            )
        ).first()
        if row is None:
            session.commit()
            return None

        task_id = int(row[0])
        result = session.execute(
            update(Task)
            .where(Task.id == task_id, Task.status == "queued")
            .values(status="running")
        )
        if result.rowcount == 0:
            # A competing executor claimed it between the SELECT and the
            # UPDATE. Treat as empty queue for this call.
            session.commit()
            return None

        session.add(
            TaskEvent(
                task_id=task_id,
                kind="status_changed",
                message=None,
                payload_json=json.dumps({"from": "queued", "to": "running"}),
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    # Reload the ORM object outside the transaction — this starts a new one.
    task = session.get(Task, task_id)
    return task


def run_echo(session: Session, task: Task) -> Run:
    """Run the echo pipeline for ``task`` and commit the result.

    Creates a ``Run`` in ``running``, immediately transitions it to
    ``completed`` (no work), and flips the task to ``done``. Two run events
    (``started``, ``completed``) and one task event (``running → done``)
    are written in the same transaction.
    """

    run = create_run(session, task.id, model=ECHO_MODEL, artifact_root="")
    complete_run(session, run, exit_code=0, outcome="echo")

    now = datetime.now(timezone.utc)
    task.status = "done"
    task.completed_at = now

    session.add(
        TaskEvent(
            task_id=task.id,
            kind="status_changed",
            message=None,
            payload_json=json.dumps({"from": "running", "to": "done"}),
        )
    )
    session.commit()
    session.refresh(run)
    return run


def process_pending(session: Session) -> int:
    """Drain every ``queued`` task currently visible to this session.

    Returns the number of tasks processed. Stops on the first ``None`` from
    ``claim_next_task`` — empty queue, or every claim lost the race. A
    failing ``run_echo`` rolls back that one iteration and re-raises; the
    loop does **not** swallow errors because the brief explicitly excludes
    retry logic from this PR.
    """

    processed = 0
    while True:
        task = claim_next_task(session)
        if task is None:
            break
        try:
            run_echo(session, task)
        except Exception:
            session.rollback()
            logger.exception("echo run failed for task_id=%s", task.id)
            raise
        processed += 1
        logger.info("echoed task_id=%s", task.id)
    return processed


__all__ = [
    "ECHO_MODEL",
    "claim_next_task",
    "process_pending",
    "run_echo",
]
