"""``attachments`` table — files the user adjuntó al crear una task.

Files live on disk under ``<project.local_path>/.niwa/attachments/
task-<id>/``; this row carries the metadata + absolute storage path so
the executor can render them in the adapter prompt and the API can
serve listings/deletes.

``ON DELETE CASCADE`` on ``task_id`` mirrors ``task_events`` and
``runs`` — wiping the parent task removes its attachment rows. The
files on disk persist (lifecycle independent per brief §Criterio).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    task: Mapped["Task"] = relationship(back_populates="attachments")  # noqa: F821
