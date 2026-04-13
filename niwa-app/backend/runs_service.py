"""Runs service — PR-04 Niwa v0.2.

Manages the lifecycle of ``backend_runs``: creation, status transitions,
heartbeat updates, event logging, and linking (fallback / resume / retry).
"""

import json
import logging
import uuid
from datetime import datetime, timezone

import state_machines

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def create_run(task_id: str, routing_decision_id: str,
               backend_profile_id: str, conn, *,
               previous_run_id: str | None = None,
               relation_type: str | None = None,
               backend_kind: str | None = None,
               runtime_kind: str | None = None,
               model_resolved: str | None = None,
               artifact_root: str | None = None) -> dict:
    """Create a new ``backend_run`` record with status 'queued'.

    Returns the created row as a dict.
    """
    run_id = str(uuid.uuid4())
    now = _now_iso()

    conn.execute(
        "INSERT INTO backend_runs "
        "(id, task_id, routing_decision_id, previous_run_id, relation_type, "
        " backend_profile_id, backend_kind, runtime_kind, model_resolved, "
        " session_handle, status, capability_snapshot_json, budget_snapshot_json, "
        " observed_usage_signals_json, heartbeat_at, started_at, finished_at, "
        " outcome, exit_code, error_code, artifact_root, created_at, updated_at) "
        "VALUES (?,?,?,?,?, ?,?,?,?, NULL,'queued',NULL,NULL, NULL,NULL,NULL,NULL, "
        "        NULL,NULL,NULL,?, ?,?)",
        (
            run_id, task_id, routing_decision_id, previous_run_id,
            relation_type, backend_profile_id, backend_kind, runtime_kind,
            model_resolved, artifact_root, now, now,
        ),
    )
    conn.commit()
    logger.info("Created backend_run %s for task %s (status=queued)", run_id, task_id)

    return _get_run(run_id, conn)


def transition_run(run_id: str, new_status: str, conn, **kwargs) -> dict:
    """Transition a run to *new_status*, enforcing the state machine.

    Optional keyword arguments are written as column updates:
      - session_handle, outcome, exit_code, error_code, started_at, finished_at,
        observed_usage_signals_json
    """
    row = _get_run(run_id, conn)
    old_status = row["status"]
    state_machines.assert_run_transition(old_status, new_status)

    now = _now_iso()
    sets = ["status = ?", "updated_at = ?"]
    params: list = [new_status, now]

    allowed_columns = {
        "session_handle", "outcome", "exit_code", "error_code",
        "started_at", "finished_at", "observed_usage_signals_json",
    }
    for col, val in kwargs.items():
        if col in allowed_columns:
            sets.append(f"{col} = ?")
            params.append(val)

    params.append(run_id)
    conn.execute(
        f"UPDATE backend_runs SET {', '.join(sets)} WHERE id = ?",
        params,
    )
    conn.commit()
    logger.info("Run %s: %s → %s", run_id, old_status, new_status)

    return _get_run(run_id, conn)


def record_heartbeat(run_id: str, conn) -> None:
    """Update ``heartbeat_at`` for a running execution."""
    now = _now_iso()
    conn.execute(
        "UPDATE backend_runs SET heartbeat_at = ?, updated_at = ? WHERE id = ?",
        (now, now, run_id),
    )
    conn.commit()


def record_event(run_id: str, event_type: str, conn, *,
                 message: str | None = None,
                 payload_json: str | None = None) -> str:
    """Insert a row into ``backend_run_events``.

    Returns the event id.
    """
    event_id = str(uuid.uuid4())
    now = _now_iso()
    conn.execute(
        "INSERT INTO backend_run_events "
        "(id, backend_run_id, event_type, message, payload_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (event_id, run_id, event_type, message, payload_json, now),
    )
    conn.commit()
    return event_id


def finish_run(run_id: str, outcome: str, conn, *,
               exit_code: int | None = None,
               error_code: str | None = None,
               observed_usage_signals_json: str | None = None) -> dict:
    """Mark a run as finished with the given outcome.

    Determines the terminal status from outcome:
      - 'success' → 'succeeded'
      - 'failure' → 'failed'
      - 'cancelled' → 'cancelled'
      - 'timed_out' → 'timed_out'
    """
    outcome_to_status = {
        "success": "succeeded",
        "failure": "failed",
        "cancelled": "cancelled",
        "timed_out": "timed_out",
    }
    new_status = outcome_to_status.get(outcome)
    if new_status is None:
        raise ValueError(
            f"Unknown outcome {outcome!r}. "
            f"Valid: {sorted(outcome_to_status)}"
        )

    return transition_run(
        run_id, new_status, conn,
        outcome=outcome,
        exit_code=exit_code,
        error_code=error_code,
        finished_at=_now_iso(),
        observed_usage_signals_json=observed_usage_signals_json,
    )


def register_artifact(task_id: str, run_id: str, artifact_type: str,
                      path: str, conn, *,
                      size_bytes: int | None = None,
                      sha256: str | None = None) -> str:
    """Insert a row into the ``artifacts`` table. Returns the artifact id."""
    artifact_id = str(uuid.uuid4())
    now = _now_iso()
    conn.execute(
        "INSERT INTO artifacts "
        "(id, task_id, backend_run_id, artifact_type, path, size_bytes, sha256, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (artifact_id, task_id, run_id, artifact_type, path, size_bytes, sha256, now),
    )
    conn.commit()
    return artifact_id


def update_session_handle(run_id: str, session_handle: str, conn) -> None:
    """Set the ``session_handle`` column on a run.

    Used by the adapter to persist the CLI session id after the run
    has already transitioned to 'running' (running→running is not
    a valid state transition, so we update the column directly).
    """
    now = _now_iso()
    conn.execute(
        "UPDATE backend_runs SET session_handle = ?, updated_at = ? WHERE id = ?",
        (session_handle, now, run_id),
    )
    conn.commit()


def _get_run(run_id: str, conn) -> dict:
    """Fetch a single backend_run as a dict. Raises if not found."""
    row = conn.execute(
        "SELECT * FROM backend_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"backend_run not found: {run_id}")
    return dict(row)
