"""Tests for PR-04 — cancel(), heartbeat(), resume() with mocked subprocess.

Covers:
  - cancel idempotent (no process → still returns cancelled)
  - cancel sends SIGTERM, escalates to SIGKILL on timeout
  - cancel updates backend_runs.status to cancelled
  - heartbeat returns alive/dead, updates heartbeat_at
  - resume passes --resume <session_id> and works end-to-end
  - resume without session_handle returns failure
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from unittest.mock import MagicMock, patch, call

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

SCHEMA_PATH = os.path.join(ROOT_DIR, "niwa-app", "db", "schema.sql")

import runs_service
from backend_adapters.claude_code import ClaudeCodeAdapter, CANCEL_SIGTERM_WAIT_SECONDS


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
        "VALUES (?, 'p', 'P', 'proyecto', ?, ?)",
        (str(uuid.uuid4()), now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, title, area, status, priority, created_at, updated_at) "
        "VALUES (?, 'Test', 'proyecto', 'en_progreso', 'media', ?, ?)",
        (task_id, now, now),
    )
    conn.execute(
        "INSERT INTO backend_profiles (id, slug, display_name, backend_kind, "
        "runtime_kind, default_model, enabled, priority, created_at, updated_at) "
        "VALUES (?, 'claude_code', 'Claude', 'claude_code', 'cli', "
        "'claude-sonnet-4-6', 1, 10, ?, ?)",
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


def _mock_popen_success(stream_text, returncode=0):
    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdout = iter(stream_text.encode("utf-8").splitlines(keepends=True))
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = b""
    mock_proc.returncode = returncode
    mock_proc.pid = 88888
    mock_proc.wait.return_value = returncode
    mock_proc.poll.return_value = returncode
    return mock_proc


# ═══════════════════════════════════════════════════════════════════
# 1. cancel()
# ═══════════════════════════════════════════════════════════════════

class TestCancel:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id = _seed(self.conn)
        self.adapter = ClaudeCodeAdapter(db_conn_factory=_db_factory(self.db_path))

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_cancel_no_process_is_idempotent(self):
        """cancel() with no tracked process returns cancelled without error."""
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        result = self.adapter.cancel(run)
        assert result["status"] == "cancelled"
        assert result["outcome"] == "cancelled"

    def test_cancel_sends_sigterm(self):
        """cancel() calls terminate() on the tracked process."""
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        # Manually inject a mock process
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.wait.return_value = 0
        mock_proc.poll.return_value = None
        with self.adapter._lock:
            self.adapter._processes[run["id"]] = mock_proc

        # Advance run to running so finish_run works
        runs_service.transition_run(run["id"], "starting", self.conn)
        runs_service.transition_run(run["id"], "running", self.conn)

        result = self.adapter.cancel(run)
        mock_proc.terminate.assert_called_once()
        assert result["status"] == "cancelled"

    def test_cancel_escalates_to_sigkill(self):
        """If terminate doesn't stop the process, kill() is called."""
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="claude", timeout=5),
            0,
        ]
        with self.adapter._lock:
            self.adapter._processes[run["id"]] = mock_proc

        runs_service.transition_run(run["id"], "starting", self.conn)
        runs_service.transition_run(run["id"], "running", self.conn)

        self.adapter.cancel(run)
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()

    def test_cancel_updates_db_status(self):
        """cancel() sets backend_runs.status to 'cancelled'."""
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.wait.return_value = 0
        with self.adapter._lock:
            self.adapter._processes[run["id"]] = mock_proc

        runs_service.transition_run(run["id"], "starting", self.conn)
        runs_service.transition_run(run["id"], "running", self.conn)

        self.adapter.cancel(run)

        row = self.conn.execute(
            "SELECT status FROM backend_runs WHERE id = ?", (run["id"],),
        ).fetchone()
        assert row["status"] == "cancelled"

    def test_cancel_records_event(self):
        """cancel() writes a 'cancelled' event."""
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.wait.return_value = 0
        with self.adapter._lock:
            self.adapter._processes[run["id"]] = mock_proc

        runs_service.transition_run(run["id"], "starting", self.conn)
        runs_service.transition_run(run["id"], "running", self.conn)

        self.adapter.cancel(run)

        events = self.conn.execute(
            "SELECT event_type FROM backend_run_events "
            "WHERE backend_run_id = ?",
            (run["id"],),
        ).fetchall()
        assert any(e["event_type"] == "cancelled" for e in events)

    def test_cancel_idempotent_on_terminal_run(self):
        """cancel() on an already-finished run doesn't crash."""
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        runs_service.transition_run(run["id"], "starting", self.conn)
        runs_service.transition_run(run["id"], "running", self.conn)
        runs_service.finish_run(run["id"], "success", self.conn, exit_code=0)

        # No process tracked, run already succeeded
        result = self.adapter.cancel(run)
        assert result["status"] == "cancelled"


# ═══════════════════════════════════════════════════════════════════
# 2. heartbeat()
# ═══════════════════════════════════════════════════════════════════

class TestHeartbeat:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id = _seed(self.conn)
        self.adapter = ClaudeCodeAdapter(db_conn_factory=_db_factory(self.db_path))

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_no_process_returns_not_alive(self):
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        result = self.adapter.heartbeat(run)
        assert result["alive"] is False

    def test_alive_process_returns_alive(self):
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        mock_proc = MagicMock()
        mock_proc.pid = 54321
        mock_proc.poll.return_value = None  # still running
        with self.adapter._lock:
            self.adapter._processes[run["id"]] = mock_proc

        result = self.adapter.heartbeat(run)
        assert result["alive"] is True
        assert "54321" in result["details"]

    def test_dead_process_returns_not_alive(self):
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        mock_proc = MagicMock()
        mock_proc.pid = 54321
        mock_proc.poll.return_value = 0  # exited
        with self.adapter._lock:
            self.adapter._processes[run["id"]] = mock_proc

        result = self.adapter.heartbeat(run)
        assert result["alive"] is False

    def test_heartbeat_updates_db(self):
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        mock_proc = MagicMock()
        mock_proc.pid = 54321
        mock_proc.poll.return_value = None
        with self.adapter._lock:
            self.adapter._processes[run["id"]] = mock_proc

        assert run["heartbeat_at"] is None
        self.adapter.heartbeat(run)

        row = self.conn.execute(
            "SELECT heartbeat_at FROM backend_runs WHERE id = ?",
            (run["id"],),
        ).fetchone()
        assert row["heartbeat_at"] is not None


# ═══════════════════════════════════════════════════════════════════
# 3. resume()
# ═══════════════════════════════════════════════════════════════════

class TestResume:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id = _seed(self.conn)
        self.adapter = ClaudeCodeAdapter(db_conn_factory=_db_factory(self.db_path))

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_resume_without_session_handle_fails(self):
        """resume() fails if prior_run has no session_handle."""
        prior_run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        new_run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            previous_run_id=prior_run["id"], relation_type="resume",
        )
        result = self.adapter.resume(
            {"id": self.task_id, "title": "T"},
            prior_run, new_run,
            {"default_model": "claude-sonnet-4-6"}, {},
        )
        assert result["status"] == "failed"
        assert result["error_code"] == "no_session_handle"

    @patch("subprocess.Popen")
    def test_resume_passes_session_id(self, mock_popen_cls):
        """resume() builds command with --resume <session_id>."""
        stream = "\n".join([
            json.dumps({"type": "result", "session_id": "sess-resumed", "cost_usd": 0.01}),
        ]) + "\n"
        mock_popen_cls.return_value = _mock_popen_success(stream)

        # Create prior run with a session_handle
        prior_run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        runs_service.update_session_handle(prior_run["id"], "sess-original", self.conn)
        prior_run["session_handle"] = "sess-original"

        new_run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            previous_run_id=prior_run["id"], relation_type="resume",
        )

        result = self.adapter.resume(
            {"id": self.task_id, "title": "T"},
            prior_run, new_run,
            {"default_model": "claude-sonnet-4-6"}, {},
        )
        assert result["status"] == "succeeded"

        # Verify --resume was in the command
        call_args = mock_popen_cls.call_args
        cmd = call_args[0][0]
        assert "--resume" in cmd
        resume_idx = cmd.index("--resume")
        assert cmd[resume_idx + 1] == "sess-original"

    @patch("subprocess.Popen")
    def test_resume_new_run_reaches_terminal(self, mock_popen_cls):
        stream = json.dumps({"type": "result", "cost_usd": 0.01}) + "\n"
        mock_popen_cls.return_value = _mock_popen_success(stream)

        prior_run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        runs_service.update_session_handle(prior_run["id"], "sess-x", self.conn)
        prior_run["session_handle"] = "sess-x"

        new_run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            previous_run_id=prior_run["id"], relation_type="resume",
        )

        self.adapter.resume(
            {"id": self.task_id, "title": "T"},
            prior_run, new_run,
            {"default_model": "claude-sonnet-4-6"}, {},
        )

        row = self.conn.execute(
            "SELECT status, relation_type FROM backend_runs WHERE id = ?",
            (new_run["id"],),
        ).fetchone()
        assert row["status"] == "succeeded"
        assert row["relation_type"] == "resume"
