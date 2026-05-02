"""Executor pipeline — claim queued tasks and drive the Claude adapter.

* ``claim_next_task`` atomically flips the oldest ``queued`` task to
  ``triaging`` using ``BEGIN IMMEDIATE`` + conditional ``UPDATE``.
* ``run_adapter`` creates the ``Run``, streams ``AdapterEvent`` rows into
  ``run_events`` (one commit per event — see PR-V1-07 brief, batch is a
  follow-up tunable), and finalizes run+task based on ``adapter.outcome``.
* ``process_pending`` loops the two above until the queue is empty.

The adapter is pure subprocess + parse; this module owns every DB write.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from ..adapters import (
    AdapterEvent,
    ClaudeCodeAdapter,
    resolve_cli_path,
    resolve_timeout,
)
from ..deployments.service import trigger_deploy
from ..finalize import finalize_task
from ..models import (
    Attachment,
    Project,
    Run,
    RunEvent,
    Task,
    TaskEvent,
    TaskPlan,
    TaskReview,
)
from ..security.redaction import redact
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
            .values(status="triaging")
        )
        if result.rowcount == 0:
            session.commit()
            return None

        session.add(
            TaskEvent(
                task_id=task_id,
                kind="status_changed",
                message=None,
                payload_json=json.dumps({"from": "queued", "to": "triaging"}),
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
    _set_task_status(session, task, "executing", reason="adapter_start")

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
        branch_name = prepare_task_branch(
            artifact_root or ".",
            task,
            allow_dirty_existing_branch=bool(task.branch_name),
        )
    except GitWorkspaceError as exc:
        logger.warning("git setup failed for task_id=%s: %s", task.id, exc)
        session.add(
            RunEvent(
                run_id=run.id,
                event_type="error",
                payload_json=_event_payload(
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
    attachments = list(
        session.scalars(
            select(Attachment)
            .where(Attachment.task_id == task.id)
            .order_by(Attachment.id.asc())
        ).all()
    )
    adapter_prompt = _build_prompt(task, attachments)
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
                _record_run_pid(session, run, adapter.pid)
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
                    payload_json=_event_payload({"reason": str(exc)[:500]}),
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

    _set_task_status(session, task, "verifying", reason="verify_start")
    result = verify_run(
        session, run, task, project,
        cwd=artifact_root or ".",
        adapter_outcome=adapter_outcome,
        exit_code=exit_code,
    )
    run.verification_json = json.dumps(result.evidence)
    session.commit()

    review = None
    if result.outcome != "needs_input":
        _set_task_status(session, task, "reviewing", reason="review_start")
        review = _create_task_review(session, task, run, result)
        if result.passed and review.decision == "request_changes":
            if _handle_review_request_changes(session, task, run, project, review):
                session.refresh(run)
                return run

    # PR-V1-13: safe-mode finalize runs on verified runs only. It is
    # best-effort — ``finalize_task`` swallows subprocess failures and
    # reports them on its return value, but we still guard against a
    # catastrophic exception (e.g. DB connection dropped) so the task
    # always reaches its terminal state below.
    deploy_after_merge = False
    if (
        result.passed
        and project is not None
        and (review is None or review.decision == "approved")
    ):
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
            deploy_after_merge = fin.pr_merged
        except Exception:  # noqa: BLE001 — must never fail the run
            logger.exception("finalize crashed for task_id=%s", task.id)

    _finalize(
        session, task, run,
        outcome="verified" if result.passed else result.outcome,
        exit_code=exit_code,
        error_code=None if result.passed else result.error_code,
        pending_question=result.pending_question,
    )
    if result.passed and project is not None:
        _maybe_trigger_deploy(session, task, project, deploy_after_merge)
    session.refresh(run)
    return run


def process_pending(session: Session) -> int:
    """Drain every ``queued`` task currently visible to this session.

    PR-V1-12b: every claimed task goes through ``triage_task`` before the
    adapter. The verdict branches the pipeline three ways:

    * ``execute`` → fall through to the existing ``run_adapter`` path.
    * ``split``   → record subtasks; parent stays ``running`` and is
      promoted when all children reach a terminal state (PR-V1-23).
    * ``TriageError`` → synthesize a failed run with
      ``outcome="triage_failed"`` so the UI has something to render.
    """

    processed = 0
    while True:
        task = claim_next_task(session)
        if task is None:
            break

        project = session.get(Project, task.project_id)
        approved_plan = _latest_task_plan(session, task.id, status="approved")
        if approved_plan is not None:
            run_adapter(session, task)
            processed += 1
            logger.info("ran adapter for approved task_id=%s", task.id)
            continue

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
            _set_task_status(session, task, "executing", reason="triage_split")
            _apply_split(session, task, decision)
            processed += 1
            continue

        _set_task_status(session, task, "planning", reason="plan_start")
        approval_mode = (
            getattr(project, "plan_approval_mode", "auto") if project else "auto"
        ) or "auto"
        plan = _create_task_plan(
            session,
            task,
            status="ready" if approval_mode == "manual" else "approved",
        )
        if approval_mode == "manual":
            _set_task_status(
                session,
                task,
                "waiting_approval",
                reason="plan_waiting_approval",
            )
            logger.info("task_id=%s waiting for plan approval plan_id=%s", task.id, plan.id)
            processed += 1
            continue

        # ``run_adapter`` swallows adapter exceptions internally (see its
        # try/except/finally), so nothing we handle here would ever fire.
        run_adapter(session, task)
        processed += 1
        logger.info("ran adapter for task_id=%s", task.id)
    return processed


def _set_task_status(
    session: Session,
    task: Task,
    new_status: str,
    *,
    reason: str | None = None,
) -> None:
    """Set task status and append the matching ``status_changed`` event."""

    from_status = task.status
    if from_status == new_status:
        return
    task.status = new_status
    payload: dict[str, object] = {"from": from_status, "to": new_status}
    if reason:
        payload["reason"] = reason
    session.add(
        TaskEvent(
            task_id=task.id,
            kind="status_changed",
            message=None,
            payload_json=json.dumps(payload),
        )
    )
    session.commit()


def _latest_task_plan(
    session: Session,
    task_id: int,
    *,
    status: str | None = None,
) -> TaskPlan | None:
    query = session.query(TaskPlan).filter(TaskPlan.task_id == task_id)
    if status is not None:
        query = query.filter(TaskPlan.status == status)
    return query.order_by(TaskPlan.id.desc()).first()


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


def _create_task_plan(
    session: Session,
    task: Task,
    *,
    status: str = "approved",
) -> TaskPlan:
    """Persist a deterministic JSON plan before code execution begins."""

    payload = {
        "summary": f"Execute task: {task.title}",
        "steps": [
            "Inspect the assigned task and attached context.",
            "Apply the smallest code or content change that satisfies the task.",
            "Run verification and finalize only if evidence passes.",
        ],
        "risks": [],
        "planner": "fake-json",
    }
    plan = TaskPlan(
        task_id=task.id,
        status=status,
        summary=payload["summary"],
        steps_json=json.dumps(payload["steps"]),
        risks_json=json.dumps(payload["risks"]),
        planner="fake-json",
        raw_json=json.dumps(payload, sort_keys=True),
    )
    session.add(plan)
    session.flush()
    session.add(
        TaskEvent(
            task_id=task.id,
            kind="message",
            message=None,
            payload_json=json.dumps(
                {
                    "event": "plan_created",
                    "plan_id": plan.id,
                    "planner": plan.planner,
                    "status": plan.status,
                }
            ),
        )
    )
    session.commit()
    session.refresh(plan)
    return plan


def _create_task_review(session: Session, task: Task, run: Run, result) -> TaskReview:
    """Persist a deterministic JSON review after verification completes."""

    iteration = _next_review_iteration(session, task.id)
    decision = _fake_review_decision(iteration)
    if decision is None:
        decision = "approved" if result.passed else "request_changes"
    findings = [] if result.passed else [
        f"Verification did not pass: {result.error_code or result.outcome}"
    ]
    payload = {
        "decision": decision,
        "summary": (
            "Review requested changes before finalize."
            if decision == "request_changes" and result.passed
            else
            "Verification passed; finalize is allowed."
            if result.passed
            else "Verification failed; changes are required before finalize."
        ),
        "findings": findings,
        "iteration": iteration,
        "reviewer": "fake-json",
        "verification": result.evidence,
    }
    review = TaskReview(
        task_id=task.id,
        run_id=run.id,
        decision=decision,
        iteration=iteration,
        summary=payload["summary"],
        findings_json=json.dumps(findings),
        reviewer="fake-json",
        raw_json=json.dumps(payload, sort_keys=True),
    )
    session.add(review)
    session.flush()
    session.add(
        TaskEvent(
            task_id=task.id,
            kind="message",
            message=None,
            payload_json=json.dumps(
                {
                    "event": "review_completed",
                    "review_id": review.id,
                    "decision": review.decision,
                }
            ),
        )
    )
    session.add(
        RunEvent(
            run_id=run.id,
            event_type="review",
            payload_json=_event_payload(payload, sort_keys=True),
        )
    )
    session.commit()
    session.refresh(review)
    return review


def _next_review_iteration(session: Session, task_id: int) -> int:
    latest = (
        session.query(TaskReview)
        .filter(TaskReview.task_id == task_id)
        .order_by(TaskReview.iteration.desc(), TaskReview.id.desc())
        .first()
    )
    return 1 if latest is None else latest.iteration + 1


def _fake_review_decision(iteration: int) -> str | None:
    raw = os.environ.get("NIWA_FAKE_REVIEW_DECISIONS", "").strip()
    if not raw:
        return None
    decisions = [item.strip() for item in raw.split(",") if item.strip()]
    if iteration > len(decisions):
        return None
    decision = decisions[iteration - 1]
    if decision not in {"approved", "request_changes"}:
        return None
    return decision


def _handle_review_request_changes(
    session: Session,
    task: Task,
    run: Run,
    project: Project | None,
    review: TaskReview,
) -> bool:
    """Return True when the task was requeued or exhausted by review."""

    max_iterations = (
        getattr(project, "max_review_iterations", 1) if project else 1
    )
    if review.iteration <= max_iterations:
        now = datetime.now(timezone.utc)
        run.finished_at = now
        run.status = "completed"
        run.outcome = "review_request_changes"
        session.add(
            RunEvent(
                run_id=run.id,
                event_type="review_request_changes",
                payload_json=_event_payload(
                    {
                        "review_id": review.id,
                        "iteration": review.iteration,
                        "max_review_iterations": max_iterations,
                    }
                ),
            )
        )
        session.commit()
        _set_task_status(
            session,
            task,
            "queued",
            reason="review_request_changes",
        )
        return True

    _finalize(
        session,
        task,
        run,
        outcome="review_changes_exhausted",
        exit_code=run.exit_code,
        error_code="review_changes_exhausted",
    )
    return True


def _maybe_trigger_deploy(
    session: Session,
    task: Task,
    project: Project,
    deploy_after_merge: bool,
) -> None:
    trigger = getattr(project, "deploy_trigger", "manual") or "manual"
    should_deploy = trigger == "on_done" or (
        trigger == "on_merge" and deploy_after_merge
    )
    if not should_deploy:
        return
    try:
        deployment = trigger_deploy(session, project, task_id=task.id)
        logger.info(
            "auto deploy task_id=%s deployment_id=%s trigger=%s status=%s",
            task.id,
            deployment.id,
            trigger,
            deployment.status,
        )
    except Exception:  # noqa: BLE001 — deployment must not unsettle the task
        logger.exception("auto deploy failed for task_id=%s trigger=%s", task.id, trigger)


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
            payload_json=_event_payload({"reason": reason[:500]}),
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
    )
    for event in session.scalars(stmt).all():
        if not event.payload_json:
            continue
        try:
            payload = json.loads(event.payload_json)
        except ValueError:
            continue
        if not isinstance(payload, dict) or payload.get("event") != "user_response":
            continue
        text_value = payload.get("text")
        return text_value if isinstance(text_value, str) and text_value else None
    return None


def _last_run_session_handle(session: Session, task_id: int) -> str | None:
    """Most recent non-NULL ``session_handle`` for ``task_id`` (PR-V1-22)."""

    stmt = (
        select(Run.session_handle)
        .where(Run.task_id == task_id, Run.session_handle.is_not(None))
        .order_by(Run.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def _build_prompt(task: Task, attachments: list[Attachment] | None = None) -> str:
    """Minimal prompt: title + description + attachment paths (relative)."""

    parts: list[str] = []
    if task.title:
        parts.append(f"# Task: {task.title}")
    if task.description:
        parts.append(task.description)
    if attachments:
        # Render paths relative to the project root so the adapter (whose
        # cwd == ``project.local_path``) can ``Read`` them as context.
        local_path = task.project.local_path if task.project is not None else ""
        lines = ["## Attached files (read these as context):"]
        for a in attachments:
            rel = (
                os.path.relpath(a.storage_path, local_path)
                if local_path
                else a.storage_path
            )
            lines.append(f"- `{rel}`")
        parts.append("\n".join(lines))
    return "\n\n".join(parts) if parts else "Complete the assigned task."


def _event_payload(payload: object, *, sort_keys: bool = False) -> str:
    return redact(json.dumps(payload, sort_keys=sort_keys))


def _record_run_pid(session: Session, run: Run, pid: int | None) -> None:
    if pid is None or run.pid == pid:
        return
    run.pid = pid
    session.commit()


def _write_event(session: Session, run: Run, event: AdapterEvent) -> None:
    session.add(
        RunEvent(
            run_id=run.id,
            event_type=event.kind,
            payload_json=_event_payload(event.payload),
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
