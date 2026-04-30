"""Deployments API — trigger, list, detail, stop, rollback (Phase 4, DEPLOY-08)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..deployments.health import check_health
from ..deployments.service import get_active_deployment, rollback_to, stop_deployment, trigger_deploy
from ..models import Deployment, Project
from ..services.projects import ProjectNotFound, get_project
from .deps import get_session


router = APIRouter(tags=["deployments"])


class DeploymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    task_id: int | None
    commit_sha: str | None
    deploy_type: str
    status: str
    artifact_path: str | None
    port: int | None
    url_local: str | None
    healthcheck_path: str
    build_log: str | None
    error: str | None
    pid: int | None
    started_at: datetime | None
    finished_at: datetime | None
    last_health_check: datetime | None
    created_at: datetime


@router.get("/projects/{slug}/deployments", response_model=list[DeploymentRead])
def list_deployments(
    slug: str,
    session: Session = Depends(get_session),
) -> list[DeploymentRead]:
    try:
        project = get_project(session, slug)
    except ProjectNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    rows = (
        session.query(Deployment)
        .filter(Deployment.project_id == project.id)
        .order_by(Deployment.id.desc())
        .all()
    )
    return [DeploymentRead.model_validate(r) for r in rows]


@router.get("/deployments/{deployment_id}", response_model=DeploymentRead)
def get_deployment(
    deployment_id: int,
    session: Session = Depends(get_session),
) -> DeploymentRead:
    d = session.get(Deployment, deployment_id)
    if d is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deployment not found")
    return DeploymentRead.model_validate(d)


@router.post("/projects/{slug}/deployments", response_model=DeploymentRead, status_code=status.HTTP_201_CREATED)
def create_deployment(
    slug: str,
    session: Session = Depends(get_session),
) -> DeploymentRead:
    """Trigger a new deployment for the project."""
    try:
        project = get_project(session, slug)
    except ProjectNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    deployment = trigger_deploy(session, project)
    return DeploymentRead.model_validate(deployment)


@router.post("/deployments/{deployment_id}/stop", response_model=DeploymentRead)
def stop_deploy(
    deployment_id: int,
    session: Session = Depends(get_session),
) -> DeploymentRead:
    d = session.get(Deployment, deployment_id)
    if d is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deployment not found")
    if d.status in ("stopped", "failed", "rolled_back"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="deployment already terminal")
    d = stop_deployment(session, d)
    return DeploymentRead.model_validate(d)


@router.post("/deployments/{deployment_id}/rollback", response_model=DeploymentRead)
def do_rollback(
    deployment_id: int,
    session: Session = Depends(get_session),
) -> DeploymentRead:
    """Create a new deployment from the artifact of the given deployment."""
    d = session.get(Deployment, deployment_id)
    if d is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deployment not found")
    if not d.artifact_path:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="deployment has no artifact to roll back to")
    project = session.get(Project, d.project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    new_d = rollback_to(session, project, d)
    return DeploymentRead.model_validate(new_d)


@router.post("/deployments/{deployment_id}/healthcheck", response_model=DeploymentRead)
def run_healthcheck(
    deployment_id: int,
    session: Session = Depends(get_session),
) -> DeploymentRead:
    d = session.get(Deployment, deployment_id)
    if d is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deployment not found")
    check_health(session, d)
    session.refresh(d)
    return DeploymentRead.model_validate(d)
