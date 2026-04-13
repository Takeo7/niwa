"""Tests for PR-04 — ClaudeCodeAdapter.start() with mocked subprocess.

Covers:
  - Run transitions queued → starting → running → succeeded/failed
  - artifact_root directory created
  - session_handle persisted from stream-json session_id
  - Events written to backend_run_events
  - Approval gate stub consulted
  - CLI command never contains --dangerously-skip-permissions
  - Usage signals persisted in observed_usage_signals_json
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

SCHEMA_PATH = os.path.join(ROOT_DIR, "niwa-app", "db", "schema.sql")

import runs_service
from backend_adapters.claude_code import ClaudeCodeAdapter, check_approval_gate


# ── Helpers ──────────────────────────────────────────────────────

def _make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(open(SCHEMA_PATH).read())
    return fd, path, conn


def _seed(conn):
    """Seed task + profile + routing_decision. Returns (task_id, profile_id, rd_id)."""
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


def _stream_lines(*msgs):
    """Encode dicts as newline-separated JSON bytes (stdout simulation)."""
    text = "\n".join(json.dumps(m) for m in msgs) + "\n"
    return text.encode("utf-8")


def _mock_popen_success(stdout_data, returncode=0):
    """Create a mock Popen that yields stdout_data and exits with returncode."""
    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdout = iter(stdout_data.encode("utf-8").splitlines(keepends=True))
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = b""
    mock_proc.returncode = returncode
    mock_proc.pid = 99999
    mock_proc.wait.return_value = returncode
    mock_proc.poll.return_value = returncode
    return mock_proc


# ═══════════════════════════════════════════════════════════════════
# 1. Happy path — start() with successful execution
# ═══════════════════════════════════════════════════════════════════

class TestStartHappyPath:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id = _seed(self.conn)
        self.adapter = ClaudeCodeAdapter(
            db_conn_factory=lambda: sqlite3.connect(
                self.db_path, timeout=10,
            ).__enter__() or self._connect(),
        )
        # Proper factory that returns Row-enabled connections
        def _factory():
            c = sqlite3.connect(self.db_path, timeout=10)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys=ON")
            return c
        self.adapter = ClaudeCodeAdapter(db_conn_factory=_factory)

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def _create_run(self, artifact_root=None):
        return runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            backend_kind="claude_code", runtime_kind="cli",
            artifact_root=artifact_root,
        )

    @patch("subprocess.Popen")
    def test_start_returns_succeeded(self, mock_popen_cls):
        stream = "\n".join([
            json.dumps({"type": "system", "subtype": "init", "session_id": "sess-abc"}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Done"}]}}),
            json.dumps({"type": "result", "session_id": "sess-abc", "cost_usd": 0.01,
                         "duration_ms": 3000, "model": "claude-sonnet-4-6",
                         "usage": {"input_tokens": 500, "output_tokens": 200}}),
        ]) + "\n"
        mock_popen_cls.return_value = _mock_popen_success(stream, returncode=0)

        run = self._create_run()
        task = {"id": self.task_id, "title": "Test task"}
        profile = {"default_model": "claude-sonnet-4-6"}

        result = self.adapter.start(task, run, profile, {})

        assert result["status"] == "succeeded"
        assert result["outcome"] == "success"
        assert result["exit_code"] == 0
        assert result["session_handle"] == "sess-abc"

    @patch("subprocess.Popen")
    def test_start_persists_session_handle(self, mock_popen_cls):
        stream = "\n".join([
            json.dumps({"type": "system", "subtype": "init", "session_id": "sess-xyz"}),
            json.dumps({"type": "result", "session_id": "sess-xyz", "cost_usd": 0.01}),
        ]) + "\n"
        mock_popen_cls.return_value = _mock_popen_success(stream)

        run = self._create_run()
        self.adapter.start({"id": self.task_id, "title": "T"}, run, {"default_model": "claude-sonnet-4-6"}, {})

        row = self.conn.execute(
            "SELECT session_handle FROM backend_runs WHERE id = ?", (run["id"],)
        ).fetchone()
        assert row["session_handle"] == "sess-xyz"

    @patch("subprocess.Popen")
    def test_start_writes_events(self, mock_popen_cls):
        stream = "\n".join([
            json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}}),
            json.dumps({"type": "tool_use", "name": "Read", "input": {"path": "/tmp"}}),
            json.dumps({"type": "tool_result", "content": "file data"}),
            json.dumps({"type": "result", "session_id": "s1", "cost_usd": 0.02}),
        ]) + "\n"
        mock_popen_cls.return_value = _mock_popen_success(stream)

        run = self._create_run()
        self.adapter.start({"id": self.task_id, "title": "T"}, run, {"default_model": "claude-sonnet-4-6"}, {})

        events = self.conn.execute(
            "SELECT event_type FROM backend_run_events "
            "WHERE backend_run_id = ? ORDER BY created_at",
            (run["id"],),
        ).fetchall()
        types = [e["event_type"] for e in events]
        assert "system_init" in types
        assert "assistant_message" in types
        assert "tool_use" in types
        assert "tool_result" in types
        assert "result" in types

    @patch("subprocess.Popen")
    def test_start_persists_usage_signals(self, mock_popen_cls):
        stream = "\n".join([
            json.dumps({"type": "result", "cost_usd": 0.05, "duration_ms": 8000,
                         "model": "claude-sonnet-4-6",
                         "usage": {"input_tokens": 1000, "output_tokens": 400}}),
        ]) + "\n"
        mock_popen_cls.return_value = _mock_popen_success(stream)

        run = self._create_run()
        self.adapter.start({"id": self.task_id, "title": "T"}, run, {"default_model": "claude-sonnet-4-6"}, {})

        row = self.conn.execute(
            "SELECT observed_usage_signals_json FROM backend_runs WHERE id = ?",
            (run["id"],),
        ).fetchone()
        usage = json.loads(row["observed_usage_signals_json"])
        assert usage["cost_usd"] == 0.05
        assert usage["input_tokens"] == 1000

    @patch("subprocess.Popen")
    def test_start_creates_artifact_root(self, mock_popen_cls):
        stream = json.dumps({"type": "result", "cost_usd": 0.01}) + "\n"
        mock_popen_cls.return_value = _mock_popen_success(stream)

        with tempfile.TemporaryDirectory() as tmpdir:
            art_root = os.path.join(tmpdir, "runs", "test-run")
            run = self._create_run(artifact_root=art_root)
            self.adapter.start(
                {"id": self.task_id, "title": "T"}, run,
                {"default_model": "claude-sonnet-4-6"}, {},
            )
            assert os.path.isdir(art_root)

    @patch("subprocess.Popen")
    def test_start_run_reaches_terminal_state(self, mock_popen_cls):
        stream = json.dumps({"type": "result", "cost_usd": 0.01}) + "\n"
        mock_popen_cls.return_value = _mock_popen_success(stream)

        run = self._create_run()
        self.adapter.start({"id": self.task_id, "title": "T"}, run, {"default_model": "claude-sonnet-4-6"}, {})

        row = self.conn.execute(
            "SELECT status, outcome, exit_code, started_at, finished_at "
            "FROM backend_runs WHERE id = ?", (run["id"],)
        ).fetchone()
        assert row["status"] == "succeeded"
        assert row["outcome"] == "success"
        assert row["exit_code"] == 0
        assert row["started_at"] is not None
        assert row["finished_at"] is not None


# ═══════════════════════════════════════════════════════════════════
# 2. Failure path — non-zero exit
# ═══════════════════════════════════════════════════════════════════

class TestStartFailurePath:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id = _seed(self.conn)

        def _factory():
            c = sqlite3.connect(self.db_path, timeout=10)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys=ON")
            return c
        self.adapter = ClaudeCodeAdapter(db_conn_factory=_factory)

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    @patch("subprocess.Popen")
    def test_nonzero_exit_results_in_failed(self, mock_popen_cls):
        stream = json.dumps({"type": "error", "error": {"message": "Auth failed"}}) + "\n"
        mock_proc = _mock_popen_success(stream, returncode=1)
        mock_proc.stderr.read.return_value = b"Error: authentication failed"
        mock_popen_cls.return_value = mock_proc

        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        result = self.adapter.start(
            {"id": self.task_id, "title": "T"}, run,
            {"default_model": "claude-sonnet-4-6"}, {},
        )
        assert result["status"] == "failed"
        assert result["outcome"] == "failure"
        assert result["exit_code"] == 1

        row = self.conn.execute(
            "SELECT status, exit_code FROM backend_runs WHERE id = ?",
            (run["id"],),
        ).fetchone()
        assert row["status"] == "failed"
        assert row["exit_code"] == 1

    @patch("subprocess.Popen")
    def test_stderr_recorded_as_error_event(self, mock_popen_cls):
        stream = json.dumps({"type": "result", "cost_usd": 0}) + "\n"
        mock_proc = _mock_popen_success(stream, returncode=1)
        mock_proc.stderr.read.return_value = b"some error output"
        mock_popen_cls.return_value = mock_proc

        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        self.adapter.start(
            {"id": self.task_id, "title": "T"}, run,
            {"default_model": "claude-sonnet-4-6"}, {},
        )
        events = self.conn.execute(
            "SELECT event_type, message FROM backend_run_events "
            "WHERE backend_run_id = ? AND event_type = 'error'",
            (run["id"],),
        ).fetchall()
        assert any("some error output" in (e["message"] or "") for e in events)


# ═══════════════════════════════════════════════════════════════════
# 3. Command safety
# ═══════════════════════════════════════════════════════════════════

class TestCommandSafety:

    def test_build_command_never_has_dangerous_flag(self):
        cmd = ClaudeCodeAdapter._build_command(
            model="claude-sonnet-4-6", profile={},
        )
        assert "--dangerously-skip-permissions" not in cmd

    def test_build_command_with_resume(self):
        cmd = ClaudeCodeAdapter._build_command(
            model="claude-sonnet-4-6",
            resume_session_id="sess-123",
            profile={},
        )
        assert "--resume" in cmd
        idx = cmd.index("--resume")
        assert cmd[idx + 1] == "sess-123"

    def test_build_command_uses_stream_json(self):
        cmd = ClaudeCodeAdapter._build_command(
            model="claude-sonnet-4-6", profile={},
        )
        assert "--output-format" in cmd
        idx = cmd.index("--output-format")
        assert cmd[idx + 1] == "stream-json"

    def test_build_command_uses_print_mode(self):
        cmd = ClaudeCodeAdapter._build_command(
            model="claude-sonnet-4-6", profile={},
        )
        assert "-p" in cmd

    def test_command_template_override(self):
        cmd = ClaudeCodeAdapter._build_command(
            model="claude-sonnet-4-6",
            profile={"command_template": "/usr/local/bin/claude"},
        )
        assert cmd[0] == "/usr/local/bin/claude"


# ═══════════════════════════════════════════════════════════════════
# 4. Approval gate
# ═══════════════════════════════════════════════════════════════════

class TestApprovalGate:

    def test_stub_always_returns_true(self):
        assert check_approval_gate({}, {}, {}, {}) is True

    @patch("backend_adapters.claude_code.check_approval_gate", return_value=False)
    def test_start_returns_rejected_when_denied(self, mock_gate):
        adapter = ClaudeCodeAdapter()
        result = adapter.start(
            {"id": "t1", "title": "T"},
            {"id": "r1", "artifact_root": None},
            {"default_model": "claude-sonnet-4-6"},
            {},
        )
        assert result["status"] == "rejected"
        assert result["reason"] == "approval_denied"


# ═══════════════════════════════════════════════════════════════════
# 5. Event classification
# ═══════════════════════════════════════════════════════════════════

class TestEventClassification:

    def test_system_init(self):
        et, msg, _ = ClaudeCodeAdapter._classify_event(
            {"type": "system", "subtype": "init", "session_id": "s1"},
        )
        assert et == "system_init"

    def test_assistant_message(self):
        et, msg, _ = ClaudeCodeAdapter._classify_event(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello"}]}},
        )
        assert et == "assistant_message"
        assert "Hello" in msg

    def test_tool_use(self):
        et, msg, payload = ClaudeCodeAdapter._classify_event(
            {"type": "tool_use", "name": "Bash", "input": {"cmd": "ls"}},
        )
        assert et == "tool_use"
        assert "Bash" in msg
        assert payload["tool_name"] == "Bash"

    def test_tool_result(self):
        et, msg, _ = ClaudeCodeAdapter._classify_event(
            {"type": "tool_result", "content": "output data"},
        )
        assert et == "tool_result"
        assert "output data" in msg

    def test_result(self):
        et, msg, _ = ClaudeCodeAdapter._classify_event(
            {"type": "result", "cost_usd": 0.05},
        )
        assert et == "result"
        assert "0.05" in msg

    def test_error(self):
        et, msg, _ = ClaudeCodeAdapter._classify_event(
            {"type": "error", "error": {"message": "Auth failed"}},
        )
        assert et == "error"
        assert "Auth failed" in msg

    def test_unknown_type(self):
        et, msg, _ = ClaudeCodeAdapter._classify_event(
            {"type": "some_new_type", "data": "stuff"},
        )
        assert et == "some_new_type"

    def test_empty_type(self):
        et, msg, payload = ClaudeCodeAdapter._classify_event({"data": "no type"})
        assert et is None


# ═══════════════════════════════════════════════════════════════════
# 6. Prompt building
# ═══════════════════════════════════════════════════════════════════

class TestBuildPrompt:

    def test_includes_title(self):
        prompt = ClaudeCodeAdapter._build_prompt({"title": "Fix bug", "description": ""})
        assert "Fix bug" in prompt

    def test_includes_description(self):
        prompt = ClaudeCodeAdapter._build_prompt({"title": "", "description": "Detailed desc"})
        assert "Detailed desc" in prompt

    def test_includes_notes(self):
        prompt = ClaudeCodeAdapter._build_prompt({"title": "T", "notes": "Extra info"})
        assert "Extra info" in prompt

    def test_empty_task_fallback(self):
        prompt = ClaudeCodeAdapter._build_prompt({})
        assert "Complete the assigned task" in prompt
