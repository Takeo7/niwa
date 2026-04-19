"""Tests for PR-C3 — migration 016 + product_healthcheck seed.

Covers:
  - Migration 016 adds ``routines.improvement_type`` and
    ``deployments.consecutive_failures``.
  - Fresh ``schema.sql`` accepts ``action='improve'`` and rejects
    unknown actions on the ``routines`` CHECK constraint.
  - HTTP layer validates ``action='improve'`` + ``improvement_type``:
    missing/invalid type → 400; valid combo → 2xx.
  - ``seed_builtin_routines`` registers ``product_healthcheck``.
  - ``check_deployments_health()`` strike logic: counts consecutive
    failures, creates exactly one fix task at strike==3, resets on
    success.

Run: pytest tests/test_routines_improve_check.py -v
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "niwa-app" / "backend"
DB_DIR = ROOT_DIR / "niwa-app" / "db"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─────────────────────── helpers ───────────────────────

def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript((DB_DIR / "schema.sql").read_text(encoding="utf-8"))


def _apply_migration(conn: sqlite3.Connection, filename: str) -> None:
    conn.executescript((DB_DIR / "migrations" / filename).read_text(encoding="utf-8"))


def _free_port() -> int:
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


# ─────────────────────── schema/migration tests ───────────────────────

def test_migration_016_adds_columns(tmp_path):
    """Applying 016 onto a pre-016 DB must add both new columns."""
    db = tmp_path / "t.db"
    c = sqlite3.connect(db)
    # Simulate a DB where schema.sql doesn't yet include the new columns:
    # use the real schema.sql but then verify that applying 016 is a no-op
    # on the already-present columns (idempotent) or adds them if missing.
    _apply_schema(c)
    _apply_migration(c, "016_routines_improve.sql")
    c.commit()

    routine_cols = {r[1] for r in c.execute("PRAGMA table_info(routines)").fetchall()}
    assert "improvement_type" in routine_cols

    dep_cols = {r[1] for r in c.execute("PRAGMA table_info(deployments)").fetchall()}
    assert "consecutive_failures" in dep_cols
    c.close()


def test_schema_sql_accepts_improve_action(tmp_path):
    """Fresh schema.sql must allow action='improve' in routines CHECK."""
    db = tmp_path / "t.db"
    c = sqlite3.connect(db)
    _apply_schema(c)
    c.execute(
        "INSERT INTO routines (id, name, enabled, schedule, tz, action, "
        "action_config, notify_channel, notify_config, "
        "consecutive_errors, created_at, updated_at) "
        "VALUES (?, 'T', 1, '*/10 * * * *', 'UTC', 'improve', '{}', 'none', "
        "'{}', 0, '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
        (str(uuid.uuid4()),),
    )
    c.commit()
    c.close()


def test_schema_sql_rejects_unknown_action(tmp_path):
    db = tmp_path / "t.db"
    c = sqlite3.connect(db)
    _apply_schema(c)
    with pytest.raises(sqlite3.IntegrityError):
        c.execute(
            "INSERT INTO routines (id, name, enabled, schedule, tz, action, "
            "action_config, notify_channel, notify_config, "
            "consecutive_errors, created_at, updated_at) "
            "VALUES (?, 'T', 1, '*/10 * * * *', 'UTC', 'foobar', '{}', 'none', "
            "'{}', 0, '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            (str(uuid.uuid4()),),
        )
    c.close()


# ─────────────────────── seed test ───────────────────────

def test_product_healthcheck_seed_registers(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    c = sqlite3.connect(db)
    _apply_schema(c)
    c.commit()
    c.close()

    monkeypatch.setenv("NIWA_DB_PATH", str(db))

    import importlib
    import scheduler  # noqa: F401
    importlib.reload(scheduler)

    def _conn():
        cc = sqlite3.connect(db)
        cc.row_factory = sqlite3.Row
        return cc

    scheduler.seed_builtin_routines(_conn)

    c = sqlite3.connect(db)
    row = c.execute(
        "SELECT id, enabled, schedule, action FROM routines WHERE id='product_healthcheck'"
    ).fetchone()
    c.close()
    assert row is not None, "product_healthcheck seed missing"
    assert row[1] == 1
    assert row[2] == "*/10 * * * *"
    assert row[3] == "script"


# ─────────────────────── strike-logic tests ───────────────────────

class _FlakyHandler(BaseHTTPRequestHandler):
    # Server-wide toggle populated by the test.
    status_code = 500

    def do_GET(self):
        self.send_response(self.status_code)
        self.end_headers()
        self.wfile.write(b"ok" if 200 <= self.status_code < 400 else b"bad")

    def log_message(self, format, *args):  # silence
        return


@pytest.fixture
def flaky_server():
    port = _free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), _FlakyHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield {"base": f"http://127.0.0.1:{port}", "set_status": lambda s: setattr(_FlakyHandler, "status_code", s)}
    srv.shutdown()
    srv.server_close()


def _seed_deployment(db_path: Path, url: str, project_id: str | None = None) -> str:
    pid = project_id or str(uuid.uuid4())
    dep_id = str(uuid.uuid4())
    c = sqlite3.connect(db_path)
    # Project row (tasks.project_id FK → projects.id via schema.sql).
    c.execute(
        "INSERT OR IGNORE INTO projects (id, slug, name, area, created_at, updated_at) "
        "VALUES (?, ?, 'P', 'proyecto', ?, ?)",
        (pid, f"proj-{pid[:6]}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    c.execute(
        "INSERT INTO deployments (id, project_id, slug, directory, url, status) "
        "VALUES (?, ?, ?, ?, ?, 'active')",
        (dep_id, pid, f"dep-{dep_id[:6]}", "/tmp/x", url),
    )
    c.commit()
    c.close()
    return dep_id


def _fresh_db(tmp_path: Path) -> Path:
    db = tmp_path / "t.db"
    c = sqlite3.connect(db)
    _apply_schema(c)
    c.commit()
    c.close()
    return db


def _conn_fn_for(db_path: Path):
    def _f():
        cc = sqlite3.connect(db_path)
        cc.row_factory = sqlite3.Row
        return cc
    return _f


def test_strikes_increment_and_create_task_at_three(tmp_path, flaky_server):
    db = _fresh_db(tmp_path)
    flaky_server["set_status"](500)
    url = f"{flaky_server['base']}/"
    _seed_deployment(db, url)

    import importlib
    import scheduler
    importlib.reload(scheduler)

    conn_fn = _conn_fn_for(db)

    for _ in range(3):
        scheduler.check_deployments_health(conn_fn)

    c = sqlite3.connect(db)
    cf = c.execute("SELECT consecutive_failures FROM deployments").fetchone()[0]
    n_tasks = c.execute(
        "SELECT COUNT(*) FROM tasks WHERE source='routine:product_healthcheck'"
    ).fetchone()[0]
    c.close()
    assert cf == 3
    assert n_tasks == 1, f"expected 1 fix task, got {n_tasks}"


def test_strikes_do_not_duplicate_task_on_further_failures(tmp_path, flaky_server):
    db = _fresh_db(tmp_path)
    flaky_server["set_status"](500)
    _seed_deployment(db, f"{flaky_server['base']}/")

    import importlib
    import scheduler
    importlib.reload(scheduler)
    conn_fn = _conn_fn_for(db)

    for _ in range(5):
        scheduler.check_deployments_health(conn_fn)

    c = sqlite3.connect(db)
    n_tasks = c.execute(
        "SELECT COUNT(*) FROM tasks WHERE source='routine:product_healthcheck'"
    ).fetchone()[0]
    c.close()
    assert n_tasks == 1, f"expected counter freeze after first fix task, got {n_tasks}"


def test_strikes_reset_on_success(tmp_path, flaky_server):
    db = _fresh_db(tmp_path)
    _seed_deployment(db, f"{flaky_server['base']}/")

    import importlib
    import scheduler
    importlib.reload(scheduler)
    conn_fn = _conn_fn_for(db)

    flaky_server["set_status"](500)
    scheduler.check_deployments_health(conn_fn)
    scheduler.check_deployments_health(conn_fn)
    flaky_server["set_status"](200)
    scheduler.check_deployments_health(conn_fn)

    c = sqlite3.connect(db)
    cf = c.execute("SELECT consecutive_failures FROM deployments").fetchone()[0]
    n_tasks = c.execute(
        "SELECT COUNT(*) FROM tasks WHERE source='routine:product_healthcheck'"
    ).fetchone()[0]
    c.close()
    assert cf == 0
    assert n_tasks == 0


# ─────────────────────── HTTP validation tests ───────────────────────

@pytest.fixture
def http_server(tmp_path):
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    port = _free_port()
    os.environ["NIWA_DB_PATH"] = db_path
    os.environ["NIWA_APP_PORT"] = str(port)
    os.environ["NIWA_APP_AUTH_REQUIRED"] = "0"
    os.environ["NIWA_APP_HOST"] = "127.0.0.1"

    # Pre-seed schema + 003 so app boot migrations don't crash (same
    # trick as test_deployments_endpoints.py).
    c = sqlite3.connect(db_path)
    _apply_schema(c)
    _apply_migration(c, "003_deployments.sql")
    c.commit()
    c.close()

    if "app" in sys.modules:
        import app
        app.DB_PATH = Path(db_path)
    else:
        import app
    app.HOST = "127.0.0.1"
    app.PORT = port
    app.NIWA_APP_AUTH_REQUIRED = False
    app.init_db()

    srv = ThreadingHTTPServer(("127.0.0.1", port), app.Handler)
    thr = threading.Thread(target=srv.serve_forever, daemon=True)
    thr.start()
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
    try:
        os.unlink(db_path)
    except Exception:
        pass


def _post_routine(base, body):
    return _request(base, "/api/routines", method="POST", body=body)


def test_http_create_routine_improve_without_type_rejected(http_server):
    status, out = _post_routine(http_server["base"], {
        "name": "t", "schedule": "*/10 * * * *", "action": "improve",
        "action_config": {},
    })
    assert status == 400, out


def test_http_create_routine_improve_invalid_type_rejected(http_server):
    status, out = _post_routine(http_server["base"], {
        "name": "t", "schedule": "*/10 * * * *", "action": "improve",
        "improvement_type": "foo", "action_config": {},
    })
    assert status == 400, out


def test_http_create_routine_improve_valid_accepted(http_server):
    status, out = _post_routine(http_server["base"], {
        "name": "t", "schedule": "*/10 * * * *", "action": "improve",
        "improvement_type": "stability", "action_config": {},
    })
    assert status == 201, out
    assert out.get("ok") is True


def test_http_create_routine_unknown_action_rejected(http_server):
    status, out = _post_routine(http_server["base"], {
        "name": "t", "schedule": "*/10 * * * *", "action": "foobar",
        "action_config": {},
    })
    assert status == 400, out
