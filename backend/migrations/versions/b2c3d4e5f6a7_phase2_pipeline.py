"""Phase 2 pipeline: task states, TaskPlan, TaskReview, project policy

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-30

Adds:
- task_plans table
- task_reviews table
- tasks.status CHECK constraint updated (planning, waiting_approval, reviewing)
- projects policy columns (require_plan_approval, auto_review, max_review_iterations)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

_NEW_TASK_STATUSES = (
    "inbox", "queued", "running", "planning", "waiting_approval",
    "reviewing", "waiting_input", "done", "failed", "cancelled",
)
_OLD_TASK_STATUSES = (
    "inbox", "queued", "running", "waiting_input", "done", "failed", "cancelled",
)


def upgrade() -> None:
    # 1. task_plans
    op.create_table(
        "task_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("steps_json", sa.Text(), nullable=True),
        sa.Column("risks_json", sa.Text(), nullable=True),
        sa.Column("acceptance_criteria_json", sa.Text(), nullable=True),
        sa.Column("needs_user_approval", sa.Integer(), nullable=False, default=0),
        sa.Column("raw_response_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','planning_failed')",
            name="ck_task_plans_status",
        ),
    )

    # 2. task_reviews
    op.create_table(
        "task_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("iteration", sa.Integer(), nullable=False, default=0),
        sa.Column("diff_summary", sa.Text(), nullable=True),
        sa.Column("findings_json", sa.Text(), nullable=True),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("pending_question", sa.Text(), nullable=True),
        sa.Column("raw_response_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "decision IN ('approve','request_changes','needs_input','fail')",
            name="ck_task_reviews_decision",
        ),
    )

    # 3. Update tasks CHECK constraint for new statuses
    statuses_new = "', '".join(_NEW_TASK_STATUSES)
    with op.batch_alter_table("tasks", recreate="always") as batch_op:
        batch_op.create_check_constraint(
            "ck_tasks_status",
            f"status IN ('{statuses_new}')",
        )

    # 4. Add project policy columns
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("require_plan_approval", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("auto_review", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("max_review_iterations", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("max_review_iterations")
        batch_op.drop_column("auto_review")
        batch_op.drop_column("require_plan_approval")

    statuses_old = "', '".join(_OLD_TASK_STATUSES)
    with op.batch_alter_table("tasks", recreate="always") as batch_op:
        batch_op.create_check_constraint(
            "ck_tasks_status",
            f"status IN ('{statuses_old}')",
        )

    op.drop_table("task_reviews")
    op.drop_table("task_plans")
