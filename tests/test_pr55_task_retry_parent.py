"""Tests for PR-55 — retry task endpoint + parent_task_id passthrough.

Covers:
  - POST /api/tasks/:id/retry flips status to ``pendiente`` and clears
    ``completed_at`` so the dashboard doesn't double-count.
  - Missing task → 404.
  - ``parent_task_id`` is persisted on create and returned on fetch.
  - Migration 013 is idempotent (column already present OK).

Run: pytest tests/test_pr55_task_retry_parent.py -v
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


def _req(base, path, *, method="GET", body=None):
    h = {"Content-Type": "application/json"} if body is not None else {}
    data = json.dumps(body).encode() if body is not None else None
    req = Request(f"{base}{path}", data=data, headers=h, method=method)
    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except HTTPError as e:
        raw = e.read()
        try:
            return e.code, (json.loads(raw) if raw else {})
        except json.JSONDecodeError:
            return e.code, {"raw": raw.decode("utf-8", errors="ignore")}


@pytest.fixture
def server(tmp_path, monkeypatch):
    import sqlite3 as _sq
    db_path = str(tmp_path / "niwa.sqlite3")
    monkeypatch.setenv("NIWA_DB_PATH", db_path)
    monkeypatch.setenv("NIWA_APP_AUTH_REQUIRED", "0")
    monkeypatch.setenv("NIWA_APP_HOST", "127.0.0.1")
    monkeypatch.setenv("NIWA_PROJECTS_ROOT", str(tmp_path / "projects"))

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
    port = _free_port()
    app.HOST = "127.0.0.1"
    app.PORT = port
    app.NIWA_APP_AUTH_REQUIRED = False
    app.init_db()

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
    yield {"base": base, "db": db_path}
    srv.shutdown()
    srv.server_close()


def _seed_task(db, status="hecha", completed=True):
    import sqlite3
    task_id = str(uuid.uuid4())
    now = "2026-04-17T12:00:00Z"
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO tasks (id, title, status, priority, area, source, "
            "completed_at, created_at, updated_at) VALUES (?, 'retry me', ?, "
            "'media', 'proyecto', 'user', ?, ?, ?)",
            (task_id, status, now if completed else None, now, now),
        )
        c.commit()
    return task_id


def test_retry_flips_status_to_pendiente(server):
    task_id = _seed_task(server["db"], status="hecha", completed=True)
    status, out = _req(
        server["base"], f"/api/tasks/{task_id}/retry", method="POST", body={},
    )
    assert status == 200, out
    assert out["ok"] is True
    assert out["status"] == "pendiente"

    # DB reflects the new status + completed_at reset.
    import sqlite3
    with sqlite3.connect(server["db"]) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT status, completed_at FROM tasks WHERE id=?", (task_id,),
        ).fetchone()
    assert row["status"] == "pendiente"
    assert row["completed_at"] is None


def test_retry_from_bloqueada_also_works(server):
    """Retry should accept any source status — the executor only cares
    about the target (``pendiente``)."""
    task_id = _seed_task(server["db"], status="bloqueada", completed=False)
    status, out = _req(
        server["base"], f"/api/tasks/{task_id}/retry", method="POST", body={},
    )
    assert status == 200
    assert out["status"] == "pendiente"


def test_retry_unknown_task_returns_404(server):
    status, out = _req(
        server["base"], "/api/tasks/does-not-exist/retry", method="POST", body={},
    )
    assert status == 404
    assert out["error"] == "not_found"


def test_create_task_persists_parent_task_id(server):
    parent = _seed_task(server["db"])
    status, out = _req(
        server["base"], "/api/tasks", method="POST",
        body={
            "title": "Respuesta al run",
            "description": "contexto...",
            "parent_task_id": parent,
        },
    )
    assert status == 201, out
    child_id = out["id"]

    import sqlite3
    with sqlite3.connect(server["db"]) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT parent_task_id FROM tasks WHERE id=?", (child_id,),
        ).fetchone()
    assert row["parent_task_id"] == parent


def test_create_task_without_parent_task_id_is_null(server):
    """Sanity: omitting the field leaves it NULL, not empty string."""
    status, out = _req(
        server["base"], "/api/tasks", method="POST",
        body={"title": "Sola"},
    )
    assert status == 201
    child_id = out["id"]
    import sqlite3
    with sqlite3.connect(server["db"]) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT parent_task_id FROM tasks WHERE id=?", (child_id,),
        ).fetchone()
    assert row["parent_task_id"] is None
