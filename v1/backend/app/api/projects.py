"""Projects CRUD endpoints (SPEC §3, brief PR-V1-03).

Five routes, no filters, no pagination — the MVP is single-user, ~10 projects.

* ``GET    /api/projects``          → list all projects, ``created_at`` ASC.
* ``POST   /api/projects``          → create; ``409`` on duplicate slug.
* ``GET    /api/projects/{slug}``   → fetch by slug; ``404`` when missing.
* ``PATCH  /api/projects/{slug}``   → partial update; ``slug`` not patchable.
* ``DELETE /api/projects/{slug}``   → remove; ``204`` on success.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..schemas import ProjectCreate, ProjectPatch, ProjectRead
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
