"""phase 4: deployments table + project deploy fields

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-04-30

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New columns on projects.
    with op.batch_alter_table("projects", recreate="auto") as batch:
        batch.add_column(
            sa.Column(
                "deploy_type",
                sa.String(),
                nullable=False,
                server_default="static",
            )
        )
        batch.add_column(sa.Column("build_command", sa.String(), nullable=True))
        batch.add_column(sa.Column("dist_dir", sa.String(), nullable=True))
        batch.add_column(sa.Column("start_command", sa.String(), nullable=True))
        batch.add_column(sa.Column("healthcheck_path", sa.String(), nullable=True))
        batch.create_check_constraint(
            "ck_projects_deploy_type",
            "deploy_type IN ('static','process')",
        )

    # New deployments table.
    op.create_table(
        "deployments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("commit_sha", sa.String(), nullable=True),
        sa.Column(
            "deploy_type",
            sa.String(),
            nullable=False,
            server_default="static",
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("artifact_path", sa.String(), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("url_local", sa.String(), nullable=True),
        sa.Column(
            "healthcheck_path",
            sa.String(),
            nullable=False,
            server_default="/",
        ),
        sa.Column("build_log", sa.Text(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("last_health_check", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('queued','building','starting','healthy','unhealthy',"
            "'failed','stopped','rolled_back')",
            name="ck_deployments_status",
        ),
        sa.CheckConstraint(
            "deploy_type IN ('static','process')",
            name="ck_deployments_type",
        ),
    )
    op.create_index(
        "ix_deployments_project_id", "deployments", ["project_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_deployments_project_id", table_name="deployments")
    op.drop_table("deployments")
    with op.batch_alter_table("projects", recreate="auto") as batch:
        batch.drop_constraint("ck_projects_deploy_type", type_="check")
        batch.drop_column("healthcheck_path")
        batch.drop_column("start_command")
        batch.drop_column("dist_dir")
        batch.drop_column("build_command")
        batch.drop_column("deploy_type")
