"""Tests for Phase 4 versioned deployments — service, ports, API."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest


PROJECT_PAYLOAD = {
    "slug": "demo",
    "name": "Demo",
    "kind": "web-deployable",
    "local_path": "",  # set per-test
    "deploy_type": "static",
    "dist_dir": "dist",
    "healthcheck_path": "/index.html",
}


def _process_project_path(tmp_path: Path) -> Path:
    project = tmp_path / "process-app"
    dist = project / "dist"
    dist.mkdir(parents=True)
    (dist / "server.py").write_text(
        "import time\nprint('process-started', flush=True)\ntime.sleep(60)\n",
        encoding="utf-8",
    )
    return project


@pytest.fixture()
def static_project_path(tmp_path: Path) -> Path:
    project = tmp_path / "myapp"
    (project / "dist").mkdir(parents=True)
    (project / "dist" / "index.html").write_text("<html>hi</html>")
    return project


@pytest.fixture()
def niwa_home_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".niwa"
    home.mkdir()
    monkeypatch.setenv("NIWA_HOME", str(home))
    return home


def test_static_deploy_creates_artifact_and_marks_healthy(
    client, static_project_path: Path, niwa_home_tmp: Path
) -> None:
    payload = {**PROJECT_PAYLOAD, "local_path": str(static_project_path)}
    client.post("/api/projects", json=payload)

    resp = client.post("/api/projects/demo/deployments")
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["deploy_type"] == "static"
    assert body["artifact_path"] is not None
    assert Path(body["artifact_path"]).exists()
    assert (Path(body["artifact_path"]) / "index.html").exists()


def test_deploy_fails_when_dist_dir_missing(
    client, tmp_path: Path, niwa_home_tmp: Path
) -> None:
    project = tmp_path / "noapp"
    project.mkdir()  # no dist/
    payload = {**PROJECT_PAYLOAD, "local_path": str(project)}
    client.post("/api/projects", json=payload)

    resp = client.post("/api/projects/demo/deployments")
    body = resp.json()
    assert body["status"] == "failed"
    assert "dist_dir" in (body.get("error") or "")


def test_list_deployments(client, static_project_path: Path, niwa_home_tmp: Path) -> None:
    payload = {**PROJECT_PAYLOAD, "local_path": str(static_project_path)}
    client.post("/api/projects", json=payload)
    client.post("/api/projects/demo/deployments")
    client.post("/api/projects/demo/deployments")

    resp = client.get("/api/projects/demo/deployments")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    # Most recent first
    assert rows[0]["id"] > rows[1]["id"]


def test_stop_deployment(client, static_project_path: Path, niwa_home_tmp: Path) -> None:
    payload = {**PROJECT_PAYLOAD, "local_path": str(static_project_path)}
    client.post("/api/projects", json=payload)
    d = client.post("/api/projects/demo/deployments").json()

    resp = client.post(f"/api/deployments/{d['id']}/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"


def test_stop_already_stopped_returns_409(
    client, static_project_path: Path, niwa_home_tmp: Path
) -> None:
    payload = {**PROJECT_PAYLOAD, "local_path": str(static_project_path)}
    client.post("/api/projects", json=payload)
    d = client.post("/api/projects/demo/deployments").json()
    client.post(f"/api/deployments/{d['id']}/stop")

    resp = client.post(f"/api/deployments/{d['id']}/stop")
    assert resp.status_code == 409


def test_rollback_creates_new_deployment_pointing_at_old_artifact(
    client, static_project_path: Path, niwa_home_tmp: Path
) -> None:
    payload = {**PROJECT_PAYLOAD, "local_path": str(static_project_path)}
    client.post("/api/projects", json=payload)
    first = client.post("/api/projects/demo/deployments").json()
    second = client.post("/api/projects/demo/deployments").json()

    rb = client.post(f"/api/deployments/{first['id']}/rollback")
    assert rb.status_code == 200
    body = rb.json()
    assert body["id"] != first["id"]
    assert body["artifact_path"] == first["artifact_path"]


def test_rollback_404_when_no_artifact(client, niwa_home_tmp: Path) -> None:
    resp = client.post("/api/deployments/9999/rollback")
    assert resp.status_code == 404


def test_deploy_unknown_project_returns_404(client) -> None:
    resp = client.post("/api/projects/ghost/deployments")
    assert resp.status_code == 404


def test_active_deployment_is_served_by_static_route(
    client, static_project_path: Path, niwa_home_tmp: Path
) -> None:
    payload = {**PROJECT_PAYLOAD, "local_path": str(static_project_path)}
    client.post("/api/projects", json=payload)
    client.post("/api/projects/demo/deployments")

    # The static SPA route should now serve from the active deployment's artifact
    resp = client.get("/api/deploy/demo/index.html")
    assert resp.status_code == 200
    assert "<html>hi</html>" in resp.text


def test_port_allocator_skips_used_ports(client, static_project_path: Path) -> None:
    from app.api.deps import get_session
    from app.deployments.ports import allocate_port, PORT_RANGE_START
    from app.models import Deployment

    db = next(client.app.dependency_overrides[get_session]())

    # Insert a project then a fake "healthy" process deployment using the first port
    payload = {**PROJECT_PAYLOAD, "local_path": str(static_project_path), "deploy_type": "process"}
    client.post("/api/projects", json=payload)
    project_id = db.query.__self__.query if False else 1  # noqa
    fake = Deployment(
        project_id=1,
        deploy_type="process",
        status="healthy",
        port=PORT_RANGE_START,
    )
    db.add(fake)
    db.commit()

    port = allocate_port(db, project_id=1)
    assert port != PORT_RANGE_START
    assert port >= PORT_RANGE_START


def test_get_deployment_404(client) -> None:
    resp = client.get("/api/deployments/9999")
    assert resp.status_code == 404


def test_healthcheck_endpoint(
    client, static_project_path: Path, niwa_home_tmp: Path
) -> None:
    payload = {**PROJECT_PAYLOAD, "local_path": str(static_project_path)}
    client.post("/api/projects", json=payload)
    d = client.post("/api/projects/demo/deployments").json()

    resp = client.post(f"/api/deployments/{d['id']}/healthcheck")
    assert resp.status_code == 200
    assert resp.json()["last_health_check"] is not None


def test_process_deploy_writes_process_log(
    client, tmp_path: Path, niwa_home_tmp: Path
) -> None:
    project = _process_project_path(tmp_path)
    payload = {
        **PROJECT_PAYLOAD,
        "local_path": str(project),
        "deploy_type": "process",
        "start_command": f"{sys.executable} server.py",
    }
    client.post("/api/projects", json=payload)

    body = client.post("/api/projects/demo/deployments").json()
    assert body["status"] == "starting"
    log_path = niwa_home_tmp / "deployments" / "demo" / str(body["id"]) / "process.log"
    assert log_path.exists()

    client.post(f"/api/deployments/{body['id']}/stop")


def test_new_process_deploy_stops_previous_process(
    client, tmp_path: Path, niwa_home_tmp: Path
) -> None:
    project = _process_project_path(tmp_path)
    payload = {
        **PROJECT_PAYLOAD,
        "local_path": str(project),
        "deploy_type": "process",
        "start_command": f"{sys.executable} server.py",
    }
    client.post("/api/projects", json=payload)

    first = client.post("/api/projects/demo/deployments").json()
    second = client.post("/api/projects/demo/deployments").json()
    first_after = client.get(f"/api/deployments/{first['id']}").json()

    assert first_after["status"] == "stopped"
    assert first_after["pid"] is None
    assert second["status"] == "starting"

    client.post(f"/api/deployments/{second['id']}/stop")
