"""Tests for assistant_service — PR-08 Niwa v0.2.

Step 1: routing_mode check and error-path persistence.

Run with: pytest tests/test_assistant_service.py -v
"""
import os
import sqlite3
import sys
import tempfile
import uuid

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

SCHEMA_PATH = os.path.join(ROOT_DIR, "niwa-app", "db", "schema.sql")

import assistant_service


# ── Helpers ──────────────────────────────────────────────────────────

def _make_db():
    """Create a temp DB with full schema and return (fd, path, conn)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(open(SCHEMA_PATH).read())
    return fd, path, conn


def _seed_project(conn, project_id=None):
    """Insert a minimal project.  Returns project_id."""
    pid = project_id or str(uuid.uuid4())
    now = assistant_service._now_iso()
    conn.execute(
        "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
        "VALUES (?, ?, 'Test Project', 'proyecto', ?, ?)",
        (pid, f"test-{pid[:8]}", now, now),
    )
    conn.commit()
    return pid


def _set_routing_mode(conn, value):
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('routing_mode', ?)",
        (value,),
    )
    conn.commit()


def _get_chat_messages(conn, session_id):
    rows = conn.execute(
        "SELECT role, content, status FROM chat_messages "
        "WHERE session_id = ? ORDER BY created_at ASC",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Tests: routing_mode gate ─────────────────────────────────────────

class TestRoutingModeGate:

    def setup_method(self):
        self.fd, self.path, self.conn = _make_db()

    def teardown_method(self):
        self.conn.close()
        os.close(self.fd)
        os.unlink(self.path)

    def test_routing_mode_legacy_returns_error(self):
        """routing_mode='legacy' → routing_mode_mismatch error."""
        pid = _seed_project(self.conn)
        _set_routing_mode(self.conn, "legacy")

        result = assistant_service.assistant_turn(
            session_id="sess-1",
            project_id=pid,
            message="hola",
            channel="web",
            conn=self.conn,
        )

        assert result["error"] == "routing_mode_mismatch"
        assert "v02" in result["assistant_message"]
        assert result["task_ids"] == []
        assert result["approval_ids"] == []
        assert result["run_ids"] == []

    def test_routing_mode_missing_returns_error(self):
        """No routing_mode key → routing_mode_mismatch error."""
        pid = _seed_project(self.conn)
        # Don't seed routing_mode — simulate pre-v0.2 DB
        self.conn.execute("DELETE FROM settings WHERE key='routing_mode'")
        self.conn.commit()

        result = assistant_service.assistant_turn(
            session_id="sess-2",
            project_id=pid,
            message="hola",
            channel="web",
            conn=self.conn,
        )

        assert result["error"] == "routing_mode_mismatch"
        assert "None" in result["message"]

    def test_routing_mode_v02_proceeds_to_not_implemented(self):
        """routing_mode='v02' passes the gate (hits NotImplementedError)."""
        pid = _seed_project(self.conn)
        _set_routing_mode(self.conn, "v02")

        with pytest.raises(NotImplementedError, match="LLM conversation loop"):
            assistant_service.assistant_turn(
                session_id="sess-3",
                project_id=pid,
                message="hola",
                channel="web",
                conn=self.conn,
            )


# ── Tests: error-path persistence ────────────────────────────────────

class TestErrorPathPersistence:

    def setup_method(self):
        self.fd, self.path, self.conn = _make_db()

    def teardown_method(self):
        self.conn.close()
        os.close(self.fd)
        os.unlink(self.path)

    def test_turn_persisted_on_routing_mode_error(self):
        """Both user msg and error response written to chat_messages."""
        pid = _seed_project(self.conn)
        _set_routing_mode(self.conn, "legacy")
        sid = "sess-persist-1"

        result = assistant_service.assistant_turn(
            session_id=sid,
            project_id=pid,
            message="¿Qué tareas hay?",
            channel="web",
            conn=self.conn,
        )

        canonical_sid = result["session_id"]
        msgs = _get_chat_messages(self.conn, canonical_sid)

        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "¿Qué tareas hay?"
        assert msgs[0]["status"] == "done"
        assert msgs[1]["role"] == "assistant"
        assert "routing_mode" in msgs[1]["content"]
        assert msgs[1]["status"] == "done"

    def test_session_auto_created_for_web(self):
        """Web channel auto-creates a chat_session if id doesn't exist."""
        pid = _seed_project(self.conn)
        _set_routing_mode(self.conn, "legacy")
        sid = "new-web-session"

        assistant_service.assistant_turn(
            session_id=sid,
            project_id=pid,
            message="test",
            channel="web",
            conn=self.conn,
        )

        row = self.conn.execute(
            "SELECT id, title FROM chat_sessions WHERE id = ?", (sid,),
        ).fetchone()
        assert row is not None
        assert row["title"] == "test"

    def test_session_created_for_openclaw_via_external_ref(self):
        """OpenClaw channel creates session with external_ref mapping."""
        pid = _seed_project(self.conn)
        _set_routing_mode(self.conn, "legacy")

        result = assistant_service.assistant_turn(
            session_id="oc-chat-xyz",
            project_id=pid,
            message="hola",
            channel="openclaw",
            conn=self.conn,
        )

        canonical_sid = result["session_id"]
        assert canonical_sid != "oc-chat-xyz"  # Niwa generates its own id

        row = self.conn.execute(
            "SELECT external_ref FROM chat_sessions WHERE id = ?",
            (canonical_sid,),
        ).fetchone()
        assert row["external_ref"] == "oc-chat-xyz"

    def test_openclaw_reuses_existing_session(self):
        """Second call with same external_ref reuses the session."""
        pid = _seed_project(self.conn)
        _set_routing_mode(self.conn, "legacy")

        r1 = assistant_service.assistant_turn(
            session_id="oc-reuse",
            project_id=pid,
            message="msg1",
            channel="openclaw",
            conn=self.conn,
        )
        r2 = assistant_service.assistant_turn(
            session_id="oc-reuse",
            project_id=pid,
            message="msg2",
            channel="openclaw",
            conn=self.conn,
        )

        assert r1["session_id"] == r2["session_id"]

    def test_project_not_found_persists_error(self):
        """Invalid project_id persists user msg + error in chat_messages."""
        _set_routing_mode(self.conn, "v02")
        sid = "sess-no-proj"

        result = assistant_service.assistant_turn(
            session_id=sid,
            project_id="nonexistent-id",
            message="hola",
            channel="web",
            conn=self.conn,
        )

        assert result["error"] == "project_not_found"
        msgs = _get_chat_messages(self.conn, sid)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert "no encontrado" in msgs[1]["content"].lower()


# ── Tests: input validation ──────────────────────────────────────────

class TestInputValidation:

    def setup_method(self):
        self.fd, self.path, self.conn = _make_db()

    def teardown_method(self):
        self.conn.close()
        os.close(self.fd)
        os.unlink(self.path)

    def test_missing_session_id(self):
        result = assistant_service.assistant_turn(
            session_id="",
            project_id="p1",
            message="hi",
            channel="web",
            conn=self.conn,
        )
        assert result["error"] == "missing_session_id"

    def test_missing_project_id(self):
        result = assistant_service.assistant_turn(
            session_id="s1",
            project_id="",
            message="hi",
            channel="web",
            conn=self.conn,
        )
        assert result["error"] == "missing_project_id"

    def test_empty_message(self):
        result = assistant_service.assistant_turn(
            session_id="s1",
            project_id="p1",
            message="   ",
            channel="web",
            conn=self.conn,
        )
        assert result["error"] == "empty_message"
