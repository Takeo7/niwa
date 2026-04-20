"""``task_events`` table — append-only log of task-scoped events.

``payload_json`` stores serialized JSON as ``TEXT``; SQLite has no native JSON
column type and the SPEC keeps the schema free of dialect-specific features.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


TASK_EVENT_KINDS = (
    "created",
    "status_changed",
    "message",
    "verification",
    "error",
)


class TaskEvent(Base):
    __tablename__ = "task_events"
    __table_args__ = (
        CheckConstraint(
            "kind IN ("
            + ", ".join(f"'{k}'" for k in TASK_EVENT_KINDS)
            + ")",
            name="ck_task_events_kind",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    task: Mapped["Task"] = relationship(back_populates="events")  # noqa: F821
