"""FastAPI entrypoint for Niwa v1.

Mounts ``/api/health`` plus the resource routers registered by
``app.api.api_router`` (projects today, tasks/runs in future PRs).
"""

from __future__ import annotations

from fastapi import FastAPI

from . import __version__
from .api import api_router

app = FastAPI(title="Niwa v1", version=__version__)
app.include_router(api_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness endpoint used by the frontend and the readiness page."""

    return {"status": "ok", "version": __version__}
