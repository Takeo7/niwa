"""Approval service — PR-05 Niwa v0.2.

Manages approval gates: creation, resolution, and querying.
Approvals block task execution until a human resolves them.

When the capability service detects a policy violation at runtime,
the adapter creates an approval via ``request_approval()``.  The
run transitions to ``waiting_approval`` and the Claude process is
killed.

When a human later resolves the approval via ``resolve_approval()``,
the caller is responsible for creating a new ``backend_run`` with
``relation_type='resume'`` and the prior run's ``session_handle``
(see note 4 in PR-05 spec).
"""

import json
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ── Create ───────────────────────────────────────────────────────

def request_approval(task_id: str, backend_run_id: str,
                     approval_type: str, reason: str,
                     risk_level: str, conn) -> dict:
    """Create a pending approval request.

    Parameters:
        task_id:         The task being executed.
        backend_run_id:  The run that triggered the approval.
        approval_type:   Trigger type (e.g. ``shell_not_whitelisted``,
                         ``deletion``, ``filesystem_write_outside_scope``).
        reason:          Human-readable explanation.
        risk_level:      ``low``, ``medium``, ``high``, or ``critical``.
        conn:            sqlite3 connection.

    Returns the created approval row as a dict.
    """
    approval_id = str(uuid.uuid4())
    now = _now_iso()

    conn.execute(
        "INSERT INTO approvals "
        "(id, task_id, backend_run_id, approval_type, reason, "
        " risk_level, status, requested_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
        (approval_id, task_id, backend_run_id, approval_type,
         reason, risk_level, now),
    )
    conn.commit()

    logger.info(
        "Created approval %s for task %s run %s (type=%s, risk=%s)",
        approval_id, task_id, backend_run_id, approval_type, risk_level,
    )

    return _get_approval(approval_id, conn)


# ── Query ────────────────────────────────────────────────────────

def get_approval(approval_id: str, conn) -> dict | None:
    """Fetch a single approval by id.  Returns ``None`` if not found."""
    row = conn.execute(
        "SELECT * FROM approvals WHERE id = ?", (approval_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def list_approvals(conn, *, status: str | None = None,
                   task_id: str | None = None) -> list[dict]:
    """List approvals, optionally filtered by status and/or task_id.

    Returns a list of dicts ordered by ``requested_at DESC``.
    """
    clauses: list[str] = []
    params: list = []

    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if task_id is not None:
        clauses.append("task_id = ?")
        params.append(task_id)

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM approvals{where} ORDER BY requested_at DESC",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


# ── Resolve ──────────────────────────────────────────────────────

def resolve_approval(approval_id: str, status: str, resolved_by: str,
                     conn, *, resolution_note: str | None = None) -> dict:
    """Resolve a pending approval.

    Parameters:
        approval_id:     The approval to resolve.
        status:          ``approved`` or ``rejected``.
        resolved_by:     Identifier of the human who resolved it.
        conn:            sqlite3 connection.
        resolution_note: Optional free-text note.

    Idempotent: if the approval is already resolved with the **same**
    status, returns the existing row without error.  If it's resolved
    with a **different** status, raises ``ValueError``.

    Returns the updated approval row as a dict.
    """
    if status not in ("approved", "rejected"):
        raise ValueError(
            f"Invalid approval status {status!r}. "
            f"Must be 'approved' or 'rejected'."
        )

    existing = _get_approval(approval_id, conn)
    if existing is None:
        raise LookupError(f"Approval not found: {approval_id}")

    current_status = existing["status"]

    # Idempotent: same resolution is a no-op
    if current_status == status:
        logger.info(
            "Approval %s already resolved as %s — idempotent no-op",
            approval_id, status,
        )
        return existing

    # Already resolved with a different status — conflict
    if current_status in ("approved", "rejected"):
        raise ValueError(
            f"Approval {approval_id} already resolved as "
            f"{current_status!r}, cannot change to {status!r}."
        )

    # Resolve
    now = _now_iso()
    conn.execute(
        "UPDATE approvals SET status = ?, resolved_at = ?, "
        "resolved_by = ?, resolution_note = ? WHERE id = ?",
        (status, now, resolved_by, resolution_note, approval_id),
    )
    conn.commit()

    logger.info(
        "Resolved approval %s as %s by %s",
        approval_id, status, resolved_by,
    )

    return _get_approval(approval_id, conn)


# ── Internal ─────────────────────────────────────────────────────

def _get_approval(approval_id: str, conn) -> dict:
    """Fetch an approval row.  Raises ``LookupError`` if not found."""
    row = conn.execute(
        "SELECT * FROM approvals WHERE id = ?", (approval_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"Approval not found: {approval_id}")
    return dict(row)
