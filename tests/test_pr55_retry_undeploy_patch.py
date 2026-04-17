"""Tests for PR-55 — retry, undeploy delegation, PATCH autogen
directory, parent_task_id.

Bundled together because they all live in the same contract.

Run: pytest tests/test_pr55_retry_undeploy_patch.py -v
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
    yield {"base": base, "app": app, "db": db_path, "root": projects_root}
    srv.shutdown()
    srv.server_close()


# ── Retry endpoint ───────────────────────────────────────────────────


def test_retry_flips_status_to_pendiente_and_clears_completed_at(app_server):
    """POST /api/tasks/:id/retry must put a ``hecha`` task back in
    ``pendiente`` with ``completed_at=NULL`` so the executor picks it
    up again and the dashboard does not double-count it."""
    import sqlite3
    task_id = str(uuid.uuid4())
    now = "2026-04-17T12:00:00Z"
    with sqlite3.connect(app_server["db"]) as c:
        c.execute(
            "INSERT INTO tasks (id, title, status, priority, area, source, "
            "completed_at, created_at, updated_at) VALUES (?, 'done', "
            "'hecha', 'media', 'proyecto', 'user', ?, ?, ?)",
            (task_id, now, now, now),
        )
        c.commit()
    status, out = _req(
        app_server["base"], f"/api/tasks/{task_id}/retry",
        method="POST", body={},
    )
    assert status == 200, out
    assert out["status"] == "pendiente"
    with sqlite3.connect(app_server["db"]) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT status, completed_at FROM tasks WHERE id=?", (task_id,),
        ).fetchone()
    assert row["status"] == "pendiente"
    assert row["completed_at"] is None


def test_retry_missing_task_returns_404(app_server):
    status, out = _req(
        app_server["base"], "/api/tasks/ghost/retry", method="POST", body={},
    )
    assert status == 404


# ── PATCH autogen directory on empty ─────────────────────────────────


def test_patch_project_autogenerates_directory_when_empty(app_server):
    """PR-55: editing a project and clearing the directory field must
    autogenerate ``<projects_root>/<slug>`` instead of saving an
    empty string (the old behaviour silently dropped the edit)."""
    import sqlite3
    proj_id = str(uuid.uuid4())
    now = "2026-04-17T12:00:00Z"
    with sqlite3.connect(app_server["db"]) as c:
        c.execute(
            "INSERT INTO projects (id, slug, name, area, active, created_at, "
            "updated_at, directory) VALUES (?, 'editme', 'Edit Me', "
            "'proyecto', 1, ?, ?, '')",
            (proj_id, now, now),
        )
        c.commit()
    # Sending empty directory should trigger autogen.
    status, _ = _req(
        app_server["base"], "/api/projects/editme",
        method="PATCH", body={"directory": ""},
    )
    assert status == 200
    with sqlite3.connect(app_server["db"]) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT directory FROM projects WHERE id=?", (proj_id,),
        ).fetchone()
    assert row["directory"] == str(app_server["root"] / "editme")


def test_patch_project_whitespace_directory_treated_as_empty(app_server):
    import sqlite3
    proj_id = str(uuid.uuid4())
    now = "2026-04-17T12:00:00Z"
    with sqlite3.connect(app_server["db"]) as c:
        c.execute(
            "INSERT INTO projects (id, slug, name, area, active, created_at, "
            "updated_at, directory) VALUES (?, 'ws', 'WS', 'proyecto', 1, "
            "?, ?, '')",
            (proj_id, now, now),
        )
        c.commit()
    status, _ = _req(
        app_server["base"], "/api/projects/ws",
        method="PATCH", body={"directory": "   "},
    )
    assert status == 200
    with sqlite3.connect(app_server["db"]) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT directory FROM projects WHERE id=?", (proj_id,),
        ).fetchone()
    assert row["directory"] == str(app_server["root"] / "ws")


def test_patch_project_explicit_directory_respected(app_server):
    """Regression guard: if the client sends a non-empty directory, we
    save it verbatim (no autogen). Prevents over-reach of the new
    empty-string rule."""
    import sqlite3
    proj_id = str(uuid.uuid4())
    now = "2026-04-17T12:00:00Z"
    with sqlite3.connect(app_server["db"]) as c:
        c.execute(
            "INSERT INTO projects (id, slug, name, area, active, created_at, "
            "updated_at, directory) VALUES (?, 'explicit', 'Explicit', "
            "'proyecto', 1, ?, ?, '')",
            (proj_id, now, now),
        )
        c.commit()
    status, _ = _req(
        app_server["base"], "/api/projects/explicit",
        method="PATCH", body={"directory": "/mnt/custom/path"},
    )
    assert status == 200
    with sqlite3.connect(app_server["db"]) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT directory FROM projects WHERE id=?", (proj_id,),
        ).fetchone()
    assert row["directory"] == "/mnt/custom/path"


# ── parent_task_id creates link ──────────────────────────────────────


def test_create_task_with_parent_task_id_persists_link(app_server):
    import sqlite3
    parent_id = str(uuid.uuid4())
    now = "2026-04-17T12:00:00Z"
    with sqlite3.connect(app_server["db"]) as c:
        c.execute(
            "INSERT INTO tasks (id, title, status, priority, area, source, "
            "created_at, updated_at) VALUES (?, 'parent', 'waiting_input', "
            "'media', 'proyecto', 'user', ?, ?)",
            (parent_id, now, now),
        )
        c.commit()

    status, out = _req(
        app_server["base"], "/api/tasks", method="POST",
        body={"title": "child follow-up", "parent_task_id": parent_id},
    )
    assert status == 201, out
    child_id = out["id"]
    with sqlite3.connect(app_server["db"]) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT parent_task_id FROM tasks WHERE id=?", (child_id,),
        ).fetchone()
    assert row["parent_task_id"] == parent_id


# ── MCP _undeploy_web delegation ─────────────────────────────────────


def test_mcp_undeploy_web_delegates_to_http(monkeypatch):
    """PR-55 fix: MCP ``_undeploy_web`` used to only flip the DB flag
    without reloading Caddy (split-brain). Now it delegates to the
    HTTP endpoint which runs ``hosting.undeploy_project()``.
    """
    import server

    calls: list = []

    def _fake(path, method="POST", body=None):
        calls.append((path, method, body or {}))
        return 200, {"ok": True}

    monkeypatch.setattr(server, "_app_request", _fake)
    result = server._undeploy_web({"project_id": "p-abc"})
    assert result == {"ok": True}
    assert calls == [("/api/projects/p-abc/undeploy", "POST", {})]


def test_mcp_undeploy_web_propagates_http_error(monkeypatch):
    import server
    monkeypatch.setattr(
        server, "_app_request",
        lambda path, method="POST", body=None: (404, {"error": "not_found"}),
    )
    with pytest.raises(ValueError) as exc:
        server._undeploy_web({"project_id": "ghost"})
    assert "undeploy_web failed" in str(exc.value)


# ── MCP project_create inputSchema exposes task_id ───────────────────


def test_mcp_project_create_schema_exposes_task_id():
    """Regression guard: the Tool descriptor must expose ``task_id`` so
    Claude (who reads it) knows it can link the task in one call.
    ``project_create`` lives in the legacy v0.1 tool list — that's the
    one MCP clients in core mode receive."""
    import server
    tools = getattr(server, "_LEGACY_TOOL_DEFS", [])
    pc = next(
        (t for t in tools if getattr(t, "name", None) == "project_create"),
        None,
    )
    assert pc is not None, "project_create tool missing from MCP defs"
    props = pc.inputSchema["properties"]
    assert "task_id" in props, "task_id not declared in project_create schema"
    assert "description" in props["task_id"]
