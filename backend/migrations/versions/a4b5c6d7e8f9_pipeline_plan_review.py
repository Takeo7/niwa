"""Add task plan/review tables and pipeline statuses.

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "a4b5c6d7e8f9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


_NEW_STATUSES = (
    "inbox", "queued", "triaging", "planning", "waiting_approval",
    "executing", "verifying", "reviewing", "running", "waiting_input",
    "done", "failed", "cancelled",
)
_OLD_STATUSES = (
    "inbox", "queued", "running", "waiting_input",
    "done", "failed", "cancelled",
)


def _status_check(statuses: tuple[str, ...]) -> str:
    return "status IN (" + ", ".join(f"'{s}'" for s in statuses) + ")"


def upgrade() -> None:
    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.drop_constraint("ck_tasks_status", type_="check")
        batch.create_check_constraint(
            "ck_tasks_status",
            _status_check(_NEW_STATUSES),
        )

    op.create_table(
        "task_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="ready"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("steps_json", sa.Text(), nullable=False),
        sa.Column("risks_json", sa.Text(), nullable=False),
        sa.Column("planner", sa.String(), nullable=False, server_default="fake-json"),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_task_plans_task_id", "task_plans", ["task_id"])

    op.create_table(
        "task_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("findings_json", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.String(), nullable=False, server_default="fake-json"),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_task_reviews_task_id", "task_reviews", ["task_id"])
    op.create_index("ix_task_reviews_run_id", "task_reviews", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_task_reviews_run_id", table_name="task_reviews")
    op.drop_index("ix_task_reviews_task_id", table_name="task_reviews")
    op.drop_table("task_reviews")
    op.drop_index("ix_task_plans_task_id", table_name="task_plans")
    op.drop_table("task_plans")

    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.drop_constraint("ck_tasks_status", type_="check")
        batch.create_check_constraint(
            "ck_tasks_status",
            _status_check(_OLD_STATUSES),
        )
