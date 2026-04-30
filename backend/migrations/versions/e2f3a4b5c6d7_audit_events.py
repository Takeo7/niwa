"""Add audit_events table (Phase 6, SEC-03).

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(255)),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("target_type", sa.String(64)),
        sa.Column("target_id", sa.String(255)),
        sa.Column("payload_json", sa.Text),
        sa.Column("ip_address", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_actor_type", "audit_events", ["actor_type"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_actor_type", "audit_events")
    op.drop_index("ix_audit_events_action", "audit_events")
    op.drop_table("audit_events")
