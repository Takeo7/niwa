"""Tests for PR-57: retry with ``relation_type='retry'`` auditable,
idempotent endpoint, graceful degradation, managed-dir ensure.

GPT review ajustes aplicados:
  - retry marker en ``tasks.retry_from_run_id`` (no en el endpoint).
  - el executor LEE el marker y crea el run con relation_type='retry'.
  - reuso de ``routing_decision_id`` + ``backend_profile_id`` del
    previous run (retry, no reroute).
  - idempotente: doble ``POST /retry`` no duplica; devuelve
    ``already_queued=true``.
  - graceful degrade: si el marker apunta a un run inexistente, el
    executor limpia el marker y va por routing normal sin bloquear.
  - ``_ensure_managed_project_dir`` solo ``chmod 0o777`` cuando crea
    (no en cada deploy).

Run: pytest tests/test_pr57_retry_audit_and_dir.py -v
"""
import json
import os
import sqlite3
import stat
import sys
import tempfile
import threading
import time
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
BIN_DIR = os.path.join(ROOT_DIR, "bin")
for p in (BACKEND_DIR, BIN_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _free_port():
    import socket as _s
    with _s.socket() as s:
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
    deployments_sql = Path(
        ROOT_DIR, "niwa-app", "db", "migrations", "003_deployments.sql"
    ).read_text()
    c = sqlite3.connect(db_path)
    c.executescript(schema_sql)
    c.executescript(deployments_sql)
    c.commit()
    c.close()

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


def _seed_task_with_run(db: str, *, run_status="failed", run_outcome="failure"):
    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    bp_id = str(uuid.uuid4())
    rd_id = str(uuid.uuid4())
    now = "2026-04-17T12:00:00Z"
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO backend_profiles (id, slug, display_name, "
            "backend_kind, runtime_kind, default_model, enabled, priority, "
            "created_at, updated_at) VALUES (?, 'test-bp', 'Test', "
            "'claude_code', 'cli', 'claude-sonnet-4-6', 1, 10, ?, ?)",
            (bp_id, now, now),
        )
        c.execute(
            "INSERT INTO tasks (id, title, status, priority, area, source, "
            "current_run_id, completed_at, created_at, updated_at) VALUES "
            "(?, 'retry-me', 'hecha', 'media', 'proyecto', 'user', ?, ?, ?, ?)",
            (task_id, run_id, now, now, now),
        )
        c.execute(
            "INSERT INTO routing_decisions (id, task_id, decision_index, "
            "selected_profile_id, created_at) VALUES (?, ?, 0, ?, ?)",
            (rd_id, task_id, bp_id, now),
        )
        c.execute(
            "INSERT INTO backend_runs (id, task_id, routing_decision_id, "
            "backend_profile_id, backend_kind, runtime_kind, status, outcome, "
            "created_at, updated_at, finished_at) VALUES (?, ?, ?, ?, "
            "'claude_code', 'cli', ?, ?, ?, ?, ?)",
            (run_id, task_id, rd_id, bp_id, run_status, run_outcome,
             now, now, now),
        )
        c.commit()
    return {"task_id": task_id, "run_id": run_id, "bp_id": bp_id, "rd_id": rd_id}


# ── Retry endpoint ───────────────────────────────────────────────────


def test_retry_sets_marker_and_flips_status(app_server):
    s = _seed_task_with_run(app_server["db"])
    status, out = _req(
        app_server["base"], f"/api/tasks/{s['task_id']}/retry",
        method="POST", body={},
    )
    assert status == 200, out
    assert out["status"] == "pendiente"
    assert out["retry_from_run_id"] == s["run_id"]
    with sqlite3.connect(app_server["db"]) as c:
        c.row_factory = sqlite3.Row
        t = c.execute(
            "SELECT status, completed_at, retry_from_run_id FROM tasks "
            "WHERE id=?", (s["task_id"],),
        ).fetchone()
    assert t["status"] == "pendiente"
    assert t["completed_at"] is None
    assert t["retry_from_run_id"] == s["run_id"]


def test_retry_is_idempotent_when_already_queued(app_server):
    """Second POST /retry while a retry is already in-flight must not
    re-mark or create duplicates — it returns 200 with
    ``already_queued=True`` (GPT review: prefer idempotent over 409)."""
    s = _seed_task_with_run(app_server["db"])
    _req(app_server["base"], f"/api/tasks/{s['task_id']}/retry",
         method="POST", body={})
    status, out = _req(
        app_server["base"], f"/api/tasks/{s['task_id']}/retry",
        method="POST", body={},
    )
    assert status == 200
    assert out["already_queued"] is True
    assert out["retry_from_run_id"] == s["run_id"]


def test_retry_without_prior_run_leaves_marker_null(app_server):
    """A task with no finished runs can still be 'reintentada' — in
    practice it just re-queues. ``retry_from_run_id`` stays NULL and
    the executor takes the normal routing path."""
    task_id = str(uuid.uuid4())
    now = "2026-04-17T12:00:00Z"
    with sqlite3.connect(app_server["db"]) as c:
        c.execute(
            "INSERT INTO tasks (id, title, status, priority, area, source, "
            "created_at, updated_at) VALUES (?, 'lonely', 'hecha', 'media', "
            "'proyecto', 'user', ?, ?)",
            (task_id, now, now),
        )
        c.commit()
    status, out = _req(
        app_server["base"], f"/api/tasks/{task_id}/retry",
        method="POST", body={},
    )
    assert status == 200
    assert out["retry_from_run_id"] is None
    with sqlite3.connect(app_server["db"]) as c:
        c.row_factory = sqlite3.Row
        t = c.execute(
            "SELECT status, retry_from_run_id FROM tasks WHERE id=?",
            (task_id,),
        ).fetchone()
    assert t["status"] == "pendiente"
    assert t["retry_from_run_id"] is None


def test_retry_404_when_task_missing(app_server):
    status, out = _req(
        app_server["base"], "/api/tasks/ghost/retry",
        method="POST", body={},
    )
    assert status == 404


# ── Managed project dir helper ───────────────────────────────────────


def test_ensure_managed_dir_creates_with_777_when_new(app_server, tmp_path):
    import app as app_mod
    target = app_server["root"] / "new-project"
    assert not target.exists()
    assert app_mod._ensure_managed_project_dir(str(target)) is True
    assert target.is_dir()
    # mode masking: the sticky/type bits aren't relevant — check the
    # low 9 bits (owner+group+other rwx).
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o777, f"expected 0o777 after create, got {oct(mode)}"


def test_ensure_managed_dir_does_not_touch_perms_when_already_exists(app_server):
    import app as app_mod
    target = app_server["root"] / "preexisting"
    target.mkdir()
    os.chmod(target, 0o755)
    assert app_mod._ensure_managed_project_dir(str(target)) is True
    mode = stat.S_IMODE(target.stat().st_mode)
    # Key assertion: permissions must NOT have been widened.
    assert mode == 0o755, (
        "helper should only chmod on CREATE, not on every call"
    )


def test_ensure_managed_dir_refuses_paths_outside_root(app_server, tmp_path):
    import app as app_mod
    outside = tmp_path / "not-managed" / "somewhere"
    assert app_mod._ensure_managed_project_dir(str(outside)) is False
    assert not outside.exists()


def test_ensure_managed_dir_refuses_traversal(app_server, tmp_path):
    """Path traversal via ``..`` must resolve before the root check."""
    import app as app_mod
    evil = f"{app_server['root']}/safe/../../escape"
    assert app_mod._ensure_managed_project_dir(evil) is False


# ── Executor retry path (unit, without full executor load) ───────────


@pytest.fixture
def executor_env(tmp_path, monkeypatch):
    niwa_home = tmp_path / "niwa-home"
    (niwa_home / "secrets").mkdir(parents=True)
    db_path = niwa_home / "data" / "niwa.sqlite3"
    db_path.parent.mkdir(exist_ok=True)
    (niwa_home / "secrets" / "mcp.env").write_text(
        f"NIWA_DB_PATH={db_path}\n"
    )
    monkeypatch.setenv("NIWA_HOME", str(niwa_home))
    monkeypatch.setenv("NIWA_DB_PATH", str(db_path))

    schema_sql = Path(ROOT_DIR, "niwa-app", "db", "schema.sql").read_text()
    c = sqlite3.connect(str(db_path))
    c.executescript(schema_sql)
    c.commit()
    c.close()

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_task_executor_pr57", os.path.join(BIN_DIR, "task-executor.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {"mod": mod, "db": str(db_path)}


def _seed_full_chain(db: str):
    """Insert project + task + backend_profile + routing_decision + run
    so ``_build_retry_decision`` has real data to read."""
    now = "2026-04-17T12:00:00Z"
    task_id = str(uuid.uuid4())
    bp_id = str(uuid.uuid4())
    rd_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO backend_profiles (id, slug, display_name, "
            "backend_kind, runtime_kind, default_model, enabled, priority, "
            "created_at, updated_at) VALUES (?, 'bp', 'BP', 'claude_code', "
            "'cli', 'claude-sonnet-4-6', 1, 10, ?, ?)",
            (bp_id, now, now),
        )
        c.execute(
            "INSERT INTO tasks (id, title, status, priority, area, source, "
            "created_at, updated_at) VALUES (?, 't', 'pendiente', 'media', "
            "'proyecto', 'user', ?, ?)",
            (task_id, now, now),
        )
        c.execute(
            "INSERT INTO routing_decisions (id, task_id, decision_index, "
            "selected_profile_id, created_at) VALUES (?, ?, 0, ?, ?)",
            (rd_id, task_id, bp_id, now),
        )
        c.execute(
            "INSERT INTO backend_runs (id, task_id, routing_decision_id, "
            "backend_profile_id, backend_kind, runtime_kind, status, outcome, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, 'claude_code', "
            "'cli', 'failed', 'failure', ?, ?)",
            (run_id, task_id, rd_id, bp_id, now, now),
        )
        c.commit()
    return {"task_id": task_id, "bp_id": bp_id, "rd_id": rd_id, "run_id": run_id}


def test_build_retry_decision_returns_previous_backend_and_rd(executor_env):
    mod = executor_env["mod"]
    s = _seed_full_chain(executor_env["db"])
    with sqlite3.connect(executor_env["db"]) as c:
        c.row_factory = sqlite3.Row
        dec = mod._build_retry_decision(s["task_id"], s["run_id"], c)
    assert dec is not None
    assert dec["selected_backend_profile_id"] == s["bp_id"]
    assert dec["routing_decision_id"] == s["rd_id"]
    assert dec["fallback_chain"] == []
    assert dec["relation_type_override"] == "retry"
    assert dec["previous_run_id_override"] == s["run_id"]


def test_build_retry_decision_none_when_run_missing(executor_env):
    mod = executor_env["mod"]
    with sqlite3.connect(executor_env["db"]) as c:
        c.row_factory = sqlite3.Row
        dec = mod._build_retry_decision("t-x", "nonexistent-run", c)
    assert dec is None


def test_build_retry_decision_none_when_profile_deleted(executor_env):
    """Graceful degrade: if the profile referenced by the previous
    run is gone, return None so the executor falls back to routing
    instead of crashing on FK / missing data."""
    mod = executor_env["mod"]
    s = _seed_full_chain(executor_env["db"])
    # Hard-delete the backend profile the run points at.
    with sqlite3.connect(executor_env["db"]) as c:
        c.execute("DELETE FROM backend_profiles WHERE id=?", (s["bp_id"],))
        c.commit()
    with sqlite3.connect(executor_env["db"]) as c:
        c.row_factory = sqlite3.Row
        dec = mod._build_retry_decision(s["task_id"], s["run_id"], c)
    assert dec is None
