"""Add review loop iteration fields.

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "f9a0b1c2d3e4"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects", recreate="always") as batch:
        batch.add_column(
            sa.Column(
                "max_review_iterations",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )

    with op.batch_alter_table("task_reviews", recreate="always") as batch:
        batch.add_column(
            sa.Column(
                "iteration",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("task_reviews", recreate="always") as batch:
        batch.drop_column("iteration")

    with op.batch_alter_table("projects", recreate="always") as batch:
        batch.drop_column("max_review_iterations")
