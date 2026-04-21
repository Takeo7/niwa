"""Executor pipeline — claim queued tasks and drive the Claude adapter.

* ``claim_next_task`` atomically flips the oldest ``queued`` task to
  ``running`` using ``BEGIN IMMEDIATE`` + conditional ``UPDATE``.
* ``run_adapter`` creates the ``Run``, streams ``AdapterEvent`` rows into
  ``run_events`` (one commit per event — see PR-V1-07 brief, batch is a
  follow-up tunable), and finalizes run+task based on ``adapter.outcome``.
* ``process_pending`` loops the two above until the queue is empty.

The adapter is pure subprocess + parse; this module owns every DB write.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text, update
from sqlalchemy.orm import Session

from ..adapters import (
    AdapterEvent,
    ClaudeCodeAdapter,
    resolve_cli_path,
    resolve_timeout,
)
from ..models import Project, Run, RunEvent, Task, TaskEvent
from ..verification import verify_run
from .git_workspace import GitWorkspaceError, prepare_task_branch


logger = logging.getLogger("niwa.executor")

ADAPTER_MODEL = "claude-code"


def claim_next_task(session: Session) -> Task | None:
    """Atomically take ownership of the oldest ``queued`` task."""

    if session.in_transaction():
        session.rollback()
    session.execute(text("BEGIN IMMEDIATE"))

    try:
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

    return session.get(Task, task_id)


def run_adapter(session: Session, task: Task) -> Run:
    """Drive the Claude adapter for ``task`` and persist every step.

    Maps adapter outcomes to terminal state:

    * ``cli_ok``            → run ``completed``, task ``done``.
    * ``cli_nonzero_exit``  → run ``failed``, task ``failed``.
    * ``cli_not_found``     → run ``failed``, task ``failed``.
    * ``timeout``           → run ``failed``, task ``failed``.

    Adapter exceptions surface as ``adapter_exception`` so the run never
    sticks in ``running``.
    """

    project = session.get(Project, task.project_id)
    artifact_root = project.local_path if project is not None else ""

    run = Run(
        task_id=task.id,
        status="running",
        model=ADAPTER_MODEL,
        started_at=datetime.now(timezone.utc),
        artifact_root=artifact_root,
    )
    session.add(run)
    session.flush()
    session.add(RunEvent(run_id=run.id, event_type="started", payload_json=None))
    session.commit()

    # PR-V1-08: prepare the per-task branch BEFORE the adapter spawns. On
    # failure we skip the adapter entirely and finalize with
    # ``git_setup_failed`` — the task never gets to mutate the working
    # tree, and ``task.branch_name`` stays ``None``.
    try:
        branch_name = prepare_task_branch(artifact_root or ".", task)
    except GitWorkspaceError as exc:
        logger.warning("git setup failed for task_id=%s: %s", task.id, exc)
        session.add(
            RunEvent(
                run_id=run.id,
                event_type="error",
                payload_json=json.dumps(
                    {"reason": f"git_setup_failed: {str(exc)[:400]}"}
                ),
            )
        )
        session.commit()
        _finalize(session, task, run, outcome="git_setup_failed", exit_code=None)
        session.refresh(run)
        return run

    task.branch_name = branch_name
    session.commit()

    adapter = ClaudeCodeAdapter(
        cli_path=resolve_cli_path(),
        cwd=artifact_root or ".",
        prompt=_build_prompt(task),
        timeout=resolve_timeout(),
    )

    try:
        try:
            for event in adapter.iter_events():
                _write_event(session, run, event)
            adapter.wait()
            adapter_outcome = adapter.outcome or "cli_ok"
            exit_code = adapter.exit_code
        except Exception as exc:  # noqa: BLE001 — must always settle the run
            logger.exception("adapter crashed for task_id=%s", task.id)
            adapter_outcome = "adapter_exception"
            exit_code = None
            session.add(
                RunEvent(
                    run_id=run.id,
                    event_type="error",
                    payload_json=json.dumps({"reason": str(exc)[:500]}),
                )
            )
            session.commit()
    finally:
        # Guarantee the subprocess is reaped even if ``iter_events`` or
        # ``_write_event`` raised before ``adapter.wait()`` ran — otherwise
        # the ``Popen`` outlives the run and accumulates as a zombie in a
        # long-running daemon.
        adapter.close()

    # PR-V1-11a: adapter failures bypass the verifier (outcome flows
    # through unchanged); only ``cli_ok`` runs the evidence checks.
    if adapter_outcome != "cli_ok":
        _finalize(session, task, run, outcome=adapter_outcome, exit_code=exit_code)
        session.refresh(run)
        return run

    result = verify_run(
        session, run, task, project,
        cwd=artifact_root or ".",
        adapter_outcome=adapter_outcome,
        exit_code=exit_code,
    )
    run.verification_json = json.dumps(result.evidence)
    session.commit()
    _finalize(
        session, task, run,
        outcome="verified" if result.passed else result.outcome,
        exit_code=exit_code,
        error_code=None if result.passed else result.error_code,
    )
    session.refresh(run)
    return run


def process_pending(session: Session) -> int:
    """Drain every ``queued`` task currently visible to this session."""

    processed = 0
    while True:
        task = claim_next_task(session)
        if task is None:
            break
        # ``run_adapter`` swallows adapter exceptions internally (see its
        # try/except/finally), so nothing we handle here would ever fire.
        run_adapter(session, task)
        processed += 1
        logger.info("ran adapter for task_id=%s", task.id)
    return processed


def _build_prompt(task: Task) -> str:
    """Minimal prompt: title + description. System-prompt rules ship later."""

    parts: list[str] = []
    if task.title:
        parts.append(f"# Task: {task.title}")
    if task.description:
        parts.append(task.description)
    return "\n\n".join(parts) if parts else "Complete the assigned task."


def _write_event(session: Session, run: Run, event: AdapterEvent) -> None:
    session.add(
        RunEvent(
            run_id=run.id,
            event_type=event.kind,
            payload_json=json.dumps(event.payload),
        )
    )
    session.commit()


def _finalize(
    session: Session,
    task: Task,
    run: Run,
    *,
    outcome: str,
    exit_code: int | None,
    error_code: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    # PR-V1-11a: only ``verified`` is success; all other outcomes fail.
    success = outcome == "verified"

    run.finished_at = now
    run.exit_code = exit_code
    run.outcome = outcome
    run.status = "completed" if success else "failed"

    terminal = "completed" if success else "failed"
    session.add(RunEvent(run_id=run.id, event_type=terminal, payload_json=None))

    new_status = "done" if success else "failed"
    from_status = task.status
    task.status = new_status
    if success:
        task.completed_at = now

    session.add(
        TaskEvent(
            task_id=task.id,
            kind="status_changed",
            message=None,
            payload_json=json.dumps({"from": from_status, "to": new_status}),
        )
    )
    if error_code is not None:
        session.add(TaskEvent(
            task_id=task.id,
            kind="verification",
            message=None,
            payload_json=json.dumps({"error_code": error_code, "outcome": outcome}),
        ))
    session.commit()


__all__ = ["ADAPTER_MODEL", "claim_next_task", "process_pending", "run_adapter"]
