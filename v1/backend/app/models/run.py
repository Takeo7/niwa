"""``runs`` table — a single execution attempt of a task.

A task may accumulate multiple runs when the user resumes from a
``waiting_input`` state. ``artifact_root`` is the absolute cwd of the CLI
invocation; ``verification_json`` snapshots the evidence check result.
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


RUN_STATUSES = (
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            + ", ".join(f"'{s}'" for s in RUN_STATUSES)
            + ")",
            name="ck_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="queued"
    )
    model: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    session_handle: Mapped[str | None] = mapped_column(String, nullable=True)
    artifact_root: Mapped[str] = mapped_column(String, nullable=False)
    verification_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    task: Mapped["Task"] = relationship(back_populates="runs")  # noqa: F821
    events: Mapped[list["RunEvent"]] = relationship(  # noqa: F821
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
