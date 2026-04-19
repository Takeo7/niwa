"""FIX-20260420 — evidence-based completion decision table.

One test per row of the decision table defined in the brief
(docs/plans/FIX-20260420-completion-truth-and-roundtrip.md §Principio
de diseño del fix):

  row  stream events          fs diff         exit    outcome
  ────────────────────────────────────────────────────────────────────
   1   ≥1 tool_use (success)  any             0       succeeded
   2   0 tool_use, non-empty  diff ≠ ∅         0       succeeded (Bug 35)
   3a  0 tool_use, non-empty  diff = ∅ + `?`   0       needs_clarification
   3b  0 tool_use, non-empty  diff = ∅ (no `?`) 0       needs_clarification
   4   stream empty           any             0       credential_error
   5   permission_denials≥1   any             0       failed (permission_denied)
   6   is_error=true          any             0       failed (execution_error)
   7   any                    any             ≠ 0     failed (exit_<N>)
   8   ≥3 nested tool_use     diff ≠ ∅         0       succeeded  (stream fixture bug35)

Row 8 is the gold-standard test against ``claude_stream_bug35.jsonl``.

Run: pytest tests/test_claude_adapter_completion.py -v
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
FIXTURE_PATH = os.path.join(
    ROOT_DIR, "tests", "fixtures", "claude_stream_bug35.jsonl",
)

import runs_service  # noqa: E402
from backend_adapters.claude_code import ClaudeCodeAdapter  # noqa: E402


def _make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(open(SCHEMA_PATH).read())
    return fd, path, conn


def _seed(conn, project_directory: str | None = None):
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


def _mock_popen(stream_lines, returncode=0, writes: list[tuple[str, str]] | None = None,
                project_directory: str | None = None):
    """Return a MagicMock Popen that emits *stream_lines* as the CLI
    would, and side-effects *writes* into ``project_directory`` just
    before the process "exits" — so a post-exit filesystem snapshot
    picks them up.
    """
    stream = "\n".join(json.dumps(m) for m in stream_lines) + "\n"
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdout = iter(stream.encode("utf-8").splitlines(keepends=True))
    proc.stderr = MagicMock()
    proc.stderr.read.return_value = b""
    proc.returncode = returncode
    proc.pid = 12345

    def _wait(timeout=None):  # noqa: ARG001
        if writes and project_directory:
            for name, content in writes:
                p = Path(project_directory) / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
        return returncode

    proc.wait.side_effect = _wait
    return proc


class _AdapterCase:
    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.tmpdir = tempfile.mkdtemp(prefix="niwa-project-")
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
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _new_run(self):
        return runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            backend_kind="claude_code", runtime_kind="cli",
        )

    def _start(self, stream, *, task_source="niwa-app",
               project_directory: str | None = None,
               writes: list[tuple[str, str]] | None = None,
               returncode=0,
               stderr_bytes: bytes = b""):
        task = {
            "id": self.task_id,
            "title": "T",
            "source": task_source,
            "project_directory": project_directory,
        }
        pop = _mock_popen(
            stream, returncode=returncode,
            writes=writes, project_directory=project_directory,
        )
        pop.stderr.read.return_value = stderr_bytes
        with patch("subprocess.Popen") as mocked:
            mocked.return_value = pop
            return self.adapter.start(
                task, self._new_run(),
                {"default_model": "claude-sonnet-4-6"}, {},
            )


# ═══════════════════════════════════════════════════════════════════
# Row 1: happy path — top-level tool_use + clean result
# ═══════════════════════════════════════════════════════════════════


class TestRow1_HappyPathWithTools(_AdapterCase):

    def test_toplevel_tool_use_succeeds(self):
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "tool_use", "name": "Write",
             "input": {"file_path": "x.txt"}},
            {"type": "tool_result", "content": "ok"},
            {"type": "result", "session_id": "s1",
             "result": "Done.", "stop_reason": "end_turn",
             "is_error": False, "permission_denials": []},
        ]
        result = self._start(stream)
        assert result["outcome"] == "success"
        assert result["status"] == "succeeded"
        assert result["tool_use_count"] == 1


# ═══════════════════════════════════════════════════════════════════
# Row 2: 0 tool_use, diff ≠ ∅ → succeeded (Bug 35 salvage)
# ═══════════════════════════════════════════════════════════════════


class TestRow2_FilesystemEvidenceSalvagesSuccess(_AdapterCase):

    def test_no_counted_tools_but_files_written_succeeds(self):
        # Stream has no `tool_use` events the parser can see — but the
        # fake process writes a file on disk just before exit. The
        # filesystem diff has to drive the decision.
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "assistant",
             "message": {"content": [
                 {"type": "text", "text": "Writing the file now."},
             ]}},
            {"type": "result", "session_id": "s1",
             "result": "index.html has been created.",
             "stop_reason": "end_turn",
             "is_error": False, "permission_denials": []},
        ]
        result = self._start(
            stream,
            project_directory=self.tmpdir,
            writes=[("index.html", "<html/>")],
        )
        assert result["outcome"] == "success", (
            "filesystem diff must salvage success when tool_use_count==0"
        )
        assert result["tool_use_count"] == 0

        # Verify the diff was persisted as artifacts with the new types.
        rows = self.conn.execute(
            "SELECT artifact_type, path FROM artifacts "
            "WHERE backend_run_id IN "
            "(SELECT id FROM backend_runs WHERE task_id=?)",
            (self.task_id,),
        ).fetchall()
        added = [r for r in rows if r["artifact_type"] == "added"]
        assert any(r["path"] == "index.html" for r in added)

    def test_completion_by_fs_diff_event_recorded(self):
        """Operator-visible trail when we salvage via the filesystem
        diff — so a future regression in the parser is diagnosable."""
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "assistant",
             "message": {"content": [
                 {"type": "text", "text": "Writing."},
             ]}},
            {"type": "result", "session_id": "s1",
             "result": "done", "stop_reason": "end_turn",
             "is_error": False, "permission_denials": []},
        ]
        self._start(
            stream,
            project_directory=self.tmpdir,
            writes=[("a.txt", "hello")],
        )
        row = self.conn.execute(
            "SELECT message FROM backend_run_events "
            "WHERE event_type='completion_by_fs_diff'",
        ).fetchone()
        assert row is not None, "salvage event must be recorded"
        assert "added=1" in row["message"]


# ═══════════════════════════════════════════════════════════════════
# Row 3a/3b: 0 tool_use + diff ∅ → needs_clarification
# ═══════════════════════════════════════════════════════════════════


class TestRow3_ClarificationPaths(_AdapterCase):

    def test_no_tools_empty_diff_with_question_is_clarification(self):
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "assistant",
             "message": {"content": [
                 {"type": "text", "text": "¿Qué stack prefieres?"}]}},
            {"type": "result", "session_id": "s1",
             "result": "¿Qué stack prefieres, Node o Python?",
             "stop_reason": "end_turn",
             "is_error": False, "permission_denials": []},
        ]
        result = self._start(stream, project_directory=self.tmpdir)
        assert result["outcome"] == "needs_clarification"
        assert result["error_code"] == "clarification_required"
        assert result["tool_use_count"] == 0

    def test_no_tools_empty_diff_without_question_still_clarification(self):
        """Post-Bug-32 case kept as needs_input even without trailing '?'."""
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "assistant",
             "message": {"content": [
                 {"type": "text", "text": "Aquí tienes un análisis."}]}},
            {"type": "result", "session_id": "s1",
             "result": "Aquí tienes un análisis.",
             "stop_reason": "end_turn",
             "is_error": False, "permission_denials": []},
        ]
        result = self._start(stream, project_directory=self.tmpdir)
        assert result["outcome"] == "needs_clarification"
        assert result["error_code"] == "clarification_required"


# ═══════════════════════════════════════════════════════════════════
# Row 4: empty stream + exit 0 → credential error
# ═══════════════════════════════════════════════════════════════════


class TestRow4_EmptyStream(_AdapterCase):

    def test_empty_stream_routes_to_empty_stream_exit_0(self):
        result = self._start([], project_directory=self.tmpdir)
        assert result["outcome"] == "needs_clarification"
        assert result["error_code"] == "empty_stream_exit_0"

    def test_only_system_event_routes_to_empty_stream_exit_0(self):
        stream = [{"type": "system", "subtype": "init", "session_id": "s1"}]
        result = self._start(stream, project_directory=self.tmpdir)
        assert result["error_code"] == "empty_stream_exit_0"


# ═══════════════════════════════════════════════════════════════════
# Row 5: permission_denials ≥ 1 → failed(permission_denied)
# ═══════════════════════════════════════════════════════════════════


class TestRow5_PermissionDenied(_AdapterCase):

    def test_permission_denials_override_everything(self):
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "result", "session_id": "s1",
             "result": "blocked", "stop_reason": "end_turn",
             "is_error": False,
             "permission_denials": [{"tool": "Write"}]},
        ]
        result = self._start(stream, project_directory=self.tmpdir)
        assert result["outcome"] == "failure"
        assert result["error_code"] == "permission_denied"


# ═══════════════════════════════════════════════════════════════════
# Row 6: is_error=true → failed(execution_error)
# ═══════════════════════════════════════════════════════════════════


class TestRow6_IsError(_AdapterCase):

    def test_is_error_routes_to_execution_error(self):
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "result", "session_id": "s1",
             "result": "boom", "stop_reason": "end_turn",
             "is_error": True, "permission_denials": []},
        ]
        result = self._start(stream, project_directory=self.tmpdir)
        assert result["outcome"] == "failure"
        assert result["error_code"] == "execution_error"


# ═══════════════════════════════════════════════════════════════════
# Row 7: exit code ≠ 0 → failed
# ═══════════════════════════════════════════════════════════════════


class TestRow7_NonZeroExit(_AdapterCase):

    def test_nonzero_exit_is_failure_regardless_of_stream(self):
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "tool_use", "name": "Write",
             "input": {"file_path": "x"}},
            {"type": "result", "session_id": "s1",
             "result": "partial", "stop_reason": "end_turn",
             "is_error": False, "permission_denials": []},
        ]
        result = self._start(
            stream,
            project_directory=self.tmpdir,
            returncode=2,
            stderr_bytes=b"network error",
        )
        assert result["outcome"] == "failure"
        assert result["exit_code"] == 2


# ═══════════════════════════════════════════════════════════════════
# Row 8 (gold): stream-json fixture with nested tool_use + diff
# ═══════════════════════════════════════════════════════════════════


class TestRow8_NestedToolUseFixture(_AdapterCase):
    """Exercise the exact shape that produced Bug 35 in production.

    The fixture ``claude_stream_bug35.jsonl`` emits three Write
    invocations inside ``assistant.message.content[].type=='tool_use'``
    blocks. Paired with a filesystem diff that reflects those writes,
    the decision table must return ``succeeded`` — pre-FIX this came
    back as ``clarification_required`` because the counter saw zero
    top-level tool_use events.
    """

    def test_fixture_yields_succeeded_with_three_tool_uses(self):
        with open(FIXTURE_PATH, encoding="utf-8") as fh:
            stream = [json.loads(line) for line in fh if line.strip()]

        writes = [
            ("index.html", "<html/>"),
            ("style.css", "body{}"),
            ("app.js", "console.log(1)"),
        ]
        result = self._start(
            stream,
            project_directory=self.tmpdir,
            writes=writes,
        )
        assert result["outcome"] == "success"
        assert result["status"] == "succeeded"
        assert result["tool_use_count"] == 3, (
            "parser must count nested tool_use blocks inside "
            "assistant.message.content[]"
        )

        # Filesystem diff registered as artifacts with new types.
        rows = self.conn.execute(
            "SELECT artifact_type, path FROM artifacts "
            "WHERE backend_run_id IN "
            "(SELECT id FROM backend_runs WHERE task_id=?) "
            "ORDER BY path",
            (self.task_id,),
        ).fetchall()
        added_paths = sorted(
            r["path"] for r in rows if r["artifact_type"] == "added"
        )
        assert added_paths == ["app.js", "index.html", "style.css"]

    def test_chat_source_with_zero_tools_is_still_success(self):
        """Regression guard for PR-B1: chat tasks that answer without
        tools stay as success even when the diff is empty."""
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "assistant",
             "message": {"content": [
                 {"type": "text", "text": "París."}]}},
            {"type": "result", "session_id": "s1",
             "result": "París.",
             "stop_reason": "end_turn",
             "is_error": False, "permission_denials": []},
        ]
        result = self._start(
            stream, task_source="chat", project_directory=self.tmpdir,
        )
        assert result["outcome"] == "success"
        assert result["tool_use_count"] == 0
