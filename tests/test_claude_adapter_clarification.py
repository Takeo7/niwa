"""Tests for Bug 32 fix — false-succeeded detection.

Problem: el adapter marcaba como `succeeded` cualquier run con
`exit_code==0`, `is_error=false` y sin `permission_denials`, incluso
cuando Claude había respondido sólo con texto pidiendo clarificación
(cero `tool_use` events). Eso generaba "tareas hechas" sin trabajo
real.

Fix: si source != 'chat' (tarea ejecutiva) y `tool_use_count == 0` y
`stop_reason == 'end_turn'`, marcar outcome como `needs_clarification`
→ run.status = 'waiting_input', error_code = 'clarification_required'.
El event con el `result_text` de Claude se persiste para la UI.

Run: pytest tests/test_claude_adapter_clarification.py -v
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


class _AdapterCase:
    """Shared setup — one db per test, fresh adapter."""

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

    def _start(self, stream, task_source="niwa-app", returncode=0):
        task = {
            "id": self.task_id,
            "title": "T",
            "source": task_source,
        }
        with patch("subprocess.Popen") as pop:
            pop.return_value = _mock_popen(stream, returncode=returncode)
            return self.adapter.start(
                task, self._run(),
                {"default_model": "claude-sonnet-4-6"}, {},
            )


# ═══════════════════════════════════════════════════════════════════
# 1. Executive task + 0 tool_use + end_turn → needs_clarification
# ═══════════════════════════════════════════════════════════════════


class TestClarificationDetection(_AdapterCase):

    def test_executive_zero_tools_end_turn_needs_clarification(self):
        """El caso canónico: 'Crea un proyecto test-mirror' → Claude
        responde pidiendo info → outcome = needs_clarification."""
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "¿Qué tipo de proyecto?"}
            ]}},
            {
                "type": "result",
                "session_id": "s1",
                "result": "¿Qué tipo de proyecto? Node.js / Python?",
                "stop_reason": "end_turn",
                "is_error": False,
                "permission_denials": [],
                "cost_usd": 0.02,
            },
        ]
        result = self._start(stream, task_source="niwa-app")
        assert result["outcome"] == "needs_clarification"
        assert result["status"] == "needs_clarification"
        assert result["error_code"] == "clarification_required"
        assert result["tool_use_count"] == 0
        assert "Python" in result["result_text"]

    def test_clarification_run_ends_in_waiting_input(self):
        """El run debe transicionar a status=waiting_input (Bug 32 fix
        en runs_service.finish_run)."""
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {
                "type": "result",
                "session_id": "s1",
                "result": "Necesito más info",
                "stop_reason": "end_turn",
                "is_error": False,
                "permission_denials": [],
            },
        ]
        result = self._start(stream, task_source="niwa-app")
        row = self.conn.execute(
            "SELECT status, error_code, outcome FROM backend_runs "
            "WHERE id = ?",
            (result.get("run_id") or self._last_run_id(),),
        ).fetchone()
        assert row["status"] == "waiting_input"
        assert row["error_code"] == "clarification_required"
        assert row["outcome"] == "needs_clarification"

    def _last_run_id(self):
        row = self.conn.execute(
            "SELECT id FROM backend_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return row["id"]

    def test_clarification_persists_result_text_event(self):
        """La pregunta exacta de Claude se guarda como event para que
        la UI pueda mostrarla al usuario."""
        claude_question = "Indica tipo (Node.js|Python) y ruta"
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {
                "type": "result",
                "session_id": "s1",
                "result": claude_question,
                "stop_reason": "end_turn",
                "is_error": False,
                "permission_denials": [],
            },
        ]
        self._start(stream, task_source="niwa-app")
        run_id = self._last_run_id()
        events = self.conn.execute(
            "SELECT message, payload_json FROM backend_run_events "
            "WHERE backend_run_id = ? AND event_type = 'error'",
            (run_id,),
        ).fetchall()
        assert events, "clarification event must be recorded"
        msgs = " ".join(e["message"] or "" for e in events)
        assert claude_question in msgs
        payloads = [json.loads(e["payload_json"]) for e in events
                    if e["payload_json"]]
        assert any(p.get("error_code") == "clarification_required"
                   for p in payloads)


# ═══════════════════════════════════════════════════════════════════
# 2. Chat task: 0 tool_use + end_turn IS legitimate success
# ═══════════════════════════════════════════════════════════════════


class TestChatTaskNoFalsePositive(_AdapterCase):

    def test_chat_zero_tools_end_turn_stays_success(self):
        """Source='chat' → el usuario preguntó algo, Claude respondió.
        Eso es éxito legítimo aunque no haya tool_use."""
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "París es la capital de Francia"}
            ]}},
            {
                "type": "result",
                "session_id": "s1",
                "result": "París es la capital de Francia",
                "stop_reason": "end_turn",
                "is_error": False,
                "permission_denials": [],
            },
        ]
        result = self._start(stream, task_source="chat")
        assert result["outcome"] == "success"
        assert result["status"] == "succeeded"
        assert result["tool_use_count"] == 0


# ═══════════════════════════════════════════════════════════════════
# 3. Executive task with tool_use → succeeded (happy path intact)
# ═══════════════════════════════════════════════════════════════════


class TestHappyPathWithTools(_AdapterCase):

    def test_executive_with_tool_use_succeeds(self):
        """Guard del happy path — una tarea ejecutiva con al menos
        un tool_use debe seguir marcándose como success."""
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "tool_use", "name": "Write",
             "input": {"path": "/tmp/x.txt"}},
            {"type": "tool_result", "content": "ok"},
            {
                "type": "result",
                "session_id": "s1",
                "result": "File written",
                "stop_reason": "end_turn",
                "is_error": False,
                "permission_denials": [],
            },
        ]
        result = self._start(stream, task_source="niwa-app")
        assert result["outcome"] == "success"
        assert result["status"] == "succeeded"
        assert result["tool_use_count"] == 1


# ═══════════════════════════════════════════════════════════════════
# 4. is_error and permission_denied retain priority
# ═══════════════════════════════════════════════════════════════════


class TestErrorPriority(_AdapterCase):

    def test_permission_denied_wins_over_clarification(self):
        """Si hay permission_denials + 0 tool_use, outcome=failure
        (permission_denied), NO clarification_required."""
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {
                "type": "result",
                "session_id": "s1",
                "result": "Blocked",
                "stop_reason": "end_turn",
                "is_error": False,
                "permission_denials": [{"tool": "Write"}],
            },
        ]
        result = self._start(stream, task_source="niwa-app")
        assert result["outcome"] == "failure"
        assert result["error_code"] == "permission_denied"

    def test_is_error_wins_over_clarification(self):
        """Si is_error=true + 0 tool_use, outcome=failure
        (execution_error), NO clarification_required."""
        stream = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {
                "type": "result",
                "session_id": "s1",
                "result": "boom",
                "stop_reason": "end_turn",
                "is_error": True,
                "permission_denials": [],
            },
        ]
        result = self._start(stream, task_source="niwa-app")
        assert result["outcome"] == "failure"
        assert result["error_code"] == "execution_error"
