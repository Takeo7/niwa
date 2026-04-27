"""Projects CRUD endpoints (SPEC §3, brief PR-V1-03).

Five routes, no filters, no pagination — the MVP is single-user, ~10 projects.

* ``GET    /api/projects``                  → list all projects, ``created_at`` ASC.
* ``POST   /api/projects``                  → create; ``409`` on duplicate slug.
* ``GET    /api/projects/{slug}``           → fetch by slug; ``404`` when missing.
* ``PATCH  /api/projects/{slug}``           → partial update; ``slug`` not patchable.
* ``DELETE /api/projects/{slug}``           → remove; ``204`` on success.
* ``GET    /api/projects/{slug}/pulls``     → PR-V1-34, GitHub pulls via ``gh``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..schemas import (
    ProjectCreate,
    ProjectPatch,
    ProjectRead,
    PullMergePayload,
    PullMergeResponse,
    PullsResponse,
)
from ..services import github_pulls
from ..services import projects as service
from .deps import get_session


router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
def list_projects(session: Session = Depends(get_session)) -> list[ProjectRead]:
    rows = service.list_projects(session)
    return [ProjectRead.model_validate(row) for row in rows]


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    payload: ProjectCreate,
    session: Session = Depends(get_session),
) -> ProjectRead:
    try:
        project = service.create_project(session, payload)
    except service.DuplicateSlug:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="slug already exists",
        )
    return ProjectRead.model_validate(project)


@router.get("/{slug}", response_model=ProjectRead)
def get_project(
    slug: str,
    session: Session = Depends(get_session),
) -> ProjectRead:
    try:
        project = service.get_project(session, slug)
    except service.ProjectNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found",
        )
    return ProjectRead.model_validate(project)


@router.patch("/{slug}", response_model=ProjectRead)
def patch_project(
    slug: str,
    payload: ProjectPatch,
    session: Session = Depends(get_session),
) -> ProjectRead:
    try:
        project = service.patch_project(session, slug, payload)
    except service.ProjectNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found",
        )
    return ProjectRead.model_validate(project)


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    slug: str,
    session: Session = Depends(get_session),
) -> Response:
    try:
        service.delete_project(session, slug)
    except service.ProjectNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


_ALLOWED_PULL_STATES = {"open", "closed", "all"}


@router.get("/{slug}/pulls", response_model=PullsResponse)
def list_project_pulls(
    slug: str,
    state: str = "open",
    include_all: bool = False,
    session: Session = Depends(get_session),
) -> JSONResponse:
    """List GitHub pulls via ``gh`` (PR-V1-34, read-only).

    200 ``{"pulls": [...]}`` on success; 200 ``{"warning": ..., "pulls":
    []}`` when the project has no/invalid remote (no point shelling out);
    503 ``gh_missing`` when the CLI isn't on PATH; 504 ``gh_timeout`` if
    the subprocess exceeds the per-call deadline; 502 ``gh_failed`` for
    other runtime failures (auth, network, rate limit, parse error).
    """

    if state not in _ALLOWED_PULL_STATES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="state must be one of: open, closed, all",
        )
    try:
        project = service.get_project(session, slug)
    except service.ProjectNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="project not found",
        )
    if not project.git_remote:
        return JSONResponse({"warning": "no_remote", "pulls": []})
    parsed = github_pulls.parse_owner_repo(project.git_remote)
    if parsed is None:
        return JSONResponse({"warning": "invalid_remote", "pulls": []})
    owner, repo = parsed
    try:
        pulls = github_pulls.list_pulls(
            owner=owner, repo=repo, state=state, include_all=include_all,
        )
    except github_pulls.GhUnavailable:
        return JSONResponse(
            {"error": "gh_missing"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except github_pulls.GhTimeout as exc:
        return JSONResponse(
            {"error": "gh_timeout", "detail": str(exc)[:500]},
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        )
    except github_pulls.GhCommandFailed as exc:
        return JSONResponse(
            {"error": "gh_failed", "detail": str(exc)[:500]},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    return JSONResponse(
        {"pulls": [pull.model_dump(mode="json") for pull in pulls]},
    )


@router.post(
    "/{slug}/pulls/{number}/merge", response_model=PullMergeResponse,
)
def merge_project_pull(
    slug: str,
    number: int,
    payload: PullMergePayload | None = None,
    session: Session = Depends(get_session),
) -> JSONResponse:
    """Merge a GitHub pull via ``gh pr merge`` (PR-V1-35).

    422 when the project's remote isn't a parseable github.com URL (the
    listing endpoint returns ``invalid_remote`` warning for the same
    case, but a merge call here implies the user is acting on a row that
    must have come from gh — surface as a hard error). 404 if project
    missing; 409 ``not_mergeable`` when gh refuses (conflicts, failing
    checks); 503/504/502 mirror the listing error mapping.
    """

    try:
        project = service.get_project(session, slug)
    except service.ProjectNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="project not found",
        )
    if not project.git_remote:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="project has no git_remote",
        )
    parsed = github_pulls.parse_owner_repo(project.git_remote)
    if parsed is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="project remote is not a github.com URL",
        )
    owner, repo = parsed
    method = (payload or PullMergePayload()).method
    try:
        github_pulls.merge_pull(
            owner=owner, repo=repo, number=number, method=method,
        )
    except github_pulls.GhUnavailable:
        return JSONResponse(
            {"error": "gh_missing"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except github_pulls.GhTimeout as exc:
        return JSONResponse(
            {"error": "gh_timeout", "detail": str(exc)[:500]},
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        )
    except github_pulls.PullNotMergeable as exc:
        return JSONResponse(
            {"error": "not_mergeable", "detail": str(exc)[:500]},
            status_code=status.HTTP_409_CONFLICT,
        )
    except github_pulls.GhCommandFailed as exc:
        return JSONResponse(
            {"error": "gh_failed", "detail": str(exc)[:500]},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    return JSONResponse(
        PullMergeResponse(merged=True, method=method).model_dump(mode="json"),
    )
