"""Add sessions and api_tokens tables for auth (Phase 5, NET-01/02).

Revision ID: d1e2f3a4b5c6
Revises: f98a50e87242
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d1e2f3a4b5c6"
down_revision = "f98a50e87242"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"])

    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", sa.Text, nullable=False, server_default="read"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_api_tokens_token_hash", "api_tokens", ["token_hash"])


def downgrade() -> None:
    op.drop_index("ix_api_tokens_token_hash", "api_tokens")
    op.drop_table("api_tokens")
    op.drop_index("ix_sessions_token_hash", "sessions")
    op.drop_table("sessions")
