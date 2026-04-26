"""Pydantic schema for the ``Attachment`` resource (PR-V1-33).

Single read shape — uploads come in as ``multipart/form-data`` and are
parsed by FastAPI's ``UploadFile``, so there is no ``AttachmentCreate``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AttachmentRead(BaseModel):
    """Response shape — mirrors the ORM columns for the attachments table."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    filename: str
    content_type: str | None
    size_bytes: int
    created_at: datetime
