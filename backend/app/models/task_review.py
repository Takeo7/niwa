"""``task_reviews`` table — LLM semantic code reviews (Phase 2)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


REVIEW_DECISIONS = ("approve", "request_changes", "needs_input", "fail")


class TaskReview(Base):
    __tablename__ = "task_reviews"
    __table_args__ = (
        CheckConstraint(
            "decision IN (" + ", ".join(f"'{d}'" for d in REVIEW_DECISIONS) + ")",
            name="ck_task_reviews_decision",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    diff_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    findings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    pending_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    task: Mapped["Task"] = relationship(back_populates="reviews")  # noqa: F821
