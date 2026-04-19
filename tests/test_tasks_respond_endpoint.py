"""FIX-20260420 — POST /api/tasks/:id/respond endpoint.

Five cases mapped to the brief:

  1. 404 when task does not exist.
  2. 409 when task is not in waiting_input.
  3. 400 when body or message is empty.
  4. 201 happy path — marker + followup stored, task flips to pendiente.
  5. Idempotency — two POSTs with different messages overwrite the
     followup (latest wins) but do not duplicate the run, because the
     second POST finds the task already in ``pendiente`` and is
     rejected with 409.

Run: pytest tests/test_tasks_respond_endpoint.py -v
"""
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


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
    yield {"base": base, "app": app, "db": db_path}
    srv.shutdown()
    srv.server_close()


def _seed_waiting_input_task(db: str, *, with_run: bool = True):
    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    bp_id = str(uuid.uuid4())
    rd_id = str(uuid.uuid4())
    now = "2026-04-19T20:00:00Z"
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
            "current_run_id, created_at, updated_at) VALUES "
            "(?, 'clarify-me', 'waiting_input', 'media', 'proyecto', "
            "'niwa-app', ?, ?, ?)",
            (task_id, run_id if with_run else None, now, now),
        )
        if with_run:
            c.execute(
                "INSERT INTO routing_decisions (id, task_id, decision_index, "
                "selected_profile_id, created_at) VALUES (?, ?, 0, ?, ?)",
                (rd_id, task_id, bp_id, now),
            )
            c.execute(
                "INSERT INTO backend_runs (id, task_id, routing_decision_id, "
                "backend_profile_id, backend_kind, runtime_kind, status, "
                "outcome, error_code, created_at, updated_at, finished_at) "
                "VALUES (?, ?, ?, ?, 'claude_code', 'cli', 'waiting_input', "
                "'needs_clarification', 'clarification_required', ?, ?, ?)",
                (run_id, task_id, rd_id, bp_id, now, now, now),
            )
        c.commit()
    return {"task_id": task_id, "run_id": run_id}


# ─── Case 1: 404 when task missing ─────────────────────────────


def test_respond_404_when_task_missing(app_server):
    status, out = _req(
        app_server["base"],
        "/api/tasks/does-not-exist/respond",
        method="POST",
        body={"message": "anything"},
    )
    assert status == 404
    assert out["error"] == "not_found"


# ─── Case 2: 409 when task not in waiting_input ────────────────


def test_respond_409_when_task_not_waiting_input(app_server):
    s = _seed_waiting_input_task(app_server["db"])
    # Flip the task out of waiting_input first.
    with sqlite3.connect(app_server["db"]) as c:
        c.execute(
            "UPDATE tasks SET status='en_progreso' WHERE id=?",
            (s["task_id"],),
        )
        c.commit()

    status, out = _req(
        app_server["base"],
        f"/api/tasks/{s['task_id']}/respond",
        method="POST",
        body={"message": "anything"},
    )
    assert status == 409
    assert out["error"] == "invalid_state"
    assert out["status"] == "en_progreso"


# ─── Case 3: 400 when body / message empty ──────────────────────


def test_respond_400_when_message_empty(app_server):
    s = _seed_waiting_input_task(app_server["db"])
    status, out = _req(
        app_server["base"],
        f"/api/tasks/{s['task_id']}/respond",
        method="POST",
        body={"message": ""},
    )
    assert status == 400
    assert out["error"] == "empty_message"


def test_respond_400_when_message_whitespace_only(app_server):
    s = _seed_waiting_input_task(app_server["db"])
    status, out = _req(
        app_server["base"],
        f"/api/tasks/{s['task_id']}/respond",
        method="POST",
        body={"message": "   \n  \t"},
    )
    assert status == 400
    assert out["error"] == "empty_message"


def test_respond_400_when_message_missing_key(app_server):
    s = _seed_waiting_input_task(app_server["db"])
    status, out = _req(
        app_server["base"],
        f"/api/tasks/{s['task_id']}/respond",
        method="POST",
        body={},
    )
    assert status == 400
    assert out["error"] == "empty_message"


def test_respond_400_when_message_too_long(app_server):
    s = _seed_waiting_input_task(app_server["db"])
    status, out = _req(
        app_server["base"],
        f"/api/tasks/{s['task_id']}/respond",
        method="POST",
        body={"message": "x" * 10_001},
    )
    assert status == 400
    assert out["error"] == "message_too_long"


# ─── Case 4: 409 when no prior run ─────────────────────────────


def test_respond_409_when_no_previous_run(app_server):
    s = _seed_waiting_input_task(app_server["db"], with_run=False)
    status, out = _req(
        app_server["base"],
        f"/api/tasks/{s['task_id']}/respond",
        method="POST",
        body={"message": "follow up"},
    )
    assert status == 409
    assert out["error"] == "no_previous_run"


# ─── Case 5: 201 happy path ────────────────────────────────────


def test_respond_happy_path_sets_marker_and_flips_status(app_server):
    s = _seed_waiting_input_task(app_server["db"])
    status, out = _req(
        app_server["base"],
        f"/api/tasks/{s['task_id']}/respond",
        method="POST",
        body={"message": "haz la versión azul"},
    )
    assert status == 201, out
    assert out["status"] == "pendiente"
    assert out["resume_from_run_id"] == s["run_id"]
    assert out["task_id"] == s["task_id"]

    # DB side: markers populated, status flipped.
    with sqlite3.connect(app_server["db"]) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT status, resume_from_run_id, pending_followup_message "
            "FROM tasks WHERE id=?",
            (s["task_id"],),
        ).fetchone()
    assert row["status"] == "pendiente"
    assert row["resume_from_run_id"] == s["run_id"]
    assert row["pending_followup_message"] == "haz la versión azul"

    # Task event recorded so the timeline carries the transition.
    with sqlite3.connect(app_server["db"]) as c:
        c.row_factory = sqlite3.Row
        evt = c.execute(
            "SELECT payload_json FROM task_events WHERE task_id=? "
            "ORDER BY created_at DESC LIMIT 1",
            (s["task_id"],),
        ).fetchone()
    assert evt is not None
    payload = json.loads(evt["payload_json"])
    assert payload["source"] == "user_respond"
    assert payload["resume_from_run_id"] == s["run_id"]


# ─── Case 6: second POST is rejected (no duplicates) ──────────


def test_second_respond_after_flip_returns_409(app_server):
    s = _seed_waiting_input_task(app_server["db"])
    status1, out1 = _req(
        app_server["base"],
        f"/api/tasks/{s['task_id']}/respond",
        method="POST",
        body={"message": "first attempt"},
    )
    assert status1 == 201

    status2, out2 = _req(
        app_server["base"],
        f"/api/tasks/{s['task_id']}/respond",
        method="POST",
        body={"message": "second attempt"},
    )
    # Task is no longer in waiting_input → 409.
    assert status2 == 409
    assert out2["error"] == "invalid_state"
    assert out2["status"] == "pendiente"

    with sqlite3.connect(app_server["db"]) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT pending_followup_message FROM tasks WHERE id=?",
            (s["task_id"],),
        ).fetchone()
    # First message persisted; second was rejected before touching.
    assert row["pending_followup_message"] == "first attempt"
