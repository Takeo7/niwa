"""Canonical state machines for tasks.status and backend_runs.status.

PR-02 — Niwa v0.2

These are pure functions with no I/O.  Every status transition in the
application must go through the validation helpers exposed here.

Transition maps come directly from docs/SPEC-v0.2.md § PR-02 and
docs/state-machines.md.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── tasks.status ──────────────────────────────────────────────────────

TASK_STATUSES = frozenset({
    'inbox', 'pendiente', 'en_progreso', 'bloqueada',
    'revision', 'waiting_input', 'hecha', 'archivada',
})

TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    'inbox':         frozenset({'pendiente'}),
    'pendiente':     frozenset({'en_progreso', 'bloqueada', 'archivada'}),
    'en_progreso':   frozenset({'waiting_input', 'revision', 'bloqueada', 'hecha', 'archivada'}),
    'waiting_input': frozenset({'pendiente', 'archivada'}),
    'revision':      frozenset({'pendiente', 'hecha', 'archivada'}),
    'bloqueada':     frozenset({'pendiente', 'archivada'}),
    # Terminal states — no outgoing transitions
    'hecha':         frozenset(),
    'archivada':     frozenset(),
}

# ── backend_runs.status ───────────────────────────────────────────────

RUN_STATUSES = frozenset({
    'queued', 'starting', 'running',
    'waiting_approval', 'waiting_input',
    'succeeded', 'failed', 'cancelled', 'timed_out', 'rejected',
})

RUN_TRANSITIONS: dict[str, frozenset[str]] = {
    'queued':           frozenset({'starting', 'failed'}),
    'starting':         frozenset({'running', 'waiting_approval', 'failed'}),
    'running':          frozenset({'waiting_approval', 'waiting_input',
                                   'succeeded', 'failed', 'cancelled', 'timed_out'}),
    'waiting_approval': frozenset({'running', 'rejected'}),
    'waiting_input':    frozenset({'queued', 'cancelled'}),
    # Terminal states
    'succeeded':        frozenset(),
    'failed':           frozenset(),
    'cancelled':        frozenset(),
    'timed_out':        frozenset(),
    'rejected':         frozenset(),
}


class InvalidTransitionError(Exception):
    """Raised when a status transition is not allowed by the state machine."""

    def __init__(self, entity: str, from_status: str, to_status: str):
        self.entity = entity
        self.from_status = from_status
        self.to_status = to_status
        allowed = (TASK_TRANSITIONS if entity == 'task' else RUN_TRANSITIONS).get(from_status, frozenset())
        super().__init__(
            f"Invalid {entity} transition: {from_status!r} → {to_status!r}. "
            f"Allowed from {from_status!r}: {sorted(allowed) if allowed else '(terminal state)'}"
        )


# ── Pure validation helpers ───────────────────────────────────────────

def can_transition_task(from_status: str, to_status: str) -> bool:
    """Return True if *from_status → to_status* is a valid task transition."""
    return to_status in TASK_TRANSITIONS.get(from_status, frozenset())


def can_transition_run(from_status: str, to_status: str) -> bool:
    """Return True if *from_status → to_status* is a valid run transition."""
    return to_status in RUN_TRANSITIONS.get(from_status, frozenset())


def assert_task_transition(from_status: str, to_status: str) -> None:
    """Raise :class:`InvalidTransitionError` if the task transition is invalid."""
    if not can_transition_task(from_status, to_status):
        raise InvalidTransitionError('task', from_status, to_status)


def assert_run_transition(from_status: str, to_status: str) -> None:
    """Raise :class:`InvalidTransitionError` if the run transition is invalid."""
    if not can_transition_run(from_status, to_status):
        raise InvalidTransitionError('run', from_status, to_status)


# ── Authorised override: reject ──────────────────────────────────────

def force_reject_task(task_id: str, reason: str, *, user: str = 'unknown') -> dict:
    """Bypass the state machine to reject a task marked as *hecha*.

    Excepción autorizada a la state machine.  Reject es un override humano
    explícito para tareas marcadas como hechas por error.  NO usar para
    flujos automáticos — cualquier código que necesite transicionar desde
    *hecha* debe revisar si esa transición debería ser válida en la state
    machine en lugar de bypasear.

    Returns an audit record dict (caller is responsible for persisting it).
    """
    ts = datetime.now(timezone.utc).isoformat()
    audit = {
        'action': 'force_reject_task',
        'task_id': task_id,
        'from_status': 'hecha',
        'to_status': 'pendiente',
        'reason': reason,
        'user': user,
        'timestamp': ts,
    }
    logger.warning(
        "force_reject_task: task=%s reason=%r user=%s ts=%s — bypassing state machine (hecha → pendiente)",
        task_id, reason, user, ts,
    )
    return audit
