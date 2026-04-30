"""MCP pull-request tools — pull_list, pull_merge (Phase 7, MCP-10)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ...services import github_pulls
from ...services import projects as projects_service


def _resolve_owner_repo(db: Session, slug: str) -> tuple[str, str]:
    try:
        project = projects_service.get_project(db, slug)
    except projects_service.ProjectNotFound:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    if not project.git_remote:
        raise HTTPException(
            status_code=400,
            detail=f"Project '{slug}' has no git_remote configured",
        )
    parsed = github_pulls.parse_owner_repo(project.git_remote)
    if parsed is None:
        raise HTTPException(
            status_code=400,
            detail=f"Could not parse owner/repo from {project.git_remote}",
        )
    return parsed


def pull_list(db: Session, project_slug: str) -> list[dict[str, Any]]:
    owner, repo = _resolve_owner_repo(db, project_slug)
    try:
        pulls = github_pulls.list_pulls(owner=owner, repo=repo)
    except github_pulls.GhUnavailable:
        raise HTTPException(status_code=503, detail="gh CLI not available")
    except github_pulls.GhTimeout:
        raise HTTPException(status_code=504, detail="gh CLI timed out")
    except github_pulls.GhCommandFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return [p.model_dump(mode="json") for p in pulls]


def pull_merge(
    db: Session,
    project_slug: str,
    number: int,
    method: str = "squash",
) -> dict[str, Any]:
    owner, repo = _resolve_owner_repo(db, project_slug)
    if method not in ("squash", "merge", "rebase"):
        raise HTTPException(status_code=400, detail=f"Invalid method: {method}")
    try:
        github_pulls.merge_pull(owner=owner, repo=repo, number=number, method=method)
    except github_pulls.GhUnavailable:
        raise HTTPException(status_code=503, detail="gh CLI not available")
    except github_pulls.GhTimeout:
        raise HTTPException(status_code=504, detail="gh CLI timed out")
    except github_pulls.PullNotMergeable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except github_pulls.GhCommandFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"merged": True, "number": number, "method": method}
