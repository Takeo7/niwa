"""Helpers for the SSE ``GET /api/runs/{run_id}/events`` endpoint (PR-V1-09).

Pure formatters + synchronous loaders. The async generator in
``app.api.runs`` wraps the loaders in ``asyncio.to_thread`` so the
project stays on synchronous ``Session`` (no AsyncSession).

``payload_json`` is stored as a JSON string in DB; we re-parse it so the
SSE ``data`` field carries a proper JSON object (not an escaped string).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Run, RunEvent


TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})


@dataclass(frozen=True)
class RunSnapshot:
    """Minimal view of a ``Run`` used to build the ``eos`` frame."""

    id: int
    status: str
    exit_code: int | None
    outcome: str | None


def run_exists(session: Session, run_id: int) -> bool:
    """``True`` when a ``Run`` with ``run_id`` exists."""

    return session.scalar(select(Run.id).where(Run.id == run_id)) is not None


def load_run_snapshot(session: Session, run_id: int) -> RunSnapshot | None:
    """Return a ``RunSnapshot`` or ``None`` if the run disappeared."""

    row = session.get(Run, run_id)
    if row is None:
        return None
    return RunSnapshot(
        id=row.id,
        status=row.status,
        exit_code=row.exit_code,
        outcome=row.outcome,
    )


def load_events_since(
    session: Session, run_id: int, last_id: int
) -> list[RunEvent]:
    """Return events for ``run_id`` with ``id > last_id``, ASC by id.

    ``last_id=0`` yields the full history.
    """

    stmt = (
        select(RunEvent)
        .where(RunEvent.run_id == run_id, RunEvent.id > last_id)
        .order_by(RunEvent.id.asc())
    )
    return list(session.scalars(stmt).all())


def _parse_payload(payload_json: str | None) -> Any:
    """Decode ``payload_json`` into a Python value (raw string on failure)."""

    if payload_json is None:
        return None
    try:
        return json.loads(payload_json)
    except (ValueError, TypeError):
        return payload_json


def format_sse_event(event: RunEvent) -> str:
    """Return the full SSE frame string for a single ``RunEvent``."""

    created_at = event.created_at.isoformat() if event.created_at else None
    data = {
        "id": event.id,
        "event_type": event.event_type,
        "payload": _parse_payload(event.payload_json),
        "created_at": created_at,
    }
    return (
        f"id: {event.id}\n"
        f"event: {event.event_type}\n"
        f"data: {json.dumps(data)}\n\n"
    )


def format_sse_eos(snapshot: RunSnapshot) -> str:
    """Return the terminal ``eos`` SSE frame for ``snapshot``."""

    data = {
        "run_id": snapshot.id,
        "final_status": snapshot.status,
        "exit_code": snapshot.exit_code,
        "outcome": snapshot.outcome,
    }
    return f"event: eos\ndata: {json.dumps(data)}\n\n"


def format_sse_heartbeat() -> str:
    """Return an SSE comment used as a keep-alive heartbeat."""

    return ": heartbeat\n\n"


__all__ = [
    "RunSnapshot",
    "TERMINAL_RUN_STATUSES",
    "format_sse_eos",
    "format_sse_event",
    "format_sse_heartbeat",
    "load_events_since",
    "load_run_snapshot",
    "run_exists",
]
