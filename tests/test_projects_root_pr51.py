"""Tests for PR-51 — executor-writable projects root + auto-generate
directory on POST /api/projects.

Covers:
  - POST /api/projects without `directory` generates one under the
    configured root.
  - POST /api/projects with explicit `directory` respects it.
  - `_default_projects_root()` honors ``NIWA_PROJECTS_ROOT`` env var.
  - Executor's ``_resolve_project_dir`` auto-heals missing dirs inside
    the managed root.
  - Executor refuses to auto-create dirs outside the managed root.

Run: pytest tests/test_projects_root_pr51.py -v
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

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
BIN_DIR = os.path.join(ROOT_DIR, "bin")
for p in (BACKEND_DIR, BIN_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _req(base, path, *, method="GET", body=None):
    h = {"Content-Type": "application/json"} if body is not None else {}
    data = json.dumps(body).encode() if body is not None else None
    req = Request(f"{base}{path}", data=data, headers=h, method=method)
    with urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read() or b"{}")


@pytest.fixture
def app_server(tmp_path, monkeypatch):
    """Minimal app server with projects root pointed at tmp_path."""
    import sqlite3 as _sq
    db_path = str(tmp_path / "niwa.sqlite3")
    projects_root = tmp_path / "projects"
    projects_root.mkdir()

    monkeypatch.setenv("NIWA_DB_PATH", db_path)
    monkeypatch.setenv("NIWA_APP_AUTH_REQUIRED", "0")
    monkeypatch.setenv("NIWA_APP_HOST", "127.0.0.1")
    monkeypatch.setenv("NIWA_PROJECTS_ROOT", str(projects_root))

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

    yield {"base": base, "projects_root": projects_root, "app": app}
    srv.shutdown()
    srv.server_close()


def test_default_projects_root_respects_env(app_server, monkeypatch):
    """``app_server`` already imports app with a valid DB. We just need
    to poke the env var and call the helper."""
    app_mod = app_server["app"]
    monkeypatch.setenv("NIWA_PROJECTS_ROOT", "/custom/proj/root")
    assert app_mod._default_projects_root() == Path("/custom/proj/root")
    monkeypatch.delenv("NIWA_PROJECTS_ROOT", raising=False)
    # Fallback is the /home/niwa/projects convention.
    assert app_mod._default_projects_root() == Path("/home/niwa/projects")


def test_post_projects_auto_generates_directory(app_server):
    status, out = _req(
        app_server["base"], "/api/projects", method="POST",
        body={"name": "Mi sitio web"},
    )
    assert status == 201, out
    # Directory is returned in the response.
    assert out["directory"]
    expected_root = str(app_server["projects_root"])
    assert out["directory"].startswith(expected_root), (
        f"generated {out['directory']} not under {expected_root}"
    )
    # And the slug is in the path.
    assert out["slug"] in out["directory"]


def test_post_projects_respects_explicit_directory(app_server, tmp_path):
    explicit = str(tmp_path / "custom-path")
    status, out = _req(
        app_server["base"], "/api/projects", method="POST",
        body={"name": "Explicito", "directory": explicit},
    )
    assert status == 201, out
    assert out["directory"] == explicit


def test_post_projects_empty_directory_string_triggers_auto_gen(app_server):
    """Empty string (not missing key) must be treated the same as
    missing — the UI might POST `directory: ''` for a user that didn't
    type anything."""
    status, out = _req(
        app_server["base"], "/api/projects", method="POST",
        body={"name": "Vacio", "directory": "   "},
    )
    assert status == 201
    assert out["directory"]
    assert out["directory"] != ""
    assert out["directory"] != "   "


# ── Executor side: auto-heal missing project_dir when under root ──


@pytest.fixture
def executor(tmp_path, monkeypatch):
    niwa_home = tmp_path / "niwa-home"
    (niwa_home / "secrets").mkdir(parents=True)
    (niwa_home / "secrets" / "mcp.env").write_text("")
    db = niwa_home / "data" / "niwa.sqlite3"
    db.parent.mkdir(exist_ok=True)
    # Seed minimum schema.
    import sqlite3 as _sq
    schema_sql = Path(ROOT_DIR, "niwa-app", "db", "schema.sql").read_text()
    _c = _sq.connect(str(db))
    _c.executescript(schema_sql)
    _c.commit()
    _c.close()

    projects_root = tmp_path / "projects"
    projects_root.mkdir()

    monkeypatch.setenv("NIWA_HOME", str(niwa_home))
    monkeypatch.setenv("NIWA_DB_PATH", str(db))
    monkeypatch.setenv("NIWA_PROJECTS_ROOT", str(projects_root))

    # Fresh module load so constants re-evaluate env.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "task_executor", os.path.join(BIN_DIR, "task-executor.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {"mod": mod, "root": projects_root, "db": str(db)}


def _seed_project(db_path, pid, directory):
    import sqlite3 as _sq
    c = _sq.connect(db_path)
    now = "2026-04-17T12:00:00Z"
    c.execute(
        "INSERT INTO projects (id, slug, name, area, directory, created_at, updated_at) "
        "VALUES (?, ?, ?, 'proyecto', ?, ?, ?)",
        (pid, pid[:8], f"test-{pid[:8]}", directory, now, now),
    )
    c.commit()
    c.close()


def test_resolve_project_dir_auto_heals_under_root(executor):
    mod = executor["mod"]
    pid = str(uuid.uuid4())
    missing_dir = executor["root"] / "heal-me"
    assert not missing_dir.exists()
    _seed_project(executor["db"], pid, str(missing_dir))

    result = mod._resolve_project_dir(pid)
    assert result is not None
    assert result == missing_dir.resolve()
    assert missing_dir.is_dir()


def test_resolve_project_dir_refuses_outside_root(executor, tmp_path):
    """A project declaring a directory OUTSIDE the managed root is
    left untouched. Prevents the executor from silently creating
    arbitrary filesystem locations if a user (or a bug) sets a weird
    path."""
    mod = executor["mod"]
    pid = str(uuid.uuid4())
    outside_dir = tmp_path / "outside" / "root" / "dangerous"
    _seed_project(executor["db"], pid, str(outside_dir))

    result = mod._resolve_project_dir(pid)
    assert result is None
    assert not outside_dir.exists()


def test_resolve_project_dir_returns_existing_dir(executor):
    """Happy path: the directory already exists — return it without
    touching the filesystem."""
    mod = executor["mod"]
    pid = str(uuid.uuid4())
    existing = executor["root"] / "already-there"
    existing.mkdir()
    (existing / "sentinel").write_text("touched")
    _seed_project(executor["db"], pid, str(existing))

    result = mod._resolve_project_dir(pid)
    assert result == existing
    assert (existing / "sentinel").read_text() == "touched"
