"""Tests for PR-B2 — Bug 34 fix.

Two invariants enforced by the adapter:

1. ``project_directory`` is a hard contract: when it is set on a task,
   the subprocess ``cwd`` MUST be that path. Missing dirs are created;
   no silent fallback to ``os.getcwd()``.
2. Post-run, if the stream recorded any ``tool_use`` Write/Edit/…
   whose ``file_path`` resolves outside ``cwd``, the run is degraded
   from ``success`` to ``needs_clarification`` with
   ``error_code='artifacts_outside_cwd'``. The operator then sees the
   list of offending paths and can decide whether to re-dispatch.

Run: pytest tests/test_claude_adapter_cwd_enforcement.py -v
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

SCHEMA_PATH = os.path.join(ROOT_DIR, "niwa-app", "db", "schema.sql")

import runs_service  # noqa: E402
from backend_adapters.claude_code import ClaudeCodeAdapter  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────


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
        "INSERT INTO tasks (id, title, area, status, priority, "
        "created_at, updated_at) VALUES (?, 'T', 'proyecto', "
        "'en_progreso', 'media', ?, ?)",
        (task_id, now, now),
    )
    conn.execute(
        "INSERT INTO backend_profiles (id, slug, display_name, "
        "backend_kind, runtime_kind, default_model, enabled, priority, "
        "created_at, updated_at) VALUES (?, 'claude_code', 'C', "
        "'claude_code', 'cli', 'claude-sonnet-4-6', 1, 10, ?, ?)",
        (profile_id, now, now),
    )
    conn.execute(
        "INSERT INTO routing_decisions (id, task_id, decision_index, "
        "selected_profile_id, created_at) VALUES (?, ?, 0, ?, ?)",
        (rd_id, task_id, profile_id, now),
    )
    conn.commit()
    return task_id, profile_id, rd_id


def _mock_popen(stream_lines, returncode=0):
    stream = "\n".join(json.dumps(m) for m in stream_lines) + "\n"
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdout = iter(stream.encode("utf-8").splitlines(keepends=True))
    proc.stderr = MagicMock()
    proc.stderr.read.return_value = b""
    proc.returncode = returncode
    proc.wait.return_value = returncode
    proc.pid = 12345
    return proc


# ── _resolve_cwd ─────────────────────────────────────────────────────


class TestResolveCwd:
    """Invariant 1: project_directory is the cwd, always."""

    def test_creates_missing_project_directory(self, tmp_path):
        target = tmp_path / "nested" / "projects" / "does-not-exist"
        assert not target.exists()
        task = {"project_directory": str(target)}

        resolved = ClaudeCodeAdapter._resolve_cwd(
            task, artifact_root=None,
        )

        assert resolved == str(target)
        assert target.is_dir()

    def test_uses_existing_project_directory(self, tmp_path):
        target = tmp_path / "already-there"
        target.mkdir()
        task = {"project_directory": str(target)}

        resolved = ClaudeCodeAdapter._resolve_cwd(
            task, artifact_root=None,
        )

        assert resolved == str(target)

    def test_no_project_directory_uses_artifact_root(self, tmp_path):
        artifact = tmp_path / "artifacts"
        artifact.mkdir()
        task = {}

        resolved = ClaudeCodeAdapter._resolve_cwd(
            task, artifact_root=str(artifact),
        )

        assert resolved == str(artifact)

    def test_no_project_no_artifact_falls_back_to_getcwd(self):
        resolved = ClaudeCodeAdapter._resolve_cwd({}, artifact_root=None)
        assert resolved == os.getcwd()


# ── Post-run artifact validation ─────────────────────────────────────


class _AdapterCase:
    """Shared setup — one db per test, fresh adapter."""

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id = _seed(self.conn)
        self.tmpdir = tempfile.mkdtemp(prefix="niwa-cwd-test-")
        self.project_dir = os.path.join(self.tmpdir, "proj")
        os.makedirs(self.project_dir, exist_ok=True)

        def _factory():
            c = sqlite3.connect(self.db_path, timeout=10)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys=ON")
            return c

        self.adapter = ClaudeCodeAdapter(db_conn_factory=_factory)

    def teardown_method(self):
        import shutil
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self):
        return runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            backend_kind="claude_code", runtime_kind="cli",
        )

    def _start(self, stream, task_source="niwa-app", returncode=0,
               project_directory=None):
        task = {
            "id": self.task_id,
            "title": "T",
            "source": task_source,
            "project_directory": project_directory or self.project_dir,
        }
        with patch("subprocess.Popen") as pop:
            pop.return_value = _mock_popen(stream, returncode=returncode)
            result = self.adapter.start(
                task, self._run(),
                {"default_model": "claude-sonnet-4-6"}, {},
            )
            return result, pop


class TestCwdInPopen(_AdapterCase):
    """Guard: Popen is called with cwd=project_directory."""

    def test_popen_cwd_is_project_directory(self):
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {
                "type": "result",
                "session_id": "s1",
                "result": "Done.",
                "stop_reason": "end_turn",
                "is_error": False,
                "permission_denials": [],
            },
        ]
        # Exec path needs at least one tool_use to avoid the Bug 32
        # zero-tool clarification filter (which would preempt this
        # test's signal). We inject a Write inside cwd.
        stream.insert(1, {
            "type": "tool_use", "name": "Write",
            "input": {
                "file_path": os.path.join(self.project_dir, "a.txt"),
                "content": "x",
            },
        })
        _, pop = self._start(stream)
        kwargs = pop.call_args.kwargs
        assert kwargs["cwd"] == self.project_dir


class TestWritesInsideCwd(_AdapterCase):
    """Writes inside cwd → run stays succeeded."""

    def test_absolute_write_inside_cwd_stays_success(self):
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {
                "type": "tool_use", "name": "Write",
                "input": {
                    "file_path": os.path.join(self.project_dir, "index.html"),
                    "content": "<h1>hi</h1>",
                },
            },
            {"type": "tool_result", "content": "ok"},
            {
                "type": "result",
                "session_id": "s1",
                "result": "Wrote index.html",
                "stop_reason": "end_turn",
                "is_error": False,
                "permission_denials": [],
            },
        ]
        result, _ = self._start(stream)
        assert result["outcome"] == "success"
        assert result["status"] == "succeeded"
        assert result["error_code"] is None

    def test_relative_write_is_safe(self):
        """Relative paths resolve to cwd — never trigger the gate."""
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {
                "type": "tool_use", "name": "Write",
                "input": {
                    "file_path": "README.md",
                    "content": "# Project",
                },
            },
            {"type": "tool_result", "content": "ok"},
            {
                "type": "result",
                "session_id": "s1",
                "result": "Wrote README.",
                "stop_reason": "end_turn",
                "is_error": False,
                "permission_denials": [],
            },
        ]
        result, _ = self._start(stream)
        assert result["outcome"] == "success"
        assert result["status"] == "succeeded"


class TestWritesOutsideCwd(_AdapterCase):
    """Writes outside cwd → needs_clarification / artifacts_outside_cwd."""

    def test_absolute_write_outside_cwd_triggers_clarification(self):
        """Bug 34 reproducer: Claude writes to /tmp/<slug>/index.html
        instead of project_directory."""
        offending = "/tmp/test-mirror/index.html"
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {
                "type": "tool_use", "name": "Write",
                "input": {"file_path": offending, "content": "x"},
            },
            {"type": "tool_result", "content": "ok"},
            {
                "type": "result",
                "session_id": "s1",
                "result": "Wrote the file.",
                "stop_reason": "end_turn",
                "is_error": False,
                "permission_denials": [],
            },
        ]
        result, _ = self._start(stream)
        assert result["outcome"] == "needs_clarification"
        assert result["status"] == "needs_clarification"
        assert result["error_code"] == "artifacts_outside_cwd"
        assert offending in result["result_text"]

        # Run row persisted with status='waiting_input' and an event
        # that carries the offending paths in payload_json.
        run_row = self.conn.execute(
            "SELECT status FROM backend_runs WHERE task_id=?",
            (self.task_id,),
        ).fetchone()
        assert run_row["status"] == "waiting_input"

        ev = self.conn.execute(
            "SELECT payload_json FROM backend_run_events "
            "WHERE event_type='error' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        assert ev is not None
        payload = json.loads(ev["payload_json"])
        assert payload["error_code"] == "artifacts_outside_cwd"
        assert offending in payload["offending_paths"]
        assert payload["cwd"] == self.project_dir

    def test_edit_outside_cwd_triggers_clarification(self):
        offending = "/etc/hosts"
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {
                "type": "tool_use", "name": "Edit",
                "input": {
                    "file_path": offending,
                    "old_string": "a", "new_string": "b",
                },
            },
            {"type": "tool_result", "content": "ok"},
            {
                "type": "result",
                "session_id": "s1",
                "result": "Edited.",
                "stop_reason": "end_turn",
                "is_error": False,
                "permission_denials": [],
            },
        ]
        result, _ = self._start(stream)
        assert result["outcome"] == "needs_clarification"
        assert result["error_code"] == "artifacts_outside_cwd"

    def test_mixed_writes_reports_only_outsiders(self):
        inside = os.path.join(self.project_dir, "a.txt")
        outside = "/tmp/b.txt"
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "tool_use", "name": "Write",
             "input": {"file_path": inside, "content": "a"}},
            {"type": "tool_result", "content": "ok"},
            {"type": "tool_use", "name": "Write",
             "input": {"file_path": outside, "content": "b"}},
            {"type": "tool_result", "content": "ok"},
            {
                "type": "result",
                "session_id": "s1",
                "result": "Wrote two files.",
                "stop_reason": "end_turn",
                "is_error": False,
                "permission_denials": [],
            },
        ]
        result, _ = self._start(stream)
        assert result["outcome"] == "needs_clarification"
        assert result["error_code"] == "artifacts_outside_cwd"

        ev = self.conn.execute(
            "SELECT payload_json FROM backend_run_events "
            "WHERE event_type='error' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        payload = json.loads(ev["payload_json"])
        assert outside in payload["offending_paths"]
        assert inside not in payload["offending_paths"]


class TestNonWriteToolsAreIgnored(_AdapterCase):
    """Guards: non-Write tools never trigger the gate."""

    def test_bash_command_referencing_tmp_is_ignored(self):
        """A `mkdir /tmp/foo` via Bash does NOT count as an artifact
        write. Out of scope for PR-B2 (documented in brief)."""
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "tool_use", "name": "Bash",
             "input": {"command": "mkdir /tmp/foo"}},
            {"type": "tool_result", "content": ""},
            {"type": "tool_use", "name": "Write",
             "input": {
                 "file_path": os.path.join(self.project_dir, "ok.txt"),
                 "content": "x",
             }},
            {"type": "tool_result", "content": "ok"},
            {
                "type": "result",
                "session_id": "s1",
                "result": "Done.",
                "stop_reason": "end_turn",
                "is_error": False,
                "permission_denials": [],
            },
        ]
        result, _ = self._start(stream)
        assert result["outcome"] == "success"
        assert result["status"] == "succeeded"

    def test_read_tool_outside_cwd_is_ignored(self):
        """Reading `/etc/hostname` is a legitimate Read; only writes
        should trigger the gate."""
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "tool_use", "name": "Read",
             "input": {"file_path": "/etc/hostname"}},
            {"type": "tool_result", "content": "host"},
            {"type": "tool_use", "name": "Write",
             "input": {
                 "file_path": os.path.join(self.project_dir, "note.md"),
                 "content": "host=...",
             }},
            {"type": "tool_result", "content": "ok"},
            {
                "type": "result",
                "session_id": "s1",
                "result": "Done.",
                "stop_reason": "end_turn",
                "is_error": False,
                "permission_denials": [],
            },
        ]
        result, _ = self._start(stream)
        assert result["outcome"] == "success"


class TestErrorsTakePrecedence(_AdapterCase):
    """If the run already failed (permission_denials, is_error), the
    artifact gate must NOT flip it to needs_clarification."""

    def test_permission_denied_wins_over_artifact_gate(self):
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "tool_use", "name": "Write",
             "input": {"file_path": "/tmp/x.txt", "content": "x"}},
            {"type": "tool_result", "content": "denied"},
            {
                "type": "result",
                "session_id": "s1",
                "result": "Blocked.",
                "stop_reason": "end_turn",
                "is_error": False,
                "permission_denials": [{"tool": "Write"}],
            },
        ]
        result, _ = self._start(stream)
        assert result["outcome"] == "failure"
        assert result["error_code"] == "permission_denied"
