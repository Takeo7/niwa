"""Unit tests for CodexAdapter lifecycle methods — PR-07 Niwa v0.2.

Covers cancel(), heartbeat(), and resume().
"""

import os
import sqlite3
import sys
import tempfile
import uuid
from unittest import mock

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

SCHEMA_PATH = os.path.join(ROOT_DIR, "niwa-app", "db", "schema.sql")

import runs_service
from backend_adapters.codex import CodexAdapter


# ── Helpers ──────────────────────────────────────────────────────

def _make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(open(SCHEMA_PATH).read())
    return fd, path, conn


def _seed(conn):
    now = runs_service._now_iso()
    task_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    rd_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
        "VALUES (?, 'test', 'Test', 'proyecto', ?, ?)",
        (str(uuid.uuid4()), now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, title, description, area, status, priority, "
        "created_at, updated_at) VALUES (?, 'Test', 'desc', 'proyecto', "
        "'en_progreso', 'media', ?, ?)",
        (task_id, now, now),
    )
    conn.execute(
        "INSERT INTO backend_profiles (id, slug, display_name, backend_kind, "
        "runtime_kind, default_model, enabled, priority, created_at, updated_at) "
        "VALUES (?, 'codex', 'Codex', 'codex', 'cli', 'o4-mini', 1, 5, ?, ?)",
        (profile_id, now, now),
    )
    conn.execute(
        "INSERT INTO routing_decisions (id, task_id, decision_index, "
        "selected_profile_id, created_at) VALUES (?, ?, 0, ?, ?)",
        (rd_id, task_id, profile_id, now),
    )
    conn.commit()
    return task_id, profile_id, rd_id


def _db_factory(db_path):
    def factory():
        c = sqlite3.connect(db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c
    return factory


# ═══════════════════════════════════════════════════════════════════
# Cancel
# ═══════════════════════════════════════════════════════════════════

class TestCodexCancel:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id = _seed(self.conn)
        self.adapter = CodexAdapter(db_conn_factory=_db_factory(self.db_path))

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_cancel_no_process_is_idempotent(self):
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        result = self.adapter.cancel(run)
        assert result["status"] == "cancelled"

    def test_cancel_terminates_process(self):
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        # Transition to running so cancel → cancelled is valid
        runs_service.transition_run(run["id"], "starting", self.conn)
        runs_service.transition_run(run["id"], "running", self.conn)

        proc = mock.MagicMock()
        proc.pid = 99999
        proc.wait.return_value = 0
        with self.adapter._lock:
            self.adapter._processes[run["id"]] = proc

        result = self.adapter.cancel(run)

        assert result["status"] == "cancelled"
        proc.terminate.assert_called_once()
        assert run["id"] not in self.adapter._processes

    def test_cancel_escalates_to_sigkill(self):
        import subprocess as sp
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        runs_service.transition_run(run["id"], "starting", self.conn)
        runs_service.transition_run(run["id"], "running", self.conn)

        proc = mock.MagicMock()
        proc.pid = 99999
        # First wait (after terminate) times out; second wait (after kill) succeeds
        proc.wait.side_effect = [
            sp.TimeoutExpired("codex", 5),
            0,
        ]
        with self.adapter._lock:
            self.adapter._processes[run["id"]] = proc

        result = self.adapter.cancel(run)

        assert result["status"] == "cancelled"
        proc.kill.assert_called_once()

    def test_cancel_records_event_in_db(self):
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        # Transition to running so cancel can transition to cancelled
        runs_service.transition_run(run["id"], "starting", self.conn)
        runs_service.transition_run(run["id"], "running", self.conn)

        proc = mock.MagicMock()
        proc.pid = 12345
        proc.wait.return_value = 0
        with self.adapter._lock:
            self.adapter._processes[run["id"]] = proc

        self.adapter.cancel(run)

        events = self.conn.execute(
            "SELECT event_type FROM backend_run_events "
            "WHERE backend_run_id = ?", (run["id"],),
        ).fetchall()
        assert any(e["event_type"] == "cancelled" for e in events)

        db_run = self.conn.execute(
            "SELECT status FROM backend_runs WHERE id = ?",
            (run["id"],),
        ).fetchone()
        assert db_run["status"] == "cancelled"


# ═══════════════════════════════════════════════════════════════════
# Heartbeat
# ═══════════════════════════════════════════════════════════════════

class TestCodexHeartbeat:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id = _seed(self.conn)
        self.adapter = CodexAdapter(db_conn_factory=_db_factory(self.db_path))

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_heartbeat_no_process(self):
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        result = self.adapter.heartbeat(run)
        assert result["alive"] is False

    def test_heartbeat_alive_process(self):
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        proc = mock.MagicMock()
        proc.pid = 12345
        proc.poll.return_value = None
        with self.adapter._lock:
            self.adapter._processes[run["id"]] = proc

        result = self.adapter.heartbeat(run)
        assert result["alive"] is True
        assert "12345" in result["details"]

    def test_heartbeat_dead_process(self):
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        proc = mock.MagicMock()
        proc.pid = 12345
        proc.poll.return_value = 0
        with self.adapter._lock:
            self.adapter._processes[run["id"]] = proc

        result = self.adapter.heartbeat(run)
        assert result["alive"] is False

    def test_heartbeat_updates_db(self):
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        proc = mock.MagicMock()
        proc.pid = 12345
        proc.poll.return_value = None
        with self.adapter._lock:
            self.adapter._processes[run["id"]] = proc

        self.adapter.heartbeat(run)

        db_run = self.conn.execute(
            "SELECT heartbeat_at FROM backend_runs WHERE id = ?",
            (run["id"],),
        ).fetchone()
        assert db_run["heartbeat_at"] is not None

    def test_heartbeat_without_db_factory_works(self):
        adapter = CodexAdapter()
        run = {"id": "fake-run-id"}
        result = adapter.heartbeat(run)
        assert result["alive"] is False


# ═══════════════════════════════════════════════════════════════════
# Resume
# ═══════════════════════════════════════════════════════════════════

class TestCodexResume:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id = _seed(self.conn)
        self.adapter = CodexAdapter(db_conn_factory=_db_factory(self.db_path))

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_resume_fails_explicitly(self):
        prior_run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        new_run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            previous_run_id=prior_run["id"], relation_type="resume",
        )

        result = self.adapter.resume(
            {"id": self.task_id}, prior_run, new_run, {}, {},
        )

        assert result["status"] == "failed"
        assert result["error_code"] == "resume_not_supported"

    def test_resume_marks_run_failed_in_db(self):
        prior_run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        new_run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            previous_run_id=prior_run["id"], relation_type="resume",
        )

        self.adapter.resume(
            {"id": self.task_id}, prior_run, new_run, {}, {},
        )

        db_run = self.conn.execute(
            "SELECT status, error_code FROM backend_runs WHERE id = ?",
            (new_run["id"],),
        ).fetchone()
        assert db_run["status"] == "failed"

    def test_resume_records_event(self):
        prior_run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        new_run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            previous_run_id=prior_run["id"], relation_type="resume",
        )

        self.adapter.resume(
            {"id": self.task_id}, prior_run, new_run, {}, {},
        )

        events = self.conn.execute(
            "SELECT event_type FROM backend_run_events "
            "WHERE backend_run_id = ?", (new_run["id"],),
        ).fetchall()
        assert any(e["event_type"] == "resume_not_supported"
                    for e in events)

    def test_resume_without_db_factory_raises(self):
        adapter = CodexAdapter()
        with pytest.raises(RuntimeError, match="db_conn_factory"):
            adapter.resume({}, {}, {}, {}, {})

    def test_resume_modes_is_empty(self):
        caps = self.adapter.capabilities()
        assert caps["resume_modes"] == []
