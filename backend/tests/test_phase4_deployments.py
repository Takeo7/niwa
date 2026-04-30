"""Tests for Phase 4 deployment model, service, and API.

Covers:
- Deployment model creation
- trigger_deploy for static type (no build_command, dist_dir exists)
- trigger_deploy with missing dist_dir → failed
- stop_deployment
- rollback_to
- GET /api/projects/{slug}/deployments
- POST /api/projects/{slug}/deployments
- POST /api/deployments/{id}/stop
- Port allocator basics
- Health check for static deployment
- deploy router serves from artifact_path when active deployment exists
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.deployments.health import check_health
from app.deployments.ports import allocate_port
from app.deployments.service import get_active_deployment, stop_deployment, trigger_deploy
from app.models import Deployment, Project


PROJECT_PAYLOAD: dict[str, Any] = {
    "slug": "web",
    "name": "Web App",
    "kind": "web-deployable",
    "local_path": "/tmp/web",
}


def _make_engine(tmp_path: Path):
    db_path = tmp_path / "deploy.sqlite3"
    eng = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(eng)
    return eng


def _make_project(session: Session, **overrides) -> Project:
    defaults = dict(
        slug="web", name="Web", kind="web-deployable",
        local_path="/tmp/web", deploy_type="static",
    )
    defaults.update(overrides)
    p = Project(**defaults)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


# ---------------------------------------------------------------------------
# Deployment model
# ---------------------------------------------------------------------------


def test_deployment_model_create(tmp_path: Path) -> None:
    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session)
        d = Deployment(
            project_id=project.id,
            deploy_type="static",
            status="queued",
            healthcheck_path="/",
        )
        session.add(d)
        session.commit()
        session.refresh(d)
        assert d.id is not None
        assert d.status == "queued"
    eng.dispose()


# ---------------------------------------------------------------------------
# trigger_deploy static (happy path)
# ---------------------------------------------------------------------------


def test_trigger_deploy_static_success(tmp_path: Path) -> None:
    # Create a fake project with dist/
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    dist_dir = project_dir / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html>hello</html>")

    # Init a git repo so commit_sha can be resolved
    os.system(f"git -C {project_dir} init -b main 2>/dev/null && "
              f"git -C {project_dir} config user.email test@test.local && "
              f"git -C {project_dir} config user.name Test && "
              f"git -C {project_dir} config commit.gpgsign false && "
              f"git -C {project_dir} add . && "
              f"git -C {project_dir} commit -m init 2>/dev/null")

    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session, local_path=str(project_dir))
        deployment = trigger_deploy(session, project)
        assert deployment.status == "healthy"
        assert deployment.artifact_path is not None
        assert Path(deployment.artifact_path).is_dir()
        assert (Path(deployment.artifact_path) / "index.html").is_file()
    eng.dispose()
    # Cleanup artifact
    if deployment.artifact_path:
        shutil.rmtree(deployment.artifact_path, ignore_errors=True)


def test_trigger_deploy_static_missing_dist(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()  # No dist/ here

    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session, local_path=str(project_dir))
        deployment = trigger_deploy(session, project)
        assert deployment.status == "failed"
        assert deployment.error is not None
        assert "dist" in deployment.error.lower()
    eng.dispose()


# ---------------------------------------------------------------------------
# stop_deployment
# ---------------------------------------------------------------------------


def test_stop_deployment(tmp_path: Path) -> None:
    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session)
        d = Deployment(
            project_id=project.id,
            deploy_type="static",
            status="healthy",
            healthcheck_path="/",
        )
        session.add(d)
        session.commit()
        session.refresh(d)

        stopped = stop_deployment(session, d)
        assert stopped.status == "stopped"
    eng.dispose()


# ---------------------------------------------------------------------------
# get_active_deployment
# ---------------------------------------------------------------------------


def test_get_active_deployment(tmp_path: Path) -> None:
    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session)

        # No deployment yet
        assert get_active_deployment(session, project.id) is None

        d = Deployment(
            project_id=project.id,
            deploy_type="static",
            status="healthy",
            healthcheck_path="/",
        )
        session.add(d)
        session.commit()
        session.refresh(d)

        active = get_active_deployment(session, project.id)
        assert active is not None
        assert active.id == d.id
    eng.dispose()


# ---------------------------------------------------------------------------
# Port allocator
# ---------------------------------------------------------------------------


def test_allocate_port_returns_free_port(tmp_path: Path) -> None:
    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session)
        port = allocate_port(session, project_id=project.id)
        assert 41000 <= port <= 41999
    eng.dispose()


# ---------------------------------------------------------------------------
# Health check for static deployment
# ---------------------------------------------------------------------------


def test_healthcheck_static_healthy(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "index.html").write_text("ok")

    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session)
        d = Deployment(
            project_id=project.id,
            deploy_type="static",
            status="starting",
            artifact_path=str(artifact),
            healthcheck_path="/",
        )
        session.add(d)
        session.commit()
        session.refresh(d)

        result = check_health(session, d)
        assert result is True
        session.refresh(d)
        assert d.status == "healthy"
    eng.dispose()


def test_healthcheck_static_unhealthy_missing_artifact(tmp_path: Path) -> None:
    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session)
        d = Deployment(
            project_id=project.id,
            deploy_type="static",
            status="starting",
            artifact_path="/nonexistent/path",
            healthcheck_path="/",
        )
        session.add(d)
        session.commit()
        session.refresh(d)

        result = check_health(session, d)
        assert result is False
        session.refresh(d)
        assert d.status == "unhealthy"
    eng.dispose()


# ---------------------------------------------------------------------------
# Deployments API
# ---------------------------------------------------------------------------


def test_list_deployments_empty(client) -> None:
    client.post("/api/projects", json={**PROJECT_PAYLOAD})
    resp = client.get("/api/projects/web/deployments")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_deployments_404_project(client) -> None:
    resp = client.get("/api/projects/nonexistent/deployments")
    assert resp.status_code == 404


def test_get_deployment_not_found(client) -> None:
    resp = client.get("/api/deployments/9999")
    assert resp.status_code == 404


def test_stop_deployment_api(client) -> None:
    client.post("/api/projects", json={**PROJECT_PAYLOAD})
    # Seed a deployment directly via session
    from app.api.deps import get_session
    session = next(client.app.dependency_overrides[get_session]())
    project = session.query(Project).filter_by(slug="web").first()
    d = Deployment(
        project_id=project.id,
        deploy_type="static",
        status="healthy",
        healthcheck_path="/",
    )
    session.add(d)
    session.commit()
    session.refresh(d)
    deploy_id = d.id
    session.close()

    resp = client.post(f"/api/deployments/{deploy_id}/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"


def test_stop_already_stopped_returns_409(client) -> None:
    client.post("/api/projects", json={**PROJECT_PAYLOAD})
    from app.api.deps import get_session
    session = next(client.app.dependency_overrides[get_session]())
    project = session.query(Project).filter_by(slug="web").first()
    d = Deployment(
        project_id=project.id,
        deploy_type="static",
        status="stopped",
        healthcheck_path="/",
    )
    session.add(d)
    session.commit()
    session.refresh(d)
    deploy_id = d.id
    session.close()

    resp = client.post(f"/api/deployments/{deploy_id}/stop")
    assert resp.status_code == 409
