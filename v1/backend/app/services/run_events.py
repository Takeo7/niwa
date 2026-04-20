"""Helpers for the SSE ``GET /api/runs/{run_id}/events`` endpoint (PR-V1-09).

The formatting helpers here are pure (no DB); the loader helpers wrap
synchronous SQLAlchemy queries so the async generator in ``app.api.runs``
can run them via ``asyncio.to_thread`` without introducing AsyncSession
into the project (see brief PR-V1-09 §"Sessions SQLAlchemy dentro de
async").

Contract of the SSE frames (brief PR-V1-09 §"Contrato del stream"):

    id: <run_event.id>
    event: <run_event.event_type>
    data: {"id": ..., "event_type": ..., "payload": {...}, "created_at": ...}

    event: eos
    data: {"run_id": ..., "final_status": ..., "exit_code": ..., "outcome": ...}

``payload_json`` is stored as a JSON string in the DB; we re-parse it so
the SSE ``data`` field is a proper JSON object (not an escaped string).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
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
    """Return every event for ``run_id`` with ``id > last_id``, ASC by id.

    ``last_id=0`` yields the full history; the tail loop passes the max id
    it has already emitted to pick up only fresh rows.
    """

    stmt = (
        select(RunEvent)
        .where(RunEvent.run_id == run_id, RunEvent.id > last_id)
        .order_by(RunEvent.id.asc())
    )
    return list(session.scalars(stmt).all())


def _parse_payload(payload_json: str | None) -> Any:
    """Decode ``payload_json`` into a Python value.

    Returns ``None`` when the column is NULL and the raw string when it is
    not valid JSON (belt-and-braces: the adapter writes JSON, but older
    rows or manual inserts might not).
    """

    if payload_json is None:
        return None
    try:
        return json.loads(payload_json)
    except (ValueError, TypeError):
        return payload_json


def _format_created_at(created_at: datetime | None) -> str | None:
    if created_at is None:
        return None
    return created_at.isoformat()


def format_sse_event(event: RunEvent) -> str:
    """Return the full SSE frame string for a single ``RunEvent``."""

    data = {
        "id": event.id,
        "event_type": event.event_type,
        "payload": _parse_payload(event.payload_json),
        "created_at": _format_created_at(event.created_at),
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
