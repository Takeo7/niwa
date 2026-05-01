"""Persisted post-verification reviews for tasks."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class TaskReview(Base):
    __tablename__ = "task_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decision: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    findings_json: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer: Mapped[str] = mapped_column(
        String, nullable=False, server_default="fake-json"
    )
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    task: Mapped["Task"] = relationship(back_populates="reviews")  # noqa: F821

    @property
    def findings(self) -> list[str]:
        try:
            value: Any = json.loads(self.findings_json)
        except ValueError:
            return []
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if isinstance(item, str)]
