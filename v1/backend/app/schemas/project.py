"""Pydantic schemas for the ``Project`` resource.

The wire contract is intentionally close to the ORM model (SPEC §3). Three
shapes live here:

* ``ProjectCreate`` — payload accepted by ``POST /api/projects``.
* ``ProjectPatch`` — payload accepted by ``PATCH /api/projects/{slug}``.
  Every field optional; ``slug`` is deliberately absent so renames are not
  possible in-place (the brief mandates delete-and-recreate).
* ``ProjectRead`` — response body, built from the ORM row via
  ``model_config = ConfigDict(from_attributes=True)``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# Regex used both for runtime validation and for the generated OpenAPI schema.
SLUG_PATTERN = r"^[a-z0-9-]+$"

ProjectKind = Literal["web-deployable", "library", "script"]
AutonomyMode = Literal["safe", "dangerous"]


class ProjectCreate(BaseModel):
    """Payload for creating a project.

    ``slug`` is lowercase alphanumerics plus dashes, 3-40 chars. ``local_path``
    is expected to be an absolute path but we defer the filesystem check to
    later PRs — the executor needs the path to exist, the API does not.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=3, max_length=40, pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    kind: ProjectKind
    git_remote: str | None = None
    local_path: str = Field(min_length=1)
    deploy_port: int | None = Field(default=None, ge=1024, le=65535)
    autonomy_mode: AutonomyMode = "safe"


class ProjectPatch(BaseModel):
    """Partial update payload.

    ``slug`` is intentionally not present. ``extra="forbid"`` turns any attempt
    to patch it (or any other unknown field) into a ``422`` before it reaches
    the service layer.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: ProjectKind | None = None
    git_remote: str | None = None
    local_path: str | None = Field(default=None, min_length=1)
    deploy_port: int | None = Field(default=None, ge=1024, le=65535)
    autonomy_mode: AutonomyMode | None = None


class ProjectRead(BaseModel):
    """Response shape — mirrors the ORM columns for the projects table."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    kind: str
    git_remote: str | None
    local_path: str
    deploy_port: int | None
    autonomy_mode: str
    created_at: datetime
    updated_at: datetime
