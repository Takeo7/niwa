"""Process manager — start/stop project processes (Phase 4, DEPLOY-05)."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Deployment, Project
from .ports import allocate_port


def is_process_alive(pid: int | None) -> bool:
    """Return True if a process with this PID is still running."""
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def start_process(
    session: Session,
    deployment: Deployment,
    project: Project,
) -> None:
    """Spawn the project's start_command and record the PID.

    Sets ``deployment.status = 'starting'``, ``pid``, ``port`` and ``url_local``.
    On failure sets ``deployment.status = 'failed'``.
    """
    if not project.start_command:
        deployment.status = "failed"
        deployment.error = "project has no start_command"
        session.commit()
        return

    try:
        port = allocate_port(session, project_id=project.id)
    except RuntimeError as exc:
        deployment.status = "failed"
        deployment.error = str(exc)
        session.commit()
        return

    env = {**os.environ, "PORT": str(port)}
    artifact = deployment.artifact_path or project.local_path
    cwd = str(Path(artifact)) if artifact else project.local_path

    try:
        proc = subprocess.Popen(
            shlex.split(project.start_command),
            shell=False,
            cwd=cwd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:  # noqa: BLE001
        deployment.status = "failed"
        deployment.error = f"failed to spawn process: {exc}"[:500]
        session.commit()
        return

    deployment.pid = proc.pid
    deployment.port = port
    deployment.url_local = f"http://127.0.0.1:{port}"
    deployment.status = "starting"
    deployment.started_at = datetime.now(timezone.utc)
    session.commit()


def stop_process(session: Session, deployment: Deployment) -> None:
    """Send SIGTERM to the process group; escalate to SIGKILL after 5 s."""
    pid = deployment.pid
    if pid is None:
        deployment.status = "stopped"
        deployment.finished_at = datetime.now(timezone.utc)
        session.commit()
        return

    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    except Exception:  # noqa: BLE001
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not is_process_alive(pid):
            break
        time.sleep(0.1)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, Exception):  # noqa: BLE001
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    deployment.status = "stopped"
    deployment.pid = None
    deployment.finished_at = datetime.now(timezone.utc)
    session.commit()
