"""Tests for GET /api/chat-sessions/:id/messages — PR-10e Niwa v0.2.

Covers:
  - 404 on unknown session
  - 400 on invalid session id (slash)
  - 200 empty list for a just-created empty session
  - 200 with messages ordered ASC by created_at
  - Side effect isolation: unlike the legacy
    GET /api/chat/sessions/:id/messages, this endpoint MUST be a pure
    read (no auto-complete of pending tasks, no auto-injected
    delegated-task messages).

Run with: pytest tests/test_chat_sessions_v02_endpoint.py -v
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
from urllib.request import Request, urlopen

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


# ── Helpers ──────────────────────────────────────────────────────────

def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _get(base, path):
    req = Request(f"{base}{path}", method="GET")
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except Exception as e:
        if hasattr(e, "read"):
            return e.code, json.loads(e.read())
        raise


# ── Module-scoped server fixture ─────────────────────────────────────

@pytest.fixture(scope="module")
def server():
    """Start the app on a random port with a temp DB."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    port = _free_port()

    os.environ["NIWA_DB_PATH"] = db_path
    os.environ["NIWA_APP_PORT"] = str(port)
    os.environ["NIWA_APP_AUTH_REQUIRED"] = "0"
    os.environ["NIWA_APP_HOST"] = "127.0.0.1"

    if "app" in sys.modules:
        import app
        from pathlib import Path
        app.DB_PATH = Path(db_path)
        app.NIWA_APP_AUTH_REQUIRED = False
    else:
        import app  # noqa: F401
        app.NIWA_APP_AUTH_REQUIRED = False

    app.HOST = "127.0.0.1"
    app.PORT = port
    app.init_db()

    srv = ThreadingHTTPServer(("127.0.0.1", port), app.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{port}"
    for _ in range(30):
        try:
            urlopen(f"{base}/api/settings", timeout=1)
            break
        except Exception:
            time.sleep(0.1)

    yield {"base": base, "db_path": db_path}

    srv.shutdown()
    os.close(fd)
    os.unlink(db_path)


def _seed_session(db_path, messages):
    """Insert a chat_sessions row + N chat_messages rows.  Returns sid."""
    sid = str(uuid.uuid4())
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    now_base = "2026-04-14T10:00:00Z"
    conn.execute(
        "INSERT INTO chat_sessions (id, title, created_at, updated_at) "
        "VALUES (?, 'Test session', ?, ?)",
        (sid, now_base, now_base),
    )
    for i, m in enumerate(messages):
        conn.execute(
            "INSERT INTO chat_messages "
            "(id, session_id, role, content, task_id, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()), sid, m["role"], m["content"],
                m.get("task_id"), m.get("status", "done"),
                f"2026-04-14T10:00:{i:02d}Z",
            ),
        )
    conn.commit()
    conn.close()
    return sid


# ── Tests ────────────────────────────────────────────────────────────

class TestChatSessionsV02Endpoint:

    def test_404_on_unknown_session(self, server):
        unknown = str(uuid.uuid4())
        status, body = _get(
            server["base"], f"/api/chat-sessions/{unknown}/messages",
        )
        assert status == 404
        assert body["error"] == "session_not_found"

    def test_400_on_invalid_session_id(self, server):
        # A slash inside the id would break the split — the endpoint
        # must reject it before looking anything up.
        status, body = _get(
            server["base"], "/api/chat-sessions//messages",
        )
        assert status in (400, 404)  # depends on path normalization

    def test_200_empty_session(self, server):
        sid = _seed_session(server["db_path"], [])
        status, body = _get(
            server["base"], f"/api/chat-sessions/{sid}/messages",
        )
        assert status == 200
        assert body == {"messages": []}

    def test_200_messages_ordered_asc(self, server):
        sid = _seed_session(server["db_path"], [
            {"role": "user", "content": "first user msg"},
            {"role": "assistant", "content": "first assistant msg"},
            {"role": "user", "content": "second user msg"},
        ])
        status, body = _get(
            server["base"], f"/api/chat-sessions/{sid}/messages",
        )
        assert status == 200
        msgs = body["messages"]
        assert len(msgs) == 3
        # ASC order
        contents = [m["content"] for m in msgs]
        assert contents == [
            "first user msg",
            "first assistant msg",
            "second user msg",
        ]
        # Shape contract
        for m in msgs:
            assert set(m.keys()) >= {
                "id", "session_id", "role", "content",
                "task_id", "status", "created_at",
            }

    def test_pure_read_no_side_effects(self, server):
        """Regression guard: the legacy endpoint mutates (completes
        pending messages, injects delegated-task messages).  The v0.2
        endpoint MUST NOT.  Seed a pending assistant row and verify it
        remains untouched after the GET."""
        sid = _seed_session(server["db_path"], [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant", "content": "",
                "status": "pending", "task_id": "some-task-id",
            },
        ])

        # Sanity: the row is pending before.
        conn = sqlite3.connect(server["db_path"])
        conn.row_factory = sqlite3.Row
        before = conn.execute(
            "SELECT status, content FROM chat_messages "
            "WHERE session_id=? AND role='assistant'",
            (sid,),
        ).fetchone()
        assert before["status"] == "pending"
        assert before["content"] == ""
        conn.close()

        # Hit the endpoint.
        status, body = _get(
            server["base"], f"/api/chat-sessions/{sid}/messages",
        )
        assert status == 200

        # Still pending + empty.  No new rows injected.
        conn = sqlite3.connect(server["db_path"])
        conn.row_factory = sqlite3.Row
        after_rows = conn.execute(
            "SELECT status, content FROM chat_messages "
            "WHERE session_id=? ORDER BY created_at ASC",
            (sid,),
        ).fetchall()
        conn.close()
        assert len(after_rows) == 2  # no injected messages
        assistant_row = after_rows[1]
        assert assistant_row["status"] == "pending"
        assert assistant_row["content"] == ""
