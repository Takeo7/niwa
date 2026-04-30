"""MCP project tools — project_list and project_get."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ...services import projects as service


def project_list(db: Session) -> list[dict[str, Any]]:
    projects = service.list_projects(db)
    return [
        {
            "slug": p.slug,
            "name": p.name,
            "kind": p.kind,
            "autonomy_mode": p.autonomy_mode,
            "git_remote": p.git_remote,
        }
        for p in projects
    ]


def project_get(db: Session, slug: str) -> dict[str, Any]:
    try:
        p = service.get_project(db, slug)
    except service.ProjectNotFound:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return {
        "slug": p.slug,
        "name": p.name,
        "kind": p.kind,
        "autonomy_mode": p.autonomy_mode,
        "git_remote": p.git_remote,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
