"""Runs API — SSE endpoint streaming ``run_events`` in real time (PR-V1-09).

Only one route for now: ``GET /api/runs/{run_id}/events`` as
Server-Sent Events. The stream emits every historical ``run_event`` for
``run_id`` ordered by ``id`` ASC, then tails the DB every 200 ms until
the parent ``Run.status`` reaches a terminal state
(``completed|failed|cancelled``). A comment heartbeat is emitted every
~15 s so intermediate proxies do not drop the keep-alive.

Design notes (see brief PR-V1-09):

- The existing ``Session`` from ``Depends(get_session)`` is used only for
  the initial 404 check. The stream body opens a short-lived session per
  poll via ``_open_session`` so we never hold a transaction open across
  ``await asyncio.sleep`` boundaries.
- ``_open_session`` calls the ``get_session`` dependency directly —
  ``app.dependency_overrides`` is honoured (tests inject the in-memory
  SQLite this way).
- SQLAlchemy session is synchronous; DB work runs inside
  ``asyncio.to_thread`` so the event loop stays responsive.
- Heartbeat cadence is implemented by counting tail iterations (75 * 200
  ms ≈ 15 s) instead of wall-clock comparison: cheaper and deterministic.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import contextmanager
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..services import run_events as svc
from .deps import get_session


runs_router = APIRouter(prefix="/runs", tags=["runs"])


# Tail cadence: sleep 200 ms between polls, emit a heartbeat every ~15 s.
_POLL_INTERVAL_S = 0.2
_HEARTBEAT_EVERY_ITERATIONS = 75  # 75 * 200 ms = 15 s.


@contextmanager
def _open_session(request: Request) -> Iterator[Session]:
    """Yield a short-lived ``Session`` honouring ``dependency_overrides``.

    Looks up the current provider for ``get_session`` (test overrides or
    the default) and drives the generator manually so ``finally`` runs
    and the session is closed.
    """

    provider = request.app.dependency_overrides.get(get_session, get_session)
    generator = provider()
    session = next(generator)
    try:
        yield session
    finally:
        generator.close()


def _initial_snapshot(request: Request, run_id: int) -> svc.RunSnapshot | None:
    """Load the run snapshot in a dedicated session."""

    with _open_session(request) as session:
        return svc.load_run_snapshot(session, run_id)


def _load_events(
    request: Request, run_id: int, last_id: int
) -> list:
    """Load pending events (``id > last_id``) in a dedicated session."""

    with _open_session(request) as session:
        return svc.load_events_since(session, run_id, last_id)


async def _event_stream(
    request: Request, run_id: int
) -> AsyncIterator[str]:
    """Async generator yielding SSE frames for ``run_id``.

    Emits history, tails until terminal, closes with an ``eos`` frame.
    Uses ``asyncio.to_thread`` so the synchronous SQLAlchemy session does
    not block the event loop.
    """

    last_id = 0
    heartbeat_counter = 0

    # Stream historical events first; use ``last_id`` to stitch the tail
    # without races (brief §"Race históricos↔nuevos").
    history = await asyncio.to_thread(_load_events, request, run_id, last_id)
    for event in history:
        yield svc.format_sse_event(event)
        if event.id > last_id:
            last_id = event.id

    while True:
        if await request.is_disconnected():
            return

        snapshot = await asyncio.to_thread(_initial_snapshot, request, run_id)
        if snapshot is None:
            # Run was deleted mid-stream; nothing sensible to emit.
            return

        new_events = await asyncio.to_thread(
            _load_events, request, run_id, last_id
        )
        for event in new_events:
            yield svc.format_sse_event(event)
            if event.id > last_id:
                last_id = event.id

        if snapshot.status in svc.TERMINAL_RUN_STATUSES:
            # Drain any events that landed between the snapshot load and
            # the terminal-state check so no event is lost.
            tail = await asyncio.to_thread(
                _load_events, request, run_id, last_id
            )
            for event in tail:
                yield svc.format_sse_event(event)
                if event.id > last_id:
                    last_id = event.id
            yield svc.format_sse_eos(snapshot)
            return

        await asyncio.sleep(_POLL_INTERVAL_S)
        heartbeat_counter += 1
        if heartbeat_counter >= _HEARTBEAT_EVERY_ITERATIONS:
            yield svc.format_sse_heartbeat()
            heartbeat_counter = 0


@runs_router.get("/{run_id}/events")
async def stream_run_events(
    run_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> StreamingResponse:
    """SSE stream of ``run_events`` for ``run_id``.

    Returns ``404`` JSON when the run does not exist (checked before the
    stream starts so the client never sees an empty 200 for a missing id).
    """

    if not svc.run_exists(session, run_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        # nginx hint; harmless when no proxy is in front of us.
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        _event_stream(request, run_id),
        media_type="text/event-stream",
        headers=headers,
    )


__all__ = ["runs_router"]
