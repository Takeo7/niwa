"""Runs API — SSE endpoint streaming ``run_events`` in real time (PR-V1-09).

``GET /api/runs/{run_id}/events`` emits historical events (``id`` ASC),
then tail-polls every 200 ms until ``Run.status`` is terminal, closing
with an ``eos`` frame. Heartbeat comment every ~15 s.

The ``Session`` from ``Depends(get_session)`` only powers the initial
404 check; the stream body opens a short-lived session per poll via
``_open_session`` (honours ``app.dependency_overrides`` for tests) so no
transaction is held across ``await`` points. DB work runs inside
``asyncio.to_thread`` because the project stays on sync ``Session``.
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
    """Yield a short-lived ``Session`` honouring ``dependency_overrides``."""

    provider = request.app.dependency_overrides.get(get_session, get_session)
    generator = provider()
    session = next(generator)
    try:
        yield session
    finally:
        generator.close()


def _initial_snapshot(request: Request, run_id: int) -> svc.RunSnapshot | None:
    with _open_session(request) as session:
        return svc.load_run_snapshot(session, run_id)


def _load_events(request: Request, run_id: int, last_id: int) -> list:
    with _open_session(request) as session:
        return svc.load_events_since(session, run_id, last_id)


async def _event_stream(
    request: Request, run_id: int
) -> AsyncIterator[str]:
    """Yield SSE frames for ``run_id``: history, tail, ``eos``."""

    last_id = 0
    heartbeat_counter = 0

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
            return

        new_events = await asyncio.to_thread(
            _load_events, request, run_id, last_id
        )
        for event in new_events:
            yield svc.format_sse_event(event)
            if event.id > last_id:
                last_id = event.id

        if snapshot.status in svc.TERMINAL_RUN_STATUSES:
            # Drain events that landed between snapshot load and the
            # terminal check so none is lost.
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
    """SSE stream of ``run_events`` for ``run_id`` (``404`` JSON if missing)."""

    if not svc.run_exists(session, run_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    return StreamingResponse(
        _event_stream(request, run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx hint; harmless without a proxy.
        },
    )


__all__ = ["runs_router"]
