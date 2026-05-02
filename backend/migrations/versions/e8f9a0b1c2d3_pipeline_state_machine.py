"""Add pipeline plan approval mode.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "e8f9a0b1c2d3"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects", recreate="always") as batch:
        batch.add_column(
            sa.Column(
                "plan_approval_mode",
                sa.String(),
                nullable=False,
                server_default="auto",
            )
        )
        batch.create_check_constraint(
            "ck_projects_plan_approval_mode",
            "plan_approval_mode IN ('auto','manual')",
        )


def downgrade() -> None:
    with op.batch_alter_table("projects", recreate="always") as batch:
        batch.drop_constraint("ck_projects_plan_approval_mode", type_="check")
        batch.drop_column("plan_approval_mode")
