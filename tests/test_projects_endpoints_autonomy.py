"""Tests for PR-B3 — `autonomy_mode` exposed via PATCH/GET /api/projects.

Covers:
  * PATCH accepts ``autonomy_mode='dangerous'`` and persists it.
  * PATCH rejects invalid values with 400.
  * GET /api/projects and /api/projects/<slug> surface the field.
"""
import json
import os
import sqlite3 as _sq
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
BIN_DIR = os.path.join(ROOT_DIR, "bin")
MCP_DIR = os.path.join(ROOT_DIR, "servers", "tasks-mcp")
for p in (BACKEND_DIR, BIN_DIR, MCP_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _install_mcp_stub():
    import types
    if "mcp" in sys.modules:
        return
    mcp_mod = types.ModuleType("mcp")
    server_mod = types.ModuleType("mcp.server")
    stdio_mod = types.ModuleType("mcp.server.stdio")
    types_mod = types.ModuleType("mcp.types")

    class _Server:
        def __init__(self, *a, **kw): pass
        def list_tools(self, *a, **kw): return lambda fn: fn
        def call_tool(self, *a, **kw): return lambda fn: fn
        def run(self, *a, **kw): pass

    class _Stub:
        def __init__(self, *a, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    server_mod.Server = _Server
    stdio_mod.stdio_server = lambda: None
    for name in ("Tool", "TextContent", "ImageContent", "EmbeddedResource"):
        setattr(types_mod, name, type(name, (_Stub,), {}))
    sys.modules["mcp"] = mcp_mod
    sys.modules["mcp.server"] = server_mod
    sys.modules["mcp.server.stdio"] = stdio_mod
    sys.modules["mcp.types"] = types_mod


_install_mcp_stub()


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
            return resp.status, json.loads(raw) if raw else {}
    except HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return e.code, {"raw": raw.decode("utf-8", errors="ignore")}


@pytest.fixture
def app_server(tmp_path, monkeypatch):
    db_path = str(tmp_path / "niwa.sqlite3")
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    monkeypatch.setenv("NIWA_DB_PATH", db_path)
    monkeypatch.setenv("NIWA_APP_AUTH_REQUIRED", "0")
    monkeypatch.setenv("NIWA_APP_HOST", "127.0.0.1")
    monkeypatch.setenv("NIWA_PROJECTS_ROOT", str(projects_root))

    schema_sql = Path(ROOT_DIR, "niwa-app", "db", "schema.sql").read_text()
    _c = _sq.connect(db_path)
    _c.executescript(schema_sql)
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
    yield {"base": base, "app": app, "db": db_path}
    srv.shutdown()
    srv.server_close()


def _insert_project(db, slug="proj-auto"):
    proj_id = str(uuid.uuid4())
    now = "2026-04-19T12:00:00Z"
    with _sq.connect(db) as c:
        c.execute(
            "INSERT INTO projects (id, slug, name, area, active, "
            "created_at, updated_at) VALUES (?, ?, 'P', 'proyecto', 1, "
            "?, ?)",
            (proj_id, slug, now, now),
        )
        c.commit()
    return proj_id


def test_patch_sets_autonomy_mode_to_dangerous(app_server):
    slug = "proj-auto-1"
    _insert_project(app_server["db"], slug=slug)

    status, body = _req(
        app_server["base"], f"/api/projects/{slug}",
        method="PATCH", body={"autonomy_mode": "dangerous"},
    )
    assert status == 200, body

    with _sq.connect(app_server["db"]) as c:
        c.row_factory = _sq.Row
        row = c.execute(
            "SELECT autonomy_mode FROM projects WHERE slug=?", (slug,),
        ).fetchone()
    assert row["autonomy_mode"] == "dangerous"


def test_patch_accepts_returning_to_normal(app_server):
    slug = "proj-auto-2"
    _insert_project(app_server["db"], slug=slug)

    # First PATCH must actually flip to 'dangerous'. Asserting this
    # is what makes "return to normal" meaningful; without it the
    # test would also pass when the first PATCH is a silent no-op.
    status, _ = _req(
        app_server["base"], f"/api/projects/{slug}",
        method="PATCH", body={"autonomy_mode": "dangerous"},
    )
    assert status == 200
    with _sq.connect(app_server["db"]) as c:
        c.row_factory = _sq.Row
        row = c.execute(
            "SELECT autonomy_mode FROM projects WHERE slug=?", (slug,),
        ).fetchone()
    assert row["autonomy_mode"] == "dangerous"

    status, _ = _req(
        app_server["base"], f"/api/projects/{slug}",
        method="PATCH", body={"autonomy_mode": "normal"},
    )
    assert status == 200
    with _sq.connect(app_server["db"]) as c:
        c.row_factory = _sq.Row
        row = c.execute(
            "SELECT autonomy_mode FROM projects WHERE slug=?", (slug,),
        ).fetchone()
    assert row["autonomy_mode"] == "normal"


def test_patch_rejects_invalid_autonomy_mode(app_server):
    slug = "proj-auto-3"
    _insert_project(app_server["db"], slug=slug)
    status, body = _req(
        app_server["base"], f"/api/projects/{slug}",
        method="PATCH", body={"autonomy_mode": "yolo"},
    )
    assert status == 400, body
    assert body.get("error") == "invalid_autonomy_mode"


def test_get_project_surfaces_autonomy_mode(app_server):
    slug = "proj-auto-4"
    _insert_project(app_server["db"], slug=slug)
    status, body = _req(app_server["base"], f"/api/projects/{slug}")
    assert status == 200
    assert body.get("autonomy_mode") == "normal"

    _req(app_server["base"], f"/api/projects/{slug}",
         method="PATCH", body={"autonomy_mode": "dangerous"})
    status, body = _req(app_server["base"], f"/api/projects/{slug}")
    assert body.get("autonomy_mode") == "dangerous"
