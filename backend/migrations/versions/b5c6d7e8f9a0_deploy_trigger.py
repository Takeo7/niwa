"""Add project deploy trigger setting.

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "b5c6d7e8f9a0"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects", recreate="always") as batch:
        batch.add_column(
            sa.Column(
                "deploy_trigger",
                sa.String(),
                nullable=False,
                server_default="manual",
            )
        )
        batch.create_check_constraint(
            "ck_projects_deploy_trigger",
            "deploy_trigger IN ('manual','on_done','on_merge')",
        )


def downgrade() -> None:
    with op.batch_alter_table("projects", recreate="always") as batch:
        batch.drop_constraint("ck_projects_deploy_trigger", type_="check")
        batch.drop_column("deploy_trigger")
