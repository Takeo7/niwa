"""Phase 4: deployments table + project deploy settings

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-30

Adds:
- deployments table
- projects deploy settings columns (build_command, start_command, dist_dir, healthcheck_path, deploy_type)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deployments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("commit_sha", sa.String(), nullable=True),
        sa.Column("deploy_type", sa.String(), nullable=False, server_default="static"),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("artifact_path", sa.String(), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("url_local", sa.String(), nullable=True),
        sa.Column("healthcheck_path", sa.String(), nullable=False, server_default="/"),
        sa.Column("build_log", sa.Text(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("last_health_check", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('queued','building','starting','healthy','unhealthy','failed','stopped','rolled_back')",
            name="ck_deployments_status",
        ),
        sa.CheckConstraint(
            "deploy_type IN ('static','process')",
            name="ck_deployments_type",
        ),
    )

    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("build_command", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("start_command", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("dist_dir", sa.String(), nullable=False, server_default="dist"))
        batch_op.add_column(sa.Column("healthcheck_path", sa.String(), nullable=False, server_default="/"))
        batch_op.add_column(sa.Column("deploy_type", sa.String(), nullable=False, server_default="static"))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("deploy_type")
        batch_op.drop_column("healthcheck_path")
        batch_op.drop_column("dist_dir")
        batch_op.drop_column("start_command")
        batch_op.drop_column("build_command")

    op.drop_table("deployments")
