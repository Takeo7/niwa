"""add finalize_result to task_events kind constraint

Revision ID: a1b2c3d4e5f6
Revises: f98a50e87242
Create Date: 2026-04-30

SQLite does not support ALTER TABLE … DROP CONSTRAINT, so we use
batch mode to rewrite the table with the updated CHECK constraint.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "f98a50e87242"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("task_events", recreate="always") as batch_op:
        batch_op.create_check_constraint(
            "ck_task_events_kind",
            "kind IN ('created','status_changed','message','verification','error','finalize_result')",
        )


def downgrade() -> None:
    with op.batch_alter_table("task_events", recreate="always") as batch_op:
        batch_op.create_check_constraint(
            "ck_task_events_kind",
            "kind IN ('created','status_changed','message','verification','error')",
        )
