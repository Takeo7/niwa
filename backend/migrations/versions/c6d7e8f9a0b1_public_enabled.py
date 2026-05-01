"""Add project public exposure flag.

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "c6d7e8f9a0b1"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects", recreate="always") as batch:
        batch.add_column(
            sa.Column(
                "public_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("projects", recreate="always") as batch:
        batch.drop_column("public_enabled")
