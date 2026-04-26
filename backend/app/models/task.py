"""``tasks`` table — a unit of work scheduled against a project.

``parent_task_id`` is a self-FK that carries the subtask relation produced by
the triage split (SPEC §4). Deleting a parent cascades to its subtasks because
a subtask has no standalone meaning outside its parent.
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


TASK_STATUSES = (
    "inbox",
    "queued",
    "running",
    "waiting_input",
    "done",
    "failed",
    "cancelled",
)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            + ", ".join(f"'{s}'" for s in TASK_STATUSES)
            + ")",
            name="ck_tasks_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="inbox"
    )
    branch_name: Mapped[str | None] = mapped_column(String, nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String, nullable=True)
    pending_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project"] = relationship(  # noqa: F821
        back_populates="tasks"
    )
    parent: Mapped["Task | None"] = relationship(
        "Task",
        remote_side="Task.id",
        back_populates="subtasks",
    )
    subtasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="parent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    events: Mapped[list["TaskEvent"]] = relationship(  # noqa: F821
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    runs: Mapped[list["Run"]] = relationship(  # noqa: F821
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    attachments: Mapped[list["Attachment"]] = relationship(  # noqa: F821
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Attachment.id.asc()",
    )
