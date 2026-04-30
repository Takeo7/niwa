"""Build runner — execute a project's build_command and capture logs (Phase 4, DEPLOY-03)."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Deployment, Project


_BUILD_TIMEOUT = 300  # seconds


def _get_niwa_home() -> Path:
    return Path(os.environ.get("NIWA_HOME", Path.home() / ".niwa"))


def build_and_stage(
    session: Session,
    deployment: Deployment,
    project: Project,
) -> None:
    """Run build_command (if any) and copy dist_dir to a versioned artifact path.

    On success: sets ``deployment.status = 'starting'`` and ``artifact_path``.
    On failure: sets ``deployment.status = 'failed'`` and ``deployment.error``.
    """
    deployment.status = "building"
    deployment.started_at = datetime.now(timezone.utc)
    session.commit()

    dist_dir = project.dist_dir or "dist"
    local_path = project.local_path

    build_log_parts: list[str] = []

    # Run build_command if defined
    if project.build_command:
        try:
            result = subprocess.run(
                shlex.split(project.build_command),
                shell=False,
                cwd=local_path,
                capture_output=True,
                text=True,
                timeout=_BUILD_TIMEOUT,
            )
            build_log_parts.append(f"$ {project.build_command}\n")
            build_log_parts.append(result.stdout)
            if result.stderr:
                build_log_parts.append(result.stderr)
            if result.returncode != 0:
                deployment.status = "failed"
                deployment.error = f"build exited {result.returncode}"
                deployment.build_log = "".join(build_log_parts)[-20_000:]
                deployment.finished_at = datetime.now(timezone.utc)
                session.commit()
                return
        except subprocess.TimeoutExpired:
            deployment.status = "failed"
            deployment.error = "build timed out"
            deployment.build_log = "".join(build_log_parts)[-20_000:]
            deployment.finished_at = datetime.now(timezone.utc)
            session.commit()
            return
        except Exception as exc:  # noqa: BLE001
            deployment.status = "failed"
            deployment.error = str(exc)[:500]
            deployment.finished_at = datetime.now(timezone.utc)
            session.commit()
            return

    # Stage dist_dir to versioned artifact directory
    src = Path(local_path) / dist_dir
    if not src.is_dir():
        deployment.status = "failed"
        deployment.error = f"dist_dir '{dist_dir}' not found in {local_path}"
        deployment.build_log = "".join(build_log_parts)[-20_000:]
        deployment.finished_at = datetime.now(timezone.utc)
        session.commit()
        return

    slug = project.slug
    deploy_id = deployment.id
    artifact_dir = _get_niwa_home() / "deployments" / slug / str(deploy_id)
    try:
        artifact_dir.parent.mkdir(parents=True, exist_ok=True)
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        shutil.copytree(str(src), str(artifact_dir))
    except Exception as exc:  # noqa: BLE001
        deployment.status = "failed"
        deployment.error = f"staging failed: {exc}"
        deployment.build_log = "".join(build_log_parts)[-20_000:]
        deployment.finished_at = datetime.now(timezone.utc)
        session.commit()
        return

    deployment.artifact_path = str(artifact_dir)
    deployment.build_log = ("".join(build_log_parts) or "(no build_command)").strip()[-20_000:]
    deployment.status = "starting"
    session.commit()
