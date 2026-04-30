"""``deployments`` table — tracks every deploy attempt for a project (Phase 4)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


DEPLOYMENT_STATUSES = (
    "queued", "building", "starting", "healthy", "unhealthy",
    "failed", "stopped", "rolled_back",
)

DEPLOYMENT_TYPES = ("static", "process")


class Deployment(Base):
    __tablename__ = "deployments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','building','starting','healthy','unhealthy',"
            "'failed','stopped','rolled_back')",
            name="ck_deployments_status",
        ),
        CheckConstraint(
            "deploy_type IN ('static','process')",
            name="ck_deployments_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    deploy_type: Mapped[str] = mapped_column(String, nullable=False, default="static")
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    artifact_path: Mapped[str | None] = mapped_column(String, nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url_local: Mapped[str | None] = mapped_column(String, nullable=True)
    healthcheck_path: Mapped[str] = mapped_column(String, nullable=False, default="/")
    build_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
