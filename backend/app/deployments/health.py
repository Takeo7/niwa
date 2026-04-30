"""Healthcheck logic for static and process deployments (Phase 4, DEPLOY-07)."""

from __future__ import annotations

import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Deployment
from .process_manager import is_process_alive

_HEALTH_TIMEOUT = 3  # seconds


def check_health(session: Session, deployment: Deployment) -> bool:
    """Run a single healthcheck and update deployment status.

    Returns True if healthy, False otherwise.
    """
    now = datetime.now(timezone.utc)
    deployment.last_health_check = now

    if deployment.deploy_type == "static":
        healthy = _check_static(deployment)
    else:
        healthy = _check_process(deployment)

    if healthy:
        if deployment.status in ("starting", "unhealthy"):
            deployment.status = "healthy"
    else:
        if deployment.status in ("starting", "healthy"):
            deployment.status = "unhealthy"
        if deployment.deploy_type == "process" and not is_process_alive(deployment.pid):
            deployment.status = "stopped"
            deployment.pid = None
            deployment.finished_at = now

    session.commit()
    return healthy


def _check_static(deployment: Deployment) -> bool:
    artifact = deployment.artifact_path
    if not artifact:
        return False
    path = Path(artifact)
    healthcheck = deployment.healthcheck_path.lstrip("/") or "index.html"
    target = path / healthcheck
    return target.is_file()


def _check_process(deployment: Deployment) -> bool:
    if not is_process_alive(deployment.pid):
        return False
    port = deployment.port
    if not port:
        return False
    hpath = deployment.healthcheck_path or "/"
    url = f"http://127.0.0.1:{port}{hpath}"
    try:
        with urllib.request.urlopen(url, timeout=_HEALTH_TIMEOUT) as resp:
            return 200 <= resp.status < 400
    except Exception:  # noqa: BLE001
        return False
