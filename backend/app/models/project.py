"""``projects`` table — a git repo Niwa can run tasks against.

See SPEC §3 for the column set. ``kind`` and ``autonomy_mode`` are bounded by
CHECK constraints; SQLite has no native ENUM and we want the constraint to
survive ``alembic upgrade`` on a fresh DB.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('web-deployable', 'library', 'script')",
            name="ck_projects_kind",
        ),
        CheckConstraint(
            "autonomy_mode IN ('safe', 'dangerous')",
            name="ck_projects_autonomy_mode",
        ),
        CheckConstraint(
            "deploy_type IN ('static', 'process')",
            name="ck_projects_deploy_type",
        ),
        CheckConstraint(
            "deploy_trigger IN ('manual', 'on_done', 'on_merge')",
            name="ck_projects_deploy_trigger",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    git_remote: Mapped[str | None] = mapped_column(String, nullable=True)
    local_path: Mapped[str] = mapped_column(String, nullable=False)
    deploy_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    autonomy_mode: Mapped[str] = mapped_column(
        String, nullable=False, server_default="safe"
    )
    # Phase 4 — versioned deployments (DEPLOY-01..09)
    deploy_type: Mapped[str] = mapped_column(
        String, nullable=False, server_default="static"
    )
    build_command: Mapped[str | None] = mapped_column(String, nullable=True)
    dist_dir: Mapped[str | None] = mapped_column(String, nullable=True)
    start_command: Mapped[str | None] = mapped_column(String, nullable=True)
    healthcheck_path: Mapped[str | None] = mapped_column(String, nullable=True)
    deploy_trigger: Mapped[str] = mapped_column(
        String, nullable=False, server_default="manual"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    tasks: Mapped[list["Task"]] = relationship(  # noqa: F821
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
