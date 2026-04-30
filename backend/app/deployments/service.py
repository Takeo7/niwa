"""Deployment orchestration — trigger, stop, rollback (Phase 4, DEPLOY-08/09)."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import Deployment, Project
from .health import check_health
from .process_manager import start_process, stop_process
from .runner import build_and_stage


def trigger_deploy(session: Session, project: Project) -> Deployment:
    """Create a new Deployment, build+stage, and start if process type."""
    commit_sha: str | None = None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project.local_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            commit_sha = result.stdout.strip()
    except Exception:  # noqa: BLE001
        pass

    deploy_type = project.deploy_type or "static"
    deployment = Deployment(
        project_id=project.id,
        deploy_type=deploy_type,
        status="queued",
        commit_sha=commit_sha,
        healthcheck_path=project.healthcheck_path or "/",
    )
    session.add(deployment)
    session.flush()
    session.commit()

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
        # Verify artifact exists and transition starting → healthy (or unhealthy)
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


def rollback_to(session: Session, project: Project, target_deployment: Deployment) -> Deployment:
    """Create a rollback deployment pointing at the target's artifact.

    For static: creates a new deployment in healthy state with the old artifact.
    For process: stops current and re-starts target (best-effort).
    """
    rollback = Deployment(
        project_id=project.id,
        deploy_type=target_deployment.deploy_type,
        status="queued",
        commit_sha=target_deployment.commit_sha,
        artifact_path=target_deployment.artifact_path,
        healthcheck_path=target_deployment.healthcheck_path,
    )
    session.add(rollback)
    session.flush()
    session.commit()

    session.refresh(rollback)
    if rollback.deploy_type == "process":
        start_process(session, rollback, project)
        session.refresh(rollback)
        # Only mark target rolled_back if the new deployment started successfully
        if rollback.status != "failed":
            target_deployment.status = "rolled_back"
            session.commit()
    else:
        rollback.status = "healthy"
        rollback.url_local = f"/api/deploy/{project.slug}/"
        rollback.finished_at = datetime.now(timezone.utc)
        target_deployment.status = "rolled_back"
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
