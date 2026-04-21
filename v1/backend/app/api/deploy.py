"""Static file handler for ``kind == 'web-deployable'`` projects (PR-V1-17).

SPEC §1 / §9 Semana 5 says "deploy a ``localhost:PORT/<slug>``". The MVP
interprets that as serving ``<project.local_path>/dist/`` under the already
running FastAPI process — no process spawn, no reverse proxy, no per-project
port binding. The ``Project.deploy_port`` column stays in the schema as
aspirational for v1.1 (Cloudflare/Caddy with wildcard subdomains).

Contract
--------
``GET /api/deploy/{slug}/{path:path}`` and ``GET /api/deploy/{slug}/`` —

* 404 when the slug is unknown or ``kind != 'web-deployable'``.
* Empty path or directory → ``dist/index.html`` (SPA fallback).
* Anything resolving outside ``dist/`` after ``Path.resolve()`` → 404. This
  catches both textual traversal (``..``) and symlinks that escape the
  build output. The guard runs before any filesystem read of the target.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Project
from .deps import get_session


router = APIRouter(prefix="/deploy", tags=["deploy"])


def _resolve_target(local_path: str, path: str) -> Path | None:
    """Return the file to serve, or ``None`` if the request must 404.

    Kept as a module-level helper so the traversal guard is straightforward
    to unit-test without spinning up the full ASGI stack. The function does
    no I/O beyond ``Path.resolve`` + ``is_dir``/``is_file``; it never reads
    file contents.
    """

    dist = (Path(local_path) / "dist").resolve()
    # Empty path hits the SPA entry point. Any other path is resolved
    # *relative to* ``dist`` so a leading slash in the raw segment can't
    # escape into the absolute filesystem root.
    target = (dist / path).resolve() if path else dist / "index.html"
    if target.is_dir():
        target = target / "index.html"

    try:
        target.resolve().relative_to(dist)
    except ValueError:
        return None

    if not target.is_file():
        return None
    return target


def _serve(slug: str, path: str, session: Session) -> FileResponse:
    project = session.execute(
        select(Project).where(Project.slug == slug)
    ).scalar_one_or_none()
    if project is None or project.kind != "web-deployable":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        )

    target = _resolve_target(project.local_path, path)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        )
    return FileResponse(target)


@router.get("/{slug}/")
def serve_deploy_root(
    slug: str,
    session: Session = Depends(get_session),
) -> FileResponse:
    """SPA entry point: ``/api/deploy/{slug}/`` → ``dist/index.html``."""

    return _serve(slug, "", session)


@router.get("/{slug}/{path:path}")
def serve_deploy(
    slug: str,
    path: str,
    session: Session = Depends(get_session),
) -> FileResponse:
    """Serve any file under ``<local_path>/dist/`` for a web-deployable project."""

    return _serve(slug, path, session)
