"""Deployment orchestration — trigger, stop, rollback (Phase 4, DEPLOY-08/09)."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import Deployment, Project
from .health import check_health
from .process_manager import start_process, stop_process
from .runner import build_and_stage


def _resolve_commit_sha(local_path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=local_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    return None


def trigger_deploy(session: Session, project: Project) -> Deployment:
    """Create a Deployment, build+stage, and start (process) or healthcheck (static)."""
    deploy_type = project.deploy_type or "static"
    deployment = Deployment(
        project_id=project.id,
        deploy_type=deploy_type,
        status="queued",
        commit_sha=_resolve_commit_sha(project.local_path),
        healthcheck_path=project.healthcheck_path or "/",
    )
    session.add(deployment)
    session.commit()
    session.refresh(deployment)

    build_and_stage(session, deployment, project)
    session.refresh(deployment)
    if deployment.status == "failed":
        return deployment

    if deploy_type == "process":
        start_process(session, deployment, project)
        session.refresh(deployment)
    else:
        deployment.url_local = f"/api/deploy/{project.slug}/"
        deployment.finished_at = datetime.now(timezone.utc)
        session.commit()
        check_health(session, deployment)
        session.refresh(deployment)

    return deployment


def stop_deployment(session: Session, deployment: Deployment) -> Deployment:
    """Stop a running deployment."""
    if deployment.deploy_type == "process" and deployment.pid is not None:
        stop_process(session, deployment)
    else:
        deployment.status = "stopped"
        deployment.finished_at = datetime.now(timezone.utc)
        session.commit()
    session.refresh(deployment)
    return deployment


def rollback_to(
    session: Session, project: Project, target: Deployment
) -> Deployment:
    """Create a new deployment pointing at the artifact of ``target``."""
    rollback = Deployment(
        project_id=project.id,
        deploy_type=target.deploy_type,
        status="queued",
        commit_sha=target.commit_sha,
        artifact_path=target.artifact_path,
        healthcheck_path=target.healthcheck_path,
    )
    session.add(rollback)
    session.commit()
    session.refresh(rollback)

    if rollback.deploy_type == "process":
        start_process(session, rollback, project)
        session.refresh(rollback)
        if rollback.status != "failed":
            target.status = "rolled_back"
            session.commit()
    else:
        rollback.url_local = f"/api/deploy/{project.slug}/"
        rollback.finished_at = datetime.now(timezone.utc)
        session.commit()
        check_health(session, rollback)
        session.refresh(rollback)
        if rollback.status == "healthy":
            target.status = "rolled_back"
            session.commit()

    session.refresh(rollback)
    return rollback


def get_active_deployment(session: Session, project_id: int) -> Deployment | None:
    """Return the most recent healthy or starting deployment for a project."""
    return (
        session.query(Deployment)
        .filter(
            Deployment.project_id == project_id,
            Deployment.status.in_(["healthy", "starting"]),
        )
        .order_by(Deployment.id.desc())
        .first()
    )
