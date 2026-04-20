"""Pydantic schemas for the ``Run`` resource.

Only the read shape is exposed by the API at this stage: runs are created
exclusively by the executor (PR-V1-05) and there is no inbound payload yet.

Fields mirror the ``runs`` table declared in ``app/models/run.py``. The
``artifact_root`` column is the absolute cwd of the CLI invocation; the MVP
echo executor leaves it as ``""`` because no real work happens. The real
Claude Code adapter fills it in Semana 2.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


RunStatus = Literal[
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
]


class RunRead(BaseModel):
    """Response shape — mirrors the ORM columns for the runs table."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    status: RunStatus
    model: str
    started_at: datetime
    finished_at: datetime | None
    exit_code: int | None
    outcome: str | None
    session_handle: str | None
    artifact_root: str
    verification_json: str | None
    created_at: datetime
