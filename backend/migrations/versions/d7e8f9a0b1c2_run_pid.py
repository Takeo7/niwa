"""Add run process pid.

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "d7e8f9a0b1c2"
down_revision = "c6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs", recreate="always") as batch:
        batch.add_column(sa.Column("pid", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("runs", recreate="always") as batch:
        batch.drop_column("pid")
