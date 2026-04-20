"""Pydantic v2 schemas exposed by the Niwa v1 API.

Each concrete schema lives in its own module; this package simply re-exports
the public names so callers can write ``from app.schemas import ProjectRead``.
"""

from __future__ import annotations

from .project import ProjectCreate, ProjectPatch, ProjectRead
from .task import TaskCreate, TaskRead

__all__ = [
    "ProjectCreate",
    "ProjectPatch",
    "ProjectRead",
    "TaskCreate",
    "TaskRead",
]
