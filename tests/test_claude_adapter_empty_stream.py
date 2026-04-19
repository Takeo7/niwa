"""Tests for FIX-20260419 — Bug 33: empty-stream exit-0 credential error.

Problem: when the Claude CLI has expired / invalid credentials
(setup_token, OAuth or ``~/.claude/.credentials.json``), it exits 0
with an empty stream (not even ``system_init``), and the adapter used
to fall through to ``outcome='success'`` — the task showed as
completed without any artefact.

Fix: in ``_execute``, when ``exit_code == 0`` and the stream carries
no informative event (i.e. zero events, or only a bare
``system_init``) and stderr is empty, classify the run as
``needs_clarification`` with ``error_code='empty_stream_exit_0'``.
The run transitions to ``waiting_input`` (via
``runs_service.finish_run`` mapping) and the UI shows a "revisa
credenciales Claude" hint.

Run: pytest tests/test_claude_adapter_empty_stream.py -v
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import uuid
from unittest.mock import MagicMock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

SCHEMA_PATH = os.path.join(ROOT_DIR, "niwa-app", "db", "schema.sql")

import runs_service  # noqa: E402
from backend_adapters.claude_code import ClaudeCodeAdapter  # noqa: E402


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


def _mock_popen(stream_lines, returncode=0, stderr=b""):
    stream = (
        "\n".join(json.dumps(m) for m in stream_lines) + "\n"
        if stream_lines else ""
    )
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdout = iter(stream.encode("utf-8").splitlines(keepends=True))
    proc.stderr = MagicMock()
    proc.stderr.read.return_value = stderr
    proc.returncode = returncode
    proc.wait.return_value = returncode
    proc.pid = 12345
    return proc


class _AdapterCase:
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

    def _run(self):
        return runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            backend_kind="claude_code", runtime_kind="cli",
        )

    def _start(self, stream, *, task_source="niwa-app",
               returncode=0, stderr=b""):
        task = {
            "id": self.task_id,
            "title": "T",
            "source": task_source,
        }
        with patch("subprocess.Popen") as pop:
            pop.return_value = _mock_popen(
                stream, returncode=returncode, stderr=stderr,
            )
            return self.adapter.start(
                task, self._run(),
                {"default_model": "claude-sonnet-4-6"}, {},
            )

    def _last_run_id(self):
        row = self.conn.execute(
            "SELECT id FROM backend_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return row["id"]


# ═══════════════════════════════════════════════════════════════════
# 1. Empty stream + exit 0 → credential_error
# ═══════════════════════════════════════════════════════════════════


class TestEmptyStreamCredentialError(_AdapterCase):

    def test_empty_stream_exit_0_is_credential_error(self):
        """The canonical Bug 33 case: caduced credentials → CLI emits
        zero events, zero stderr, exit 0. Must NOT be marked as done."""
        result = self._start([], task_source="niwa-app")
        assert result["outcome"] == "needs_clarification"
        assert result["status"] == "needs_clarification"
        assert result["error_code"] == "empty_stream_exit_0"
        assert "credencial" in (result.get("result_text") or "").lower()

    def test_empty_stream_run_transitions_to_waiting_input(self):
        """The run row must land in ``status=waiting_input`` so the
        executor routes the task to waiting_input (not hecha)."""
        self._start([], task_source="niwa-app")
        row = self.conn.execute(
            "SELECT status, error_code, outcome FROM backend_runs "
            "WHERE id = ?",
            (self._last_run_id(),),
        ).fetchone()
        assert row["status"] == "waiting_input"
        assert row["error_code"] == "empty_stream_exit_0"
        assert row["outcome"] == "needs_clarification"

    def test_empty_stream_persists_error_event(self):
        """A ``backend_run_events`` row of type ``error`` must carry a
        hint pointing at credentials, with a structured payload."""
        self._start([], task_source="niwa-app")
        run_id = self._last_run_id()
        events = self.conn.execute(
            "SELECT message, payload_json FROM backend_run_events "
            "WHERE backend_run_id = ? AND event_type = 'error'",
            (run_id,),
        ).fetchall()
        assert events, "empty-stream event must be recorded"
        payloads = [
            json.loads(e["payload_json"]) for e in events
            if e["payload_json"]
        ]
        assert any(
            p.get("error_code") == "empty_stream_exit_0" for p in payloads
        )


# ═══════════════════════════════════════════════════════════════════
# 2. Only system_init event + exit 0 → still credential_error
# ═══════════════════════════════════════════════════════════════════


class TestOnlySystemInitIsCredentialError(_AdapterCase):

    def test_only_system_init_is_credential_error(self):
        """Observed variant of Bug 33: the CLI emits a bare
        ``system_init`` frame and exits 0 without any assistant /
        result event. Treat as credential error too."""
        stream = [
            {"type": "system", "subtype": "init",
             "session_id": "s1", "tools": ["Read"]},
        ]
        result = self._start(stream, task_source="niwa-app")
        assert result["outcome"] == "needs_clarification"
        assert result["error_code"] == "empty_stream_exit_0"


# ═══════════════════════════════════════════════════════════════════
# 3. Functional stream → still succeeded (guard)
# ═══════════════════════════════════════════════════════════════════


class TestFunctionalStreamStillSucceeds(_AdapterCase):

    def test_stream_with_tool_use_and_result_still_succeeds(self):
        """Guard against the new rule swallowing legitimate runs."""
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "tool_use", "name": "Write",
             "input": {"file_path": "/tmp/x.txt"}},
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
        result = self._start(stream, task_source="niwa-app")
        assert result["outcome"] == "success"
        assert result["status"] == "succeeded"


# ═══════════════════════════════════════════════════════════════════
# 4. Non-zero exit still wins — empty-stream rule only fires on exit 0
# ═══════════════════════════════════════════════════════════════════


class TestNonZeroExitNotReclassified(_AdapterCase):

    def test_empty_stream_with_nonzero_exit_stays_failure(self):
        """If the CLI crashed (exit != 0) and stream is empty, the
        existing ``failure`` path must still win. Credentials error is
        a subset of exit 0."""
        result = self._start(
            [], task_source="niwa-app",
            returncode=1, stderr=b"boom",
        )
        assert result["outcome"] == "failure"
        assert result["status"] == "failed"
        # error_code for generic failures is left as None by the
        # existing adapter (no reclassification here).
