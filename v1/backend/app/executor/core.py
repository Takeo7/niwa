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
from ..triage import TriageDecision, TriageError, triage_task
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
    """Drain every ``queued`` task visible to this session.

    PR-V1-12 inserts the triage stage between ``claim_next_task`` and
    ``run_adapter``: ``execute`` -> normal pipeline, ``split`` -> parent
    ``done`` + subtasks queued, ``TriageError`` -> ``triage_failed``.
    """

    processed = 0
    while True:
        task = claim_next_task(session)
        if task is None:
            break
        project = session.get(Project, task.project_id)

        try:
            decision = triage_task(project, task)
        except TriageError as exc:
            logger.warning("triage failed for task_id=%s: %s", task.id, exc)
            _finalize_triage_failure(session, task, project, reason=str(exc))
            processed += 1
            continue

        if decision.kind == "split":
            logger.info(
                "triage split for task_id=%s into %d subtasks",
                task.id, len(decision.subtasks),
            )
            _apply_split(session, task, decision)
            processed += 1
            continue

        # ``run_adapter`` swallows adapter exceptions internally.
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


def _apply_split(
    session: Session, task: Task, decision: TriageDecision
) -> None:
    """Close the parent and enqueue the triage-produced subtasks.

    SPEC §3 fixes ``task_events.kind`` to a closed enum, so the
    ``triage_split`` marker lives in the payload of a ``message`` event.
    """

    subtasks = [
        Task(
            project_id=task.project_id, parent_task_id=task.id,
            title=title, description="", status="queued",
        )
        for title in decision.subtasks
    ]
    for s in subtasks:
        session.add(s)
    session.flush()

    from_status = task.status
    task.status = "done"
    task.completed_at = datetime.now(timezone.utc)
    session.add(TaskEvent(
        task_id=task.id, kind="message",
        payload_json=json.dumps({
            "event": "triage_split",
            "subtask_ids": [s.id for s in subtasks],
            "rationale": decision.rationale,
        }),
    ))
    session.add(TaskEvent(
        task_id=task.id, kind="status_changed",
        payload_json=json.dumps({"from": from_status, "to": "done"}),
    ))
    session.commit()


def _finalize_triage_failure(
    session: Session, task: Task, project: Project | None, *, reason: str
) -> None:
    """Terminal ``triage_failed`` path: synthetic Run + verification event."""

    now = datetime.now(timezone.utc)
    run = Run(
        task_id=task.id, status="failed", model=ADAPTER_MODEL,
        started_at=now, finished_at=now, exit_code=None,
        outcome="triage_failed",
        artifact_root=project.local_path if project is not None else "",
    )
    session.add(run)
    session.flush()
    session.add(RunEvent(
        run_id=run.id, event_type="error",
        payload_json=json.dumps({"reason": reason[:500]}),
    ))
    session.add(RunEvent(run_id=run.id, event_type="failed", payload_json=None))

    from_status = task.status
    task.status = "failed"
    session.add(TaskEvent(
        task_id=task.id, kind="status_changed",
        payload_json=json.dumps({"from": from_status, "to": "failed"}),
    ))
    session.add(TaskEvent(
        task_id=task.id, kind="verification",
        payload_json=json.dumps(
            {"error_code": "triage_failed", "outcome": "triage_failed"}
        ),
    ))
    session.commit()


__all__ = ["ADAPTER_MODEL", "claim_next_task", "process_pending", "run_adapter"]
