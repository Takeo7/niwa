"""Unit tests for CodexAdapter.start() — PR-07 Niwa v0.2.

Mocks subprocess.Popen to test the adapter's start() logic without
a real Codex binary.  Verifies state transitions, event recording,
session handle extraction, approval gate, and error handling.
"""

import json
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
from backend_adapters.codex import CodexAdapter, CODEX_CLI_COMMAND


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
        "created_at, updated_at) VALUES (?, 'Test task', 'Do something', "
        "'proyecto', 'en_progreso', 'media', ?, ?)",
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


def _fake_stream_lines(events):
    """Build bytes iterator simulating subprocess stdout."""
    for event in events:
        yield (json.dumps(event) + "\n").encode()


def _mock_popen(events, exit_code=0):
    """Create a mock Popen with the given events and exit code."""
    proc = mock.MagicMock()
    proc.pid = 12345
    proc.stdin = mock.MagicMock()
    proc.stderr = mock.MagicMock()
    proc.stderr.read.return_value = b""
    proc.stdout = _fake_stream_lines(events)
    proc.poll.return_value = None
    proc.wait.return_value = exit_code
    proc.returncode = exit_code
    return proc


# ── Test class ────────────────────────────────────────────────────

class TestCodexAdapterStart:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id = _seed(self.conn)
        self.adapter = CodexAdapter(db_conn_factory=_db_factory(self.db_path))
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_run(self, artifact_root=None):
        return runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            backend_kind="codex", runtime_kind="cli",
            artifact_root=artifact_root or self.tmpdir,
        )

    def _task(self):
        return {"id": self.task_id, "title": "Test task",
                "description": "Do something"}

    def _profile(self):
        return {"default_model": "o4-mini"}

    # ── Happy path ────────────────────────────────────────────────

    @mock.patch("subprocess.Popen")
    def test_start_success_transitions(self, mock_popen_cls):
        events = [
            {"type": "status", "status": "started",
             "session_id": "codex-s1"},
            {"type": "message", "role": "assistant",
             "content": "Working..."},
            {"type": "result", "status": "completed",
             "session_id": "codex-s1", "model": "o4-mini",
             "cost_usd": 0.01,
             "usage": {"prompt_tokens": 100,
                       "completion_tokens": 50,
                       "total_tokens": 150}},
        ]
        mock_popen_cls.return_value = _mock_popen(events, exit_code=0)

        run = self._make_run()
        result = self.adapter.start(self._task(), run,
                                    self._profile(), {})

        assert result["status"] == "succeeded"
        assert result["outcome"] == "success"
        assert result["exit_code"] == 0
        assert result["session_handle"] == "codex-s1"

    @mock.patch("subprocess.Popen")
    def test_start_records_events(self, mock_popen_cls):
        events = [
            {"type": "status", "status": "started",
             "session_id": "codex-s1"},
            {"type": "command", "name": "shell",
             "command": "echo done"},
            {"type": "command_output", "output": "done",
             "exit_code": 0},
            {"type": "result", "model": "o4-mini",
             "usage": {"total_tokens": 10}},
        ]
        mock_popen_cls.return_value = _mock_popen(events, exit_code=0)

        run = self._make_run()
        self.adapter.start(self._task(), run, self._profile(), {})

        db_events = self.conn.execute(
            "SELECT event_type FROM backend_run_events "
            "WHERE backend_run_id = ? ORDER BY created_at",
            (run["id"],),
        ).fetchall()
        types = [e["event_type"] for e in db_events]
        assert "system_init" in types
        assert "tool_use" in types
        assert "tool_result" in types
        assert "result" in types

    @mock.patch("subprocess.Popen")
    def test_start_persists_session_handle(self, mock_popen_cls):
        events = [
            {"type": "status", "session_id": "my-sess"},
            {"type": "result", "usage": {}},
        ]
        mock_popen_cls.return_value = _mock_popen(events, exit_code=0)

        run = self._make_run()
        self.adapter.start(self._task(), run, self._profile(), {})

        db_run = self.conn.execute(
            "SELECT session_handle FROM backend_runs WHERE id = ?",
            (run["id"],),
        ).fetchone()
        assert db_run["session_handle"] == "my-sess"

    @mock.patch("subprocess.Popen")
    def test_start_persists_usage_signals(self, mock_popen_cls):
        events = [
            {"type": "result", "model": "o4-mini",
             "cost_usd": 0.02, "duration_ms": 1500,
             "usage": {"prompt_tokens": 200,
                       "completion_tokens": 100,
                       "total_tokens": 300}},
        ]
        mock_popen_cls.return_value = _mock_popen(events, exit_code=0)

        run = self._make_run()
        result = self.adapter.start(self._task(), run,
                                    self._profile(), {})

        assert result["usage"]["input_tokens"] == 200
        assert result["usage"]["output_tokens"] == 100
        assert result["usage"]["total_tokens"] == 300

        db_run = self.conn.execute(
            "SELECT observed_usage_signals_json FROM backend_runs "
            "WHERE id = ?", (run["id"],),
        ).fetchone()
        usage = json.loads(db_run["observed_usage_signals_json"])
        assert usage["cost_usd"] == 0.02

    # ── Failure path ──────────────────────────────────────────────

    @mock.patch("subprocess.Popen")
    def test_start_failure_exit_code(self, mock_popen_cls):
        events = [
            {"type": "error", "message": "Something failed"},
        ]
        proc = _mock_popen(events, exit_code=1)
        proc.stderr.read.return_value = b"Codex error output"
        mock_popen_cls.return_value = proc

        run = self._make_run()
        result = self.adapter.start(self._task(), run,
                                    self._profile(), {})

        assert result["status"] == "failed"
        assert result["outcome"] == "failure"
        assert result["exit_code"] == 1

        db_run = self.conn.execute(
            "SELECT status, exit_code FROM backend_runs WHERE id = ?",
            (run["id"],),
        ).fetchone()
        assert db_run["status"] == "failed"
        assert db_run["exit_code"] == 1

    @mock.patch("subprocess.Popen")
    def test_start_exception_marks_failure(self, mock_popen_cls):
        mock_popen_cls.side_effect = OSError("Cannot start process")

        run = self._make_run()
        result = self.adapter.start(self._task(), run,
                                    self._profile(), {})

        assert result["status"] == "failed"
        assert result["error_code"] == "adapter_exception"

    # ── DB required ───────────────────────────────────────────────

    def test_start_without_db_factory_raises(self):
        adapter = CodexAdapter()
        with pytest.raises(RuntimeError, match="db_conn_factory"):
            adapter.start(self._task(), {}, {}, {})

    # ── Command building ──────────────────────────────────────────

    def test_build_command_default(self):
        cmd = CodexAdapter._build_command(model="o4-mini")
        assert cmd == ["codex", "exec", "--json", "--model", "o4-mini"]

    def test_build_command_no_model(self):
        cmd = CodexAdapter._build_command()
        assert cmd == ["codex", "exec", "--json"]

    def test_build_command_custom_template(self):
        cmd = CodexAdapter._build_command(
            model="o4-mini",
            profile={"command_template": "/usr/bin/codex run"},
        )
        assert cmd[0] == "/usr/bin/codex"
        assert "run" in cmd

    def test_command_never_has_dangerous_flag(self):
        cmd = CodexAdapter._build_command(model="o4-mini")
        assert "--dangerously-skip-permissions" not in " ".join(cmd)

    # ── Artifact root ─────────────────────────────────────────────

    @mock.patch("subprocess.Popen")
    def test_artifact_root_created(self, mock_popen_cls):
        events = [{"type": "result", "usage": {}}]
        mock_popen_cls.return_value = _mock_popen(events, exit_code=0)

        art = os.path.join(self.tmpdir, "new_artifacts", "subdir")
        run = self._make_run(artifact_root=art)
        self.adapter.start(self._task(), run, self._profile(), {})

        assert os.path.isdir(art)

    # ── Event classification ──────────────────────────────────────

    def test_classify_status_event(self):
        t, m, p = CodexAdapter._classify_event(
            {"type": "status", "status": "started"})
        assert t == "system_init"

    def test_classify_message_event(self):
        t, m, p = CodexAdapter._classify_event(
            {"type": "message", "role": "assistant",
             "content": "Hello"})
        assert t == "assistant_message"
        assert "Hello" in m

    def test_classify_command_event(self):
        t, m, p = CodexAdapter._classify_event(
            {"type": "command", "name": "shell",
             "command": "echo hi"})
        assert t == "tool_use"
        assert "shell" in m

    def test_classify_command_output(self):
        t, m, p = CodexAdapter._classify_event(
            {"type": "command_output", "output": "hi",
             "exit_code": 0})
        assert t == "tool_result"
        assert "hi" in m

    def test_classify_result_event(self):
        t, m, p = CodexAdapter._classify_event(
            {"type": "result", "cost_usd": 0.01})
        assert t == "result"

    def test_classify_error_event(self):
        t, m, p = CodexAdapter._classify_event(
            {"type": "error", "message": "fail"})
        assert t == "error"
        assert "fail" in m

    def test_classify_unknown_type(self):
        t, m, p = CodexAdapter._classify_event(
            {"type": "custom_thing", "data": 42})
        assert t == "custom_thing"

    def test_classify_no_type(self):
        t, m, p = CodexAdapter._classify_event({"data": 42})
        assert t is None

    # ── Normalize for runtime check ──────────────────────────────

    def test_normalize_command_to_tool_use(self):
        result = CodexAdapter._normalize_for_runtime_check(
            {"type": "command", "name": "shell",
             "command": "rm -rf /"})
        assert result["type"] == "tool_use"
        assert result["name"] == "Bash"
        assert result["input"]["command"] == "rm -rf /"

    def test_normalize_non_command_returns_none(self):
        assert CodexAdapter._normalize_for_runtime_check(
            {"type": "message"}) is None
        assert CodexAdapter._normalize_for_runtime_check(
            {"type": "result"}) is None
