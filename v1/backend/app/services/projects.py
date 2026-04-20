"""Pure functions over ``Session`` for the ``Project`` resource.

Each public function commits its own transaction and raises a domain-level
exception that the API layer maps to an HTTP status. Keeping ``HTTPException``
out of here makes the service reusable from non-HTTP callers (CLI scripts,
the executor, future tests).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Project
from ..schemas import ProjectCreate, ProjectPatch


class ProjectNotFound(Exception):
    """Raised when a slug lookup does not match any row."""


class DuplicateSlug(Exception):
    """Raised when a ``create`` would violate the ``projects.slug`` unique."""


def list_projects(session: Session) -> list[Project]:
    """Return every project ordered by ``created_at`` ascending."""

    stmt = select(Project).order_by(Project.created_at.asc(), Project.id.asc())
    return list(session.scalars(stmt).all())


def get_project(session: Session, slug: str) -> Project:
    """Return the project with the given slug or raise ``ProjectNotFound``."""

    project = session.scalar(select(Project).where(Project.slug == slug))
    if project is None:
        raise ProjectNotFound(slug)
    return project


def create_project(session: Session, payload: ProjectCreate) -> Project:
    """Insert a new project row.

    Translates the SQLite unique-constraint violation on ``slug`` into
    ``DuplicateSlug`` so the API layer can respond ``409`` instead of leaking
    a generic ``IntegrityError`` (which would surface as ``500``).
    """

    project = Project(**payload.model_dump())
    session.add(project)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateSlug(payload.slug) from exc
    session.refresh(project)
    return project


def patch_project(
    session: Session, slug: str, payload: ProjectPatch
) -> Project:
    """Apply the non-``None`` fields of ``payload`` to the matching project."""

    project = get_project(session, slug)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(project, field, value)
    session.commit()
    session.refresh(project)
    return project


def delete_project(session: Session, slug: str) -> None:
    """Delete the project with the given slug; raise if it does not exist."""

    project = get_project(session, slug)
    session.delete(project)
    session.commit()
