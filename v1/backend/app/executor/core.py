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

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from ..adapters import (
    AdapterEvent,
    ClaudeCodeAdapter,
    resolve_cli_path,
    resolve_timeout,
)
from ..finalize import finalize_task
from ..models import Project, Run, RunEvent, Task, TaskEvent
from ..triage import TriageDecision, TriageError, triage_task
from ..verification import verify_run
from .git_workspace import GitWorkspaceError, prepare_task_branch


logger = logging.getLogger("niwa.executor")

ADAPTER_MODEL = "claude-code"

# PR-V1-23: terminal statuses used by ``_maybe_promote_parent`` to decide
# whether every subtask has settled. Kept in sync with SPEC §3 task states.
_TERMINAL_STATUSES = frozenset({"done", "failed", "cancelled"})


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

    # PR-V1-22: on a respond-triggered run (user_response event + prior
    # session_handle), resume the conversation with the user's text as
    # prompt. Missing either signal → fresh prompt + warning.
    resume_handle: str | None = None
    adapter_prompt = _build_prompt(task)
    user_response = _last_user_response_text(session, task.id)
    if user_response is not None:
        prev_handle = _last_run_session_handle(session, task.id)
        if prev_handle is not None:
            resume_handle = prev_handle
            adapter_prompt = user_response
            logger.info("resuming task_id=%s session=%s...", task.id, prev_handle[:8])
        else:
            logger.warning(
                "task_id=%s has user_response but no prior session_handle", task.id,
            )

    adapter = ClaudeCodeAdapter(
        cli_path=resolve_cli_path(),
        cwd=artifact_root or ".",
        prompt=adapter_prompt,
        timeout=resolve_timeout(),
        resume_handle=resume_handle,
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

    # PR-V1-22: persist the session handle even on failed runs so a
    # later respond can resume.
    if adapter.session_id is not None:
        run.session_handle = adapter.session_id
        session.commit()

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

    # PR-V1-13: safe-mode finalize runs on verified runs only. It is
    # best-effort — ``finalize_task`` swallows subprocess failures and
    # reports them on its return value, but we still guard against a
    # catastrophic exception (e.g. DB connection dropped) so the task
    # always reaches its terminal state below.
    if result.passed and project is not None:
        try:
            fin = finalize_task(session, run, task, project)
            logger.info(
                "finalize task_id=%s committed=%s pushed=%s pr_url=%s skipped=%s",
                task.id,
                fin.committed,
                fin.pushed,
                fin.pr_url,
                fin.commands_skipped,
            )
        except Exception:  # noqa: BLE001 — must never fail the run
            logger.exception("finalize crashed for task_id=%s", task.id)

    _finalize(
        session, task, run,
        outcome="verified" if result.passed else result.outcome,
        exit_code=exit_code,
        error_code=None if result.passed else result.error_code,
        pending_question=result.pending_question,
    )
    session.refresh(run)
    return run


def process_pending(session: Session) -> int:
    """Drain every ``queued`` task currently visible to this session.

    PR-V1-12b: every claimed task goes through ``triage_task`` before the
    adapter. The verdict branches the pipeline three ways:

    * ``execute`` → fall through to the existing ``run_adapter`` path.
    * ``split``   → materialize the subtasks, close the parent ``done``
      without ever spawning the adapter.
    * ``TriageError`` → synthesize a failed run with
      ``outcome="triage_failed"`` so the UI has something to render.
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
                "triage split task_id=%s into %d subtasks",
                task.id,
                len(decision.subtasks),
            )
            _apply_split(session, task, decision)
            processed += 1
            continue

        # ``run_adapter`` swallows adapter exceptions internally (see its
        # try/except/finally), so nothing we handle here would ever fire.
        run_adapter(session, task)
        processed += 1
        logger.info("ran adapter for task_id=%s", task.id)
    return processed


def _apply_split(session: Session, task: Task, decision: TriageDecision) -> None:
    """Materialize subtasks and log the split event; parent stays ``running``.

    SPEC §3 does not allow ``triage_split`` in the ``task_events.kind``
    enum, so the marker rides inside a ``kind="message"`` payload —
    this is the Opción B resolution agreed for 12b.

    PR-V1-23: the parent is NOT closed here. It stays ``running`` and
    is promoted to its aggregated terminal state by
    ``_maybe_promote_parent`` once every subtask has reached a
    terminal status.
    """

    subtasks: list[Task] = []
    for title in decision.subtasks:
        sub = Task(
            project_id=task.project_id,
            parent_task_id=task.id,
            title=title,
            description="",
            status="queued",
        )
        session.add(sub)
        subtasks.append(sub)
    session.flush()  # populate sub.id for the payload below

    session.add(
        TaskEvent(
            task_id=task.id,
            kind="message",
            message=None,
            payload_json=json.dumps(
                {
                    "event": "triage_split",
                    "subtask_ids": [s.id for s in subtasks],
                    "rationale": decision.rationale,
                }
            ),
        )
    )
    session.commit()


def _finalize_triage_failure(
    session: Session,
    task: Task,
    project: Project | None,
    *,
    reason: str,
) -> None:
    """Record a synthetic failed run for a task whose triage could not decide.

    The run never spawned the adapter, so ``exit_code`` stays ``None`` and
    no stream events are written. ``artifact_root`` falls back to empty
    when the project could not be loaded — the schema forbids ``NULL``.
    """

    now = datetime.now(timezone.utc)
    run = Run(
        task_id=task.id,
        status="failed",
        model=ADAPTER_MODEL,
        started_at=now,
        finished_at=now,
        outcome="triage_failed",
        artifact_root=project.local_path if project is not None else "",
        exit_code=None,
    )
    session.add(run)
    session.flush()

    session.add(
        RunEvent(
            run_id=run.id,
            event_type="error",
            payload_json=json.dumps({"reason": reason[:500]}),
        )
    )
    session.add(RunEvent(run_id=run.id, event_type="failed", payload_json=None))

    from_status = task.status
    task.status = "failed"
    session.add(
        TaskEvent(
            task_id=task.id,
            kind="verification",
            message=None,
            payload_json=json.dumps(
                {"error_code": "triage_failed", "outcome": "triage_failed"}
            ),
        )
    )
    session.add(
        TaskEvent(
            task_id=task.id,
            kind="status_changed",
            message=None,
            payload_json=json.dumps({"from": from_status, "to": "failed"}),
        )
    )
    session.commit()

    # PR-V1-23: triage failure also settles a subtask terminally. Without
    # this hook the parent of a split child that fails triage would be
    # stranded in ``running`` forever — the very bug parent promotion
    # exists to prevent, mirrored on the triage path.
    if task.parent_task_id is not None:
        _maybe_promote_parent(session, task.parent_task_id)


def _last_user_response_text(session: Session, task_id: int) -> str | None:
    """Text of the most recent ``message``/``user_response`` TaskEvent (PR-V1-22)."""

    stmt = (
        select(TaskEvent)
        .where(TaskEvent.task_id == task_id, TaskEvent.kind == "message")
        .order_by(TaskEvent.id.desc())
        .limit(1)
    )
    event = session.scalars(stmt).first()
    if event is None or not event.payload_json:
        return None
    try:
        payload = json.loads(event.payload_json)
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("event") != "user_response":
        return None
    text_value = payload.get("text")
    return text_value if isinstance(text_value, str) and text_value else None


def _last_run_session_handle(session: Session, task_id: int) -> str | None:
    """Most recent non-NULL ``session_handle`` for ``task_id`` (PR-V1-22)."""

    stmt = (
        select(Run.session_handle)
        .where(Run.task_id == task_id, Run.session_handle.is_not(None))
        .order_by(Run.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


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


def _maybe_promote_parent(session: Session, parent_id: int) -> None:
    """If every subtask of ``parent_id`` is terminal, update the parent.

    Aggregation (SPEC §3 statuses only):

    * any subtask ``failed``                          → parent ``failed``
    * all subtasks ``done``                           → parent ``done``
    * any ``cancelled`` and none ``failed``           → parent ``cancelled``
    * any subtask in ``waiting_input``/``queued``/
      ``running``                                     → no-op (not ready)

    Idempotent: if the parent is already terminal the call is a no-op, so
    two hermano subtasks finishing in parallel cannot corrupt the state.
    Best-effort: never raises; on any unexpected DB error the call logs
    a warning and returns so ``_finalize`` still settles the subtask.
    """

    try:
        children = session.execute(
            select(Task).where(Task.parent_task_id == parent_id)
        ).scalars().all()
        if not children:
            return  # defensive — parent with no subtasks should not hit here

        statuses = [c.status for c in children]
        if any(s not in _TERMINAL_STATUSES for s in statuses):
            return

        parent = session.get(Task, parent_id)
        if parent is None:
            return
        if parent.status in _TERMINAL_STATUSES:
            return  # already promoted — the sibling that won the race settled it

        if any(s == "failed" for s in statuses):
            new_status = "failed"
        elif all(s == "done" for s in statuses):
            new_status = "done"
        else:
            # Only cancelled + done remain once failed is ruled out.
            new_status = "cancelled"

        from_status = parent.status
        parent.status = new_status
        if new_status == "done":
            parent.completed_at = datetime.now(timezone.utc)

        session.add(TaskEvent(
            task_id=parent.id,
            kind="status_changed",
            message=None,
            payload_json=json.dumps({
                "from": from_status,
                "to": new_status,
                "reason": "subtasks_terminal",
            }),
        ))
        session.commit()
    except Exception:  # noqa: BLE001 — promotion must never sink _finalize
        logger.warning(
            "parent promotion failed for parent_id=%s", parent_id, exc_info=True,
        )


def _finalize(
    session: Session,
    task: Task,
    run: Run,
    *,
    outcome: str,
    exit_code: int | None,
    error_code: str | None = None,
    pending_question: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    # Three terminal buckets: ``verified`` → run completed + task done;
    # ``needs_input`` (PR-V1-19) → run failed + task parked in
    # ``waiting_input`` with ``pending_question`` populated; anything else
    # → run failed + task failed. Only the verified path clears the
    # lifecycle cleanly; ``needs_input`` is an intentional pause, not
    # a success.
    success = outcome == "verified"
    needs_input = outcome == "needs_input"

    run.finished_at = now
    run.exit_code = exit_code
    run.outcome = outcome
    run.status = "completed" if success else "failed"

    terminal = "completed" if success else "failed"
    session.add(RunEvent(run_id=run.id, event_type=terminal, payload_json=None))

    if success:
        new_status = "done"
    elif needs_input:
        new_status = "waiting_input"
    else:
        new_status = "failed"
    from_status = task.status
    task.status = new_status
    if success:
        task.completed_at = now
    if needs_input:
        task.pending_question = pending_question

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

    # PR-V1-23: once this subtask has settled, check whether the parent
    # is ready to be promoted. The hook is a no-op for top-level tasks
    # (no parent) and for mothers whose siblings are still non-terminal
    # — see ``_maybe_promote_parent``.
    if task.parent_task_id is not None:
        _maybe_promote_parent(session, task.parent_task_id)


__all__ = ["ADAPTER_MODEL", "claim_next_task", "process_pending", "run_adapter"]
