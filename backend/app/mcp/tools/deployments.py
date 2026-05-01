"""MCP deployment tools backed by Niwa deployment services."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ...deployments.service import trigger_deploy
from ...models import Deployment
from ...services import projects as projects_service


def _deployment_dict(row: Deployment) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "task_id": row.task_id,
        "commit_sha": row.commit_sha,
        "deploy_type": row.deploy_type,
        "status": row.status,
        "artifact_path": row.artifact_path,
        "port": row.port,
        "url_local": row.url_local,
        "healthcheck_path": row.healthcheck_path,
        "error": row.error,
        "pid": row.pid,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "last_health_check": (
            row.last_health_check.isoformat() if row.last_health_check else None
        ),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def deploy_trigger(db: Session, project_slug: str) -> dict[str, Any]:
    try:
        project = projects_service.get_project(db, project_slug)
    except projects_service.ProjectNotFound:
        raise HTTPException(status_code=404, detail=f"Project '{project_slug}' not found")
    return _deployment_dict(trigger_deploy(db, project))


def deployment_status(
    db: Session,
    *,
    deployment_id: int | None = None,
    project_slug: str | None = None,
) -> dict[str, Any]:
    if deployment_id is not None:
        deployment = db.get(Deployment, deployment_id)
    elif project_slug:
        try:
            project = projects_service.get_project(db, project_slug)
        except projects_service.ProjectNotFound:
            raise HTTPException(status_code=404, detail=f"Project '{project_slug}' not found")
        deployment = (
            db.query(Deployment)
            .filter(Deployment.project_id == project.id)
            .order_by(Deployment.id.desc())
            .first()
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="deployment_status requires deployment_id or project_slug",
        )

    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return _deployment_dict(deployment)
