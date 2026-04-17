"""Tests for PR-47 HTTP endpoints — deployments.

Covers:
  - GET  /api/deployments
  - POST /api/projects/:key/deploy
  - POST /api/projects/:key/undeploy

The hosting module is patched during the test:
  - ``_reload_caddy`` → no-op (no child process).
  - ``CADDYFILE_PATH`` → tmp file (no /tmp writes collide).

Run: pytest tests/test_deployments_endpoints.py -v
"""
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _request(base, path, *, method="GET", body=None):
    h = {"Content-Type": "application/json"} if body is not None else {}
    data = json.dumps(body).encode() if body is not None else None
    req = Request(f"{base}{path}", data=data, headers=h, method=method)
    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read()
            out = json.loads(raw) if raw else {}
            return resp.status, out
    except HTTPError as e:
        raw = e.read()
        try:
            out = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            out = {"raw": raw.decode("utf-8", errors="ignore")}
        return e.code, out


@pytest.fixture
def server():
    import sqlite3 as _sq
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    caddy_path = tempfile.mktemp(suffix="-Caddyfile")
    proj_dir = tempfile.mkdtemp(prefix="niwa-proj-")
    # Create a dummy file so the directory has something.
    Path(proj_dir, "index.html").write_text("<html>hi</html>")

    port = _free_port()
    os.environ["NIWA_DB_PATH"] = db_path
    os.environ["NIWA_APP_PORT"] = str(port)
    os.environ["NIWA_APP_AUTH_REQUIRED"] = "0"
    os.environ["NIWA_APP_HOST"] = "127.0.0.1"
    os.environ["NIWA_HOSTING_CADDYFILE"] = caddy_path

    # Pre-apply schema.sql + deployments migration so migrations that
    # reference existing tables (e.g. 005 indexes `settings(key)`) don't
    # blow up on import — the top-level _run_migrations() runs as a
    # side effect of `import app`. The `deployments` table is NOT in
    # schema.sql (known bug #2), so we apply migration 003 explicitly.
    schema_sql = Path(ROOT_DIR, "niwa-app", "db", "schema.sql").read_text()
    deployments_sql = Path(
        ROOT_DIR, "niwa-app", "db", "migrations", "003_deployments.sql"
    ).read_text()
    _c = _sq.connect(db_path)
    _c.executescript(schema_sql)
    _c.executescript(deployments_sql)
    _c.commit()
    _c.close()

    if "app" in sys.modules:
        import app
        app.DB_PATH = Path(db_path)
    else:
        import app

    import hosting
    # Neutralise side effects: no caddy reload, custom tmp caddyfile path.
    hosting.CADDYFILE_PATH = Path(caddy_path)
    hosting._reload_caddy = lambda: None

    app.HOST = "127.0.0.1"
    app.PORT = port
    app.NIWA_APP_AUTH_REQUIRED = False
    app.init_db()

    conn = app.db_conn()
    now = app.now_iso()
    project_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO projects (id, slug, name, area, directory, created_at, updated_at) "
        "VALUES (?, 'site-a', 'Site A', 'proyecto', ?, ?, ?)",
        (project_id, proj_dir, now, now),
    )
    # Second project without directory — used to test 400.
    project_no_dir = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
        "VALUES (?, 'no-dir', 'No Dir', 'proyecto', ?, ?)",
        (project_no_dir, now, now),
    )
    conn.commit()
    conn.close()

    srv = ThreadingHTTPServer(("127.0.0.1", port), app.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(30):
        try:
            urlopen(f"{base}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.1)

    yield {
        "base": base,
        "project_id": project_id,
        "project_no_dir": project_no_dir,
        "proj_dir": proj_dir,
        "db_path": db_path,
    }

    srv.shutdown()
    srv.server_close()
    try:
        os.unlink(db_path)
    except Exception:
        pass


def test_list_deployments_empty(server):
    status, out = _request(server["base"], "/api/deployments")
    assert status == 200
    assert out == {"deployments": []}


def test_deploy_project_by_slug_creates_row(server):
    status, out = _request(
        server["base"], "/api/projects/site-a/deploy", method="POST", body={}
    )
    assert status == 200, out
    assert out["ok"] is True
    assert out["slug"] == "site-a"
    assert out["url"].endswith("/site-a/") or "site-a." in out["url"]
    # Listed afterwards.
    status, listing = _request(server["base"], "/api/deployments")
    assert status == 200
    deployments = listing["deployments"]
    assert len(deployments) == 1
    assert deployments[0]["project_id"] == server["project_id"]
    assert deployments[0]["status"] == "active"


def test_deploy_project_by_id_also_works(server):
    status, out = _request(
        server["base"],
        f"/api/projects/{server['project_id']}/deploy",
        method="POST",
        body={},
    )
    assert status == 200, out
    assert out["ok"] is True


def test_deploy_project_not_found(server):
    status, out = _request(
        server["base"], "/api/projects/ghost/deploy", method="POST", body={}
    )
    assert status == 404
    assert out["error"] == "not_found"


def test_deploy_project_without_directory_returns_400(server):
    status, out = _request(
        server["base"], "/api/projects/no-dir/deploy", method="POST", body={}
    )
    assert status == 400
    assert out["error"] == "project_has_no_directory"


def test_undeploy_project_marks_inactive(server):
    _request(
        server["base"], "/api/projects/site-a/deploy", method="POST", body={}
    )
    status, out = _request(
        server["base"], "/api/projects/site-a/undeploy", method="POST", body={}
    )
    assert status == 200
    assert out["ok"] is True
    # After undeploy the active listing is empty.
    status, listing = _request(server["base"], "/api/deployments")
    assert status == 200
    assert listing["deployments"] == []


def test_undeploy_project_not_found(server):
    status, out = _request(
        server["base"], "/api/projects/ghost/undeploy", method="POST", body={}
    )
    assert status == 404
    assert out["error"] == "not_found"


def test_deploy_ignores_payload_slug_and_directory(server):
    """Security pin: payload-supplied slug/directory MUST be ignored so an
    authenticated admin can't publish arbitrary host paths (``/etc``,
    ``/root/...``) as static sites by abusing the endpoint. The only
    values trusted are the project's own slug + directory in SQLite.
    """
    status, out = _request(
        server["base"],
        "/api/projects/site-a/deploy",
        method="POST",
        body={"slug": "evil-slug", "directory": "/etc"},
    )
    assert status == 200, out
    # The stored deployment uses the project's slug + directory, not the
    # attacker-supplied ones.
    assert out["slug"] == "site-a"
    assert out["directory"] == server["proj_dir"]
    status, listing = _request(server["base"], "/api/deployments")
    assert status == 200
    deployments = listing["deployments"]
    assert len(deployments) == 1
    assert deployments[0]["slug"] == "site-a"
    assert deployments[0]["directory"] == server["proj_dir"]
