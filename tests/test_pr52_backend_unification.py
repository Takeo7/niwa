"""Tests for PR-52 — backend contract unification:

  - POST /api/projects
      · auto-generates slug + directory if omitted (already covered
        by PR-51, re-asserted here as regression guard)
      · links task_id to the new project in the same transaction
      · slug dedup adds a short suffix (no UNIQUE conflict)
  - fetch_tasks / get_task expose ``project_slug`` (new column)
  - MCP _project_create delegates to the HTTP endpoint (mock urlopen)
  - MCP _deploy_web delegates to the HTTP endpoint
  - _auto_project_finalize orphan cleanup: if dir is empty, drop the
    projects row + detach tasks.project_id.

Run: pytest tests/test_pr52_backend_unification.py -v
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
MCP_DIR = os.path.join(ROOT_DIR, "servers", "tasks-mcp")
for p in (BACKEND_DIR, BIN_DIR, MCP_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _install_mcp_stub():
    """The real ``mcp`` package is only present in the MCP container.
    Tests that import ``servers/tasks-mcp/server.py`` need a stub so
    the top-level ``from mcp.server import Server`` doesn't crash.

    We inject a minimal shim that exposes the names server.py reads at
    import time. No behavioural stubs — tests call ``_project_create``
    / ``_deploy_web`` directly, not through the MCP dispatch layer.
    """
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

    server_mod.Server = _Server
    stdio_mod.stdio_server = lambda: None
    # ``Tool``, ``TextContent``, etc. — the module iterates over Tool
    # instances reading ``.name``, so we need a dataclass-ish shim
    # that stores whatever kwargs got passed.
    class _Stub:
        def __init__(self, *a, **kw):
            for k, v in kw.items():
                setattr(self, k, v)
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
    with urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read() or b"{}")


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


# ── HTTP endpoint tests ───────────────────────────────────────────────


def test_post_projects_links_task_id(app_server):
    """The new optional ``task_id`` in POST /api/projects attaches the
    task to the newly-created project in the same transaction."""
    import sqlite3
    task_id = str(uuid.uuid4())
    now = "2026-04-17T12:00:00Z"
    with sqlite3.connect(app_server["db"]) as c:
        c.execute(
            "INSERT INTO tasks (id, title, status, priority, area, created_at, updated_at) "
            "VALUES (?, 'orphan task', 'pendiente', 'media', 'proyecto', ?, ?)",
            (task_id, now, now),
        )
        c.commit()

    status, out = _req(
        app_server["base"], "/api/projects", method="POST",
        body={"name": "With Link", "task_id": task_id},
    )
    assert status == 201, out
    assert out["linked_task_id"] == task_id

    with sqlite3.connect(app_server["db"]) as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT project_id FROM tasks WHERE id=?", (task_id,)).fetchone()
    assert row["project_id"] == out["id"]


def test_post_projects_task_id_without_match_is_noop(app_server):
    """Passing a non-existent task_id must not blow up — the UPDATE
    is gated by ``WHERE id=? AND project_id IS NULL`` so it just
    affects zero rows."""
    status, out = _req(
        app_server["base"], "/api/projects", method="POST",
        body={"name": "Ghost Task", "task_id": "does-not-exist"},
    )
    assert status == 201, out
    # The HTTP shape still reports what we tried to link — the UI can
    # decide whether to complain.
    assert out["linked_task_id"] == "does-not-exist"


def test_post_projects_slug_dedup(app_server):
    """Second project with the same name → slug gets a hex suffix, not
    a 409 UNIQUE error."""
    status, first = _req(
        app_server["base"], "/api/projects", method="POST",
        body={"name": "Duplicate Name"},
    )
    assert status == 201
    assert first["slug"] == "duplicate-name"

    status, second = _req(
        app_server["base"], "/api/projects", method="POST",
        body={"name": "Duplicate Name"},
    )
    assert status == 201
    assert second["slug"].startswith("duplicate-name-")
    assert second["slug"] != first["slug"]


def test_get_task_exposes_project_slug(app_server):
    """PR-52: ``GET /api/tasks/:id`` now returns ``project_slug`` so the
    UI can navigate from the task to its project without an extra
    round-trip."""
    import sqlite3
    task_id = str(uuid.uuid4())
    proj_id = str(uuid.uuid4())
    now = "2026-04-17T12:00:00Z"
    with sqlite3.connect(app_server["db"]) as c:
        c.execute(
            "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
            "VALUES (?, 'my-proj', 'My Proj', 'proyecto', ?, ?)",
            (proj_id, now, now),
        )
        c.execute(
            "INSERT INTO tasks (id, title, project_id, status, priority, area, "
            "created_at, updated_at) VALUES (?, 'task-with-proj', ?, 'pendiente', "
            "'media', 'proyecto', ?, ?)",
            (task_id, proj_id, now, now),
        )
        c.commit()

    status, out = _req(app_server["base"], f"/api/tasks/{task_id}")
    assert status == 200
    assert out["project_slug"] == "my-proj"
    assert out["project_name"] == "My Proj"


def test_fetch_tasks_exposes_project_slug(app_server):
    import sqlite3
    task_id = str(uuid.uuid4())
    proj_id = str(uuid.uuid4())
    now = "2026-04-17T12:00:00Z"
    with sqlite3.connect(app_server["db"]) as c:
        c.execute(
            "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
            "VALUES (?, 'my-proj2', 'My Proj 2', 'proyecto', ?, ?)",
            (proj_id, now, now),
        )
        # ``source`` must be set to something other than 'chat' — the
        # list endpoint filters ``WHERE t.source != 'chat'`` and NULL
        # fails that predicate under SQLite 3-valued logic.
        c.execute(
            "INSERT INTO tasks (id, title, project_id, status, priority, area, "
            "source, created_at, updated_at) VALUES (?, 'list-task', ?, "
            "'pendiente', 'media', 'proyecto', 'user', ?, ?)",
            (task_id, proj_id, now, now),
        )
        c.commit()

    status, out = _req(app_server["base"], "/api/tasks")
    assert status == 200
    row = next((t for t in out if t["id"] == task_id), None)
    assert row is not None
    assert row["project_slug"] == "my-proj2"


# ── MCP delegation tests (no real HTTP — we monkeypatch _app_request) ─


def test_mcp_project_create_delegates_to_http(monkeypatch):
    """The MCP tool no longer INSERTs directly. It posts to the app
    HTTP endpoint. We stub ``_app_request`` to verify the payload and
    short-circuit the DB readback."""
    # Stash/restore server module so monkeypatch works cleanly.
    for k in ("server",):
        if k in sys.modules:
            del sys.modules[k]
    sys.path.insert(0, MCP_DIR)
    import server

    calls: list[tuple[str, str, dict]] = []

    def _fake_request(path, method="POST", body=None):
        calls.append((path, method, body or {}))
        return 201, {"id": "p-abc", "slug": "test-proj",
                     "directory": "/tmp/test-proj", "linked_task_id": None}

    monkeypatch.setattr(server, "_app_request", _fake_request)

    # The tool reads back the row after the HTTP call — mock the DB
    # path via NIWA_DB_PATH. An in-memory table keeps this hermetic.
    import sqlite3
    import tempfile as _tmp
    fd, db_path = _tmp.mkstemp(suffix=".db")
    os.close(fd)
    try:
        c = sqlite3.connect(db_path)
        c.execute(
            "CREATE TABLE projects (id TEXT PRIMARY KEY, slug TEXT, "
            "name TEXT, area TEXT, description TEXT, active INTEGER, "
            "created_at TEXT, updated_at TEXT, directory TEXT, url TEXT)"
        )
        c.execute(
            "INSERT INTO projects (id, slug, name, area, active, created_at, "
            "updated_at) VALUES ('p-abc', 'test-proj', 'Test Proj', 'proyecto', "
            "1, '2026-04-17', '2026-04-17')"
        )
        c.commit()
        c.close()

        monkeypatch.setenv("NIWA_DB_PATH", db_path)
        # server.DB_PATH is captured at import time; re-point it so
        # _ro_conn() sees our fresh sqlite.
        monkeypatch.setattr(server, "DB_PATH", db_path)
        result = server._project_create({"name": "Test Proj", "task_id": "t-1"})
        assert result["id"] == "p-abc"
        assert result["slug"] == "test-proj"

        # The HTTP call was made with the right payload.
        assert len(calls) == 1
        path, method, body = calls[0]
        assert path == "/api/projects"
        assert method == "POST"
        assert body["name"] == "Test Proj"
        assert body["task_id"] == "t-1"
    finally:
        os.unlink(db_path)


def test_mcp_project_create_propagates_http_error(monkeypatch):
    import server
    monkeypatch.setattr(
        server, "_app_request",
        lambda path, method="POST", body=None: (400, {"error": "name required"}),
    )
    with pytest.raises(ValueError) as exc:
        server._project_create({"name": "x"})
    assert "project_create failed" in str(exc.value)


def test_mcp_deploy_web_delegates_to_http(monkeypatch):
    import server

    calls: list = []

    def _fake(path, method="POST", body=None):
        calls.append((path, method, body or {}))
        return 200, {"ok": True, "url": "https://x.example.com/",
                     "slug": "x", "directory": "/p/x", "status": "active"}

    monkeypatch.setattr(server, "_app_request", _fake)
    result = server._deploy_web({"project_id": "p-abc"})
    assert result["url"] == "https://x.example.com/"
    assert result["status"] == "deployed"
    assert calls == [("/api/projects/p-abc/deploy", "POST", {})]


def test_mcp_deploy_web_propagates_error(monkeypatch):
    import server
    monkeypatch.setattr(
        server, "_app_request",
        lambda path, method="POST", body=None: (404, {"error": "not_found"}),
    )
    with pytest.raises(ValueError) as exc:
        server._deploy_web({"project_id": "ghost"})
    assert "deploy_web failed" in str(exc.value)


def test_app_request_wraps_url_errors(monkeypatch):
    """When the app is unreachable (container down, network fail,
    DNS broken inside the MCP container), ``_app_request`` must NOT
    leak the raw ``<urlopen error [Errno 111] ...>`` string. Wrap it
    into a structured error so the MCP caller can recognise the case.
    """
    import server
    import urllib.error as _ue

    def _fail(*a, **kw):
        raise _ue.URLError("[Errno 111] Connection refused")

    # The function imports ``urllib.request`` lazily each call, so
    # patching the module-level ``urlopen`` is the reliable hook.
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", _fail)
    status, body = server._app_request("/api/projects", method="POST", body={})
    assert status == 0
    assert body["error"] == "app_unreachable"
    assert "Connection refused" in body["detail"]


# ── Orphan cleanup test (executor-side) ───────────────────────────────


@pytest.fixture
def executor(tmp_path, monkeypatch):
    niwa_home = tmp_path / "niwa-home"
    (niwa_home / "secrets").mkdir(parents=True)
    db_path = niwa_home / "data" / "niwa.sqlite3"
    db_path.parent.mkdir(exist_ok=True)
    (niwa_home / "secrets" / "mcp.env").write_text(
        f"NIWA_DB_PATH={db_path}\n"
    )
    monkeypatch.setenv("NIWA_HOME", str(niwa_home))
    monkeypatch.setenv("NIWA_DB_PATH", str(db_path))

    import sqlite3
    schema_sql = Path(ROOT_DIR, "niwa-app", "db", "schema.sql").read_text()
    _c = sqlite3.connect(str(db_path))
    _c.executescript(schema_sql)
    _c.commit()
    _c.close()

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "task_executor_pr52", os.path.join(BIN_DIR, "task-executor.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {"mod": mod, "db": str(db_path)}


def test_finalize_drops_phantom_project_when_dir_empty(executor, tmp_path):
    """Claude called project_create MCP (inserted a projects row) but
    then wrote no files → finalize must delete the phantom row AND
    detach any tasks that already got linked to it.
    """
    import sqlite3
    mod = executor["mod"]
    proj_id = "p-phantom"
    task_id = "t-linked"
    empty_dir = tmp_path / "nothing-here"
    empty_dir.mkdir()  # exists but no files inside

    with sqlite3.connect(executor["db"]) as c:
        c.execute(
            "INSERT INTO projects (id, slug, name, area, active, created_at, "
            "updated_at, directory) VALUES (?, 'phantom', 'Phantom', 'proyecto',"
            " 1, '2026-04-17', '2026-04-17', ?)",
            (proj_id, str(empty_dir)),
        )
        c.execute(
            "INSERT INTO tasks (id, title, project_id, status, priority, area, "
            "created_at, updated_at) VALUES (?, 'linked', ?, 'pendiente', "
            "'media', 'proyecto', '2026-04-17', '2026-04-17')",
            (task_id, proj_id),
        )
        c.commit()

    ctx = {"slug": "phantom", "directory": str(empty_dir), "name": "Phantom"}
    mod._auto_project_finalize(ctx, task_id)

    with sqlite3.connect(executor["db"]) as c:
        c.row_factory = sqlite3.Row
        proj = c.execute("SELECT * FROM projects WHERE id=?", (proj_id,)).fetchone()
        task = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    assert proj is None, "phantom project was not cleaned up"
    assert task["project_id"] is None, "linked task was not detached"
    assert not empty_dir.exists()


def test_finalize_keeps_project_when_dir_has_files(executor, tmp_path):
    """Happy path: files exist → do NOT touch the projects row, just
    re-associate the task. Guards against a regression where orphan
    cleanup nukes real projects."""
    import sqlite3
    mod = executor["mod"]
    proj_id = "p-real"
    task_id = "t-real"
    real_dir = tmp_path / "with-files"
    real_dir.mkdir()
    (real_dir / "index.html").write_text("<html></html>")

    with sqlite3.connect(executor["db"]) as c:
        c.execute(
            "INSERT INTO projects (id, slug, name, area, active, created_at, "
            "updated_at, directory) VALUES (?, 'real', 'Real', 'proyecto', "
            "1, '2026-04-17', '2026-04-17', ?)",
            (proj_id, str(real_dir)),
        )
        c.execute(
            "INSERT INTO tasks (id, title, status, priority, area, "
            "created_at, updated_at) VALUES (?, 'attach-me', 'pendiente', "
            "'media', 'proyecto', '2026-04-17', '2026-04-17')",
            (task_id,),
        )
        c.commit()

    ctx = {"slug": "real", "directory": str(real_dir), "name": "Real"}
    mod._auto_project_finalize(ctx, task_id)

    with sqlite3.connect(executor["db"]) as c:
        c.row_factory = sqlite3.Row
        proj = c.execute("SELECT * FROM projects WHERE id=?", (proj_id,)).fetchone()
        task = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    assert proj is not None, "real project must not be deleted"
    assert task["project_id"] == proj_id, "task must end up linked"
    assert (real_dir / "index.html").exists()
