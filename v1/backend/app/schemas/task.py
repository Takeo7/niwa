"""Pydantic schemas for the ``Task`` resource.

Two shapes live here:

* ``TaskCreate`` — payload accepted by ``POST /api/projects/{slug}/tasks``.
  The service decides ``status`` (always ``queued`` on create), the parent
  project, and timestamps; the caller only provides ``title`` and an
  optional ``description``.
* ``TaskRead`` — response body, built from the ORM row via
  ``model_config = ConfigDict(from_attributes=True)``.

Other task fields (``branch_name``, ``pr_url``, ``pending_question`` and
status transitions past ``queued``) are written by the executor in later
PRs; they are never settable through the HTTP API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TaskStatus = Literal[
    "inbox",
    "queued",
    "running",
    "waiting_input",
    "done",
    "failed",
    "cancelled",
]


class TaskCreate(BaseModel):
    """Payload for creating a task.

    ``extra="forbid"`` rejects any attempt to set status / timestamps /
    branch_name from the client with ``422``.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)


class TaskRead(BaseModel):
    """Response shape — mirrors the ORM columns for the tasks table."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    parent_task_id: int | None
    title: str
    description: str | None
    status: TaskStatus
    branch_name: str | None
    pr_url: str | None
    pending_question: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
