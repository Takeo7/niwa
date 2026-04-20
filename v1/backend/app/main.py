"""FastAPI entrypoint for Niwa v1.

Exposes only ``/api/health`` in this PR; CRUD and executor wiring arrive in
later PRs per the SPEC §9 milestones.
"""

from __future__ import annotations

from fastapi import FastAPI

from . import __version__

app = FastAPI(title="Niwa v1", version=__version__)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness endpoint used by the frontend and the readiness page."""

    return {"status": "ok", "version": __version__}
