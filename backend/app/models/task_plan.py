"""Persisted execution plans for tasks."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class TaskPlan(Base):
    __tablename__ = "task_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="ready"
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    steps_json: Mapped[str] = mapped_column(Text, nullable=False)
    risks_json: Mapped[str] = mapped_column(Text, nullable=False)
    planner: Mapped[str] = mapped_column(
        String, nullable=False, server_default="fake-json"
    )
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    task: Mapped["Task"] = relationship(back_populates="plans")  # noqa: F821

    @property
    def steps(self) -> list[str]:
        return _json_list(self.steps_json)

    @property
    def risks(self) -> list[str]:
        return _json_list(self.risks_json)


def _json_list(raw: str) -> list[str]:
    try:
        value: Any = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]
