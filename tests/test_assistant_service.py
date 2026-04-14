"""Tests for assistant_service — PR-08 Niwa v0.2.

Step 1: routing_mode check and error-path persistence.

Run with: pytest tests/test_assistant_service.py -v
"""
import json
import os
import sqlite3
import sys
import tempfile
import urllib.request
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

    def test_routing_mode_v02_reaches_llm(self, monkeypatch):
        """routing_mode='v02' passes the gate and reaches LLM call."""
        pid = _seed_project(self.conn)
        _set_routing_mode(self.conn, "v02")
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            ("svc.llm.anthropic.api_key", "sk-test"),
        )
        self.conn.commit()

        # Fake the LLM to return a simple text response
        def fake_call(*a, **kw):
            return {
                "content": [{"type": "text", "text": "Hola, soy Niwa."}],
                "stop_reason": "end_turn",
            }
        monkeypatch.setattr(assistant_service, "call_anthropic", fake_call)

        result = assistant_service.assistant_turn(
            session_id="sess-3",
            project_id=pid,
            message="hola",
            channel="web",
            conn=self.conn,
        )
        assert "error" not in result
        assert result["assistant_message"] == "Hola, soy Niwa."


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


# ── Tests: LLM config resolution ────────────────────────────────────

class TestLLMConfig:

    def setup_method(self):
        self.fd, self.path, self.conn = _make_db()

    def teardown_method(self):
        self.conn.close()
        os.close(self.fd)
        os.unlink(self.path)

    def test_model_from_agent_assistant(self):
        """agent.assistant setting takes priority."""
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            ("agent.assistant", '{"model": "claude-sonnet-4-6"}'),
        )
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            ("agent.chat", '{"model": "claude-haiku-4-5"}'),
        )
        self.conn.commit()
        model, _ = assistant_service._get_llm_config(self.conn)
        assert model == "claude-sonnet-4-6"

    def test_model_fallback_to_agent_chat(self):
        """No agent.assistant → falls back to agent.chat."""
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            ("agent.chat", '{"model": "claude-haiku-4-5"}'),
        )
        self.conn.commit()
        model, _ = assistant_service._get_llm_config(self.conn)
        assert model == "claude-haiku-4-5"

    def test_model_fallback_to_llm_command_chat(self):
        """No agent.* → parses model from int.llm_command_chat."""
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            ("int.llm_command_chat",
             "claude -p --model claude-opus-4-6 --max-turns 10"),
        )
        self.conn.commit()
        model, _ = assistant_service._get_llm_config(self.conn)
        assert model == "claude-opus-4-6"

    def test_model_fallback_to_default_model_setting(self):
        """No agent.* and no command → uses svc.llm.anthropic.default_model."""
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            ("svc.llm.anthropic.default_model", "claude-sonnet-4-6"),
        )
        self.conn.commit()
        model, _ = assistant_service._get_llm_config(self.conn)
        assert model == "claude-sonnet-4-6"

    def test_model_hardcoded_last_resort(self):
        """No settings at all → hardcoded claude-haiku-4-5."""
        model, _ = assistant_service._get_llm_config(self.conn)
        assert model == "claude-haiku-4-5"

    def test_api_key_from_settings(self):
        """API key read from svc.llm.anthropic.api_key."""
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            ("svc.llm.anthropic.api_key", "sk-ant-test-key"),
        )
        self.conn.commit()
        _, api_key = assistant_service._get_llm_config(self.conn)
        assert api_key == "sk-ant-test-key"

    def test_api_key_from_legacy_setting(self):
        """Falls back to int.llm_api_key."""
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            ("int.llm_api_key", "sk-legacy-key"),
        )
        self.conn.commit()
        _, api_key = assistant_service._get_llm_config(self.conn)
        assert api_key == "sk-legacy-key"

    def test_api_key_from_env(self, monkeypatch):
        """Falls back to ANTHROPIC_API_KEY env var."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-key")
        _, api_key = assistant_service._get_llm_config(self.conn)
        assert api_key == "sk-env-key"

    def test_api_key_empty_when_unconfigured(self, monkeypatch):
        """No key anywhere → empty string."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("NIWA_LLM_API_KEY", raising=False)
        _, api_key = assistant_service._get_llm_config(self.conn)
        assert api_key == ""


# ── Tests: call_anthropic wrapper ────────────────────────────────────

class TestCallAnthropic:
    """Test the HTTP wrapper by intercepting urlopen."""

    def test_sends_correct_payload(self, monkeypatch):
        """Verifies headers, model, tools are sent correctly."""
        captured = {}

        class FakeResponse:
            def __init__(self, body):
                self._body = body
            def read(self):
                return self._body
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.headers)
            captured["body"] = json.loads(req.data.decode())
            captured["timeout"] = timeout
            return FakeResponse(json.dumps({
                "content": [{"type": "text", "text": "hello"}],
                "stop_reason": "end_turn",
            }).encode())

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        result = assistant_service.call_anthropic(
            model="claude-haiku-4-5",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"name": "task_list", "description": "x",
                    "input_schema": {"type": "object", "properties": {}}}],
            system="You are helpful.",
            timeout=10.0,
        )

        assert captured["url"] == "https://api.anthropic.com/v1/messages"
        assert captured["headers"]["X-api-key"] == "sk-test"
        assert captured["headers"]["Anthropic-version"] == "2023-06-01"
        assert captured["body"]["model"] == "claude-haiku-4-5"
        assert captured["body"]["system"] == "You are helpful."
        assert len(captured["body"]["tools"]) == 1
        assert captured["timeout"] == 10.0
        assert result["content"][0]["text"] == "hello"

    def test_no_tools_omits_key(self, monkeypatch):
        """When tools=None, payload has no 'tools' key."""
        captured = {}

        class FakeResponse:
            def read(self):
                return json.dumps({"content": [], "stop_reason": "end_turn"}).encode()
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        def fake_urlopen(req, timeout=None):
            captured["body"] = json.loads(req.data.decode())
            return FakeResponse()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        assistant_service.call_anthropic(
            model="m", api_key="k",
            messages=[{"role": "user", "content": "hi"}],
            tools=None, system="s", timeout=5,
        )
        assert "tools" not in captured["body"]

    def test_timeout_floor_at_one_second(self, monkeypatch):
        """timeout < 1 is clamped to 1."""
        captured = {}

        class FakeResponse:
            def read(self):
                return json.dumps({"content": [], "stop_reason": "end_turn"}).encode()
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        def fake_urlopen(req, timeout=None):
            captured["timeout"] = timeout
            return FakeResponse()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        assistant_service.call_anthropic(
            model="m", api_key="k",
            messages=[{"role": "user", "content": "hi"}],
            tools=None, system="s", timeout=0.3,
        )
        assert captured["timeout"] == 1


# ── Tests: domain tools ──────────────────────────────────────────────

class TestDomainTools:
    """Unit tests for each domain tool function."""

    def setup_method(self):
        self.fd, self.path, self.conn = _make_db()
        self.pid = _seed_project(self.conn)

    def teardown_method(self):
        self.conn.close()
        os.close(self.fd)
        os.unlink(self.path)

    def _insert_task(self, status="pendiente", title="Test task"):
        tid = str(uuid.uuid4())
        now = assistant_service._now_iso()
        self.conn.execute(
            "INSERT INTO tasks (id, title, area, project_id, status, "
            "priority, created_at, updated_at) "
            "VALUES (?, ?, 'proyecto', ?, ?, 'media', ?, ?)",
            (tid, title, self.pid, status, now, now),
        )
        self.conn.commit()
        return tid

    # ── task_list ────────────────────────────────────────────────

    def test_task_list_empty(self):
        r = assistant_service._tool_task_list(self.conn, self.pid, {})
        assert r["count"] == 0
        assert r["tasks"] == []

    def test_task_list_returns_tasks(self):
        self._insert_task()
        self._insert_task()
        r = assistant_service._tool_task_list(self.conn, self.pid, {})
        assert r["count"] == 2

    def test_task_list_filters_by_status(self):
        self._insert_task(status="pendiente")
        self._insert_task(status="en_progreso")
        r = assistant_service._tool_task_list(
            self.conn, self.pid, {"status": "pendiente"},
        )
        assert r["count"] == 1
        assert r["tasks"][0]["status"] == "pendiente"

    # ── task_get ─────────────────────────────────────────────────

    def test_task_get_found(self):
        tid = self._insert_task(title="Hello")
        r = assistant_service._tool_task_get(self.conn, self.pid, {"task_id": tid})
        assert r["title"] == "Hello"

    def test_task_get_not_found(self):
        r = assistant_service._tool_task_get(
            self.conn, self.pid, {"task_id": "nonexistent"},
        )
        assert r["error"] == "task_not_found"

    # ── task_create ──────────────────────────────────────────────

    def test_task_create_success(self):
        r = assistant_service._tool_task_create(
            self.conn, self.pid, {"title": "New task", "priority": "alta"},
        )
        assert "task_id" in r
        assert r["status"] == "pendiente"
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (r["task_id"],),
        ).fetchone()
        assert row["title"] == "New task"
        assert row["priority"] == "alta"
        assert row["project_id"] == self.pid

    def test_task_create_records_event(self):
        r = assistant_service._tool_task_create(
            self.conn, self.pid, {"title": "Evented"},
        )
        evt = self.conn.execute(
            "SELECT * FROM task_events WHERE task_id = ? AND type = 'created'",
            (r["task_id"],),
        ).fetchone()
        assert evt is not None

    def test_task_create_missing_title(self):
        r = assistant_service._tool_task_create(self.conn, self.pid, {})
        assert r["error"] == "title is required"

    # ── task_cancel ──────────────────────────────────────────────

    def test_task_cancel_from_pendiente(self):
        tid = self._insert_task(status="pendiente")
        r = assistant_service._tool_task_cancel(
            self.conn, self.pid, {"task_id": tid},
        )
        assert r["status"] == "archivada"
        row = self.conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (tid,),
        ).fetchone()
        assert row["status"] == "archivada"

    def test_task_cancel_from_terminal_fails(self):
        tid = self._insert_task(status="hecha")
        r = assistant_service._tool_task_cancel(
            self.conn, self.pid, {"task_id": tid},
        )
        assert r["error"] == "cannot_cancel"

    # ── task_resume ──────────────────────────────────────────────

    def test_task_resume_from_bloqueada(self):
        tid = self._insert_task(status="bloqueada")
        r = assistant_service._tool_task_resume(
            self.conn, self.pid, {"task_id": tid},
        )
        assert r["status"] == "pendiente"

    def test_task_resume_from_en_progreso_fails(self):
        tid = self._insert_task(status="en_progreso")
        r = assistant_service._tool_task_resume(
            self.conn, self.pid, {"task_id": tid},
        )
        assert r["error"] == "cannot_resume"

    # ── project_context ──────────────────────────────────────────

    def test_project_context(self):
        self._insert_task(status="pendiente")
        self._insert_task(status="hecha")
        r = assistant_service._tool_project_context(self.conn, self.pid, {})
        assert r["project"]["name"] == "Test Project"
        assert r["task_summary"].get("pendiente", 0) == 1
        assert r["task_summary"].get("hecha", 0) == 1
        assert len(r["recent_tasks"]) == 2


# ── Tests: ID collection helper ──────────────────────────────────────

class TestCollectIds:

    def test_collects_task_ids_from_list(self):
        task_ids, approval_ids, run_ids = set(), set(), set()
        result = {"tasks": [{"id": "t1"}, {"id": "t2"}], "count": 2}
        assistant_service._collect_ids(
            "task_list", result, task_ids, approval_ids, run_ids,
        )
        assert task_ids == {"t1", "t2"}

    def test_collects_task_id_from_create(self):
        task_ids, approval_ids, run_ids = set(), set(), set()
        result = {"task_id": "t1", "status": "pendiente"}
        assistant_service._collect_ids(
            "task_create", result, task_ids, approval_ids, run_ids,
        )
        assert task_ids == {"t1"}

    def test_collects_cancelled_run_ids(self):
        task_ids, approval_ids, run_ids = set(), set(), set()
        result = {"task_id": "t1", "cancelled_run_ids": ["r1", "r2"]}
        assistant_service._collect_ids(
            "task_cancel", result, task_ids, approval_ids, run_ids,
        )
        assert run_ids == {"r1", "r2"}

    def test_collects_approval_ids_from_list(self):
        task_ids, approval_ids, run_ids = set(), set(), set()
        result = {"approvals": [{"id": "a1"}, {"id": "a2"}], "count": 2}
        assistant_service._collect_ids(
            "approval_list", result, task_ids, approval_ids, run_ids,
        )
        assert approval_ids == {"a1", "a2"}

    def test_collects_run_from_tail(self):
        task_ids, approval_ids, run_ids = set(), set(), set()
        result = {"run": {"id": "r1", "status": "running"}, "events": []}
        assistant_service._collect_ids(
            "run_tail", result, task_ids, approval_ids, run_ids,
        )
        assert run_ids == {"r1"}


# ── Tests: full assistant_turn loop (with fake LLM) ──────────────────

def _fake_llm_simple(text):
    """Return a fake call_anthropic that always replies with text."""
    def fake(*a, **kw):
        return {
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
        }
    return fake


def _fake_llm_tool_then_text(tool_name, tool_input, tool_id, final_text):
    """Fake that first calls a tool, then responds with text."""
    call_count = {"n": 0}

    def fake(model, api_key, messages, tools, system, timeout):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {
                "content": [{
                    "type": "tool_use",
                    "id": tool_id,
                    "name": tool_name,
                    "input": tool_input,
                }],
                "stop_reason": "tool_use",
            }
        return {
            "content": [{"type": "text", "text": final_text}],
            "stop_reason": "end_turn",
        }
    return fake


class TestAssistantTurnLoop:

    def setup_method(self):
        self.fd, self.path, self.conn = _make_db()
        self.pid = _seed_project(self.conn)
        _set_routing_mode(self.conn, "v02")
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            ("svc.llm.anthropic.api_key", "sk-test"),
        )
        self.conn.commit()

    def teardown_method(self):
        self.conn.close()
        os.close(self.fd)
        os.unlink(self.path)

    def test_simple_text_response(self, monkeypatch):
        """LLM returns text only — no tool calls."""
        monkeypatch.setattr(
            assistant_service, "call_anthropic",
            _fake_llm_simple("Todo bien."),
        )
        r = assistant_service.assistant_turn(
            session_id="s1", project_id=self.pid,
            message="¿cómo va?", channel="web", conn=self.conn,
        )
        assert r["assistant_message"] == "Todo bien."
        assert r["actions_taken"] == []
        assert r["task_ids"] == []

    def test_tool_call_creates_task(self, monkeypatch):
        """LLM calls task_create, then responds with text."""
        monkeypatch.setattr(
            assistant_service, "call_anthropic",
            _fake_llm_tool_then_text(
                "task_create",
                {"title": "Deploy v2", "priority": "alta"},
                "tu-1",
                "Tarea creada.",
            ),
        )
        r = assistant_service.assistant_turn(
            session_id="s2", project_id=self.pid,
            message="crea una tarea para deploy v2", channel="web",
            conn=self.conn,
        )
        assert r["assistant_message"] == "Tarea creada."
        assert len(r["task_ids"]) == 1
        assert len(r["actions_taken"]) == 1
        assert r["actions_taken"][0]["tool"] == "task_create"

        # Verify task in DB
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (r["task_ids"][0],),
        ).fetchone()
        assert row["title"] == "Deploy v2"
        assert row["priority"] == "alta"

    def test_tool_call_task_list(self, monkeypatch):
        """LLM calls task_list and gets results."""
        # Seed a task
        now = assistant_service._now_iso()
        tid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO tasks (id, title, area, project_id, status, "
            "priority, created_at, updated_at) "
            "VALUES (?, 'Existing', 'proyecto', ?, 'pendiente', 'media', ?, ?)",
            (tid, self.pid, now, now),
        )
        self.conn.commit()

        monkeypatch.setattr(
            assistant_service, "call_anthropic",
            _fake_llm_tool_then_text(
                "task_list", {}, "tu-2", "Hay 1 tarea pendiente.",
            ),
        )
        r = assistant_service.assistant_turn(
            session_id="s3", project_id=self.pid,
            message="lista tareas", channel="web", conn=self.conn,
        )
        assert r["assistant_message"] == "Hay 1 tarea pendiente."
        assert tid in r["task_ids"]

    def test_llm_not_configured_error(self):
        """No API key → llm_not_configured error."""
        self.conn.execute(
            "DELETE FROM settings WHERE key = 'svc.llm.anthropic.api_key'",
        )
        self.conn.commit()

        # Clear env too
        old = os.environ.pop("ANTHROPIC_API_KEY", None)
        old2 = os.environ.pop("NIWA_LLM_API_KEY", None)
        try:
            r = assistant_service.assistant_turn(
                session_id="s4", project_id=self.pid,
                message="hola", channel="web", conn=self.conn,
            )
            assert r["error"] == "llm_not_configured"
        finally:
            if old is not None:
                os.environ["ANTHROPIC_API_KEY"] = old
            if old2 is not None:
                os.environ["NIWA_LLM_API_KEY"] = old2

    def test_http_error_persists_message(self, monkeypatch):
        """HTTP 429 from API → error message persisted."""
        def fake_fail(*a, **kw):
            raise urllib.error.HTTPError(
                "https://api.anthropic.com/v1/messages",
                429, "Rate limited", {}, None,
            )
        monkeypatch.setattr(assistant_service, "call_anthropic", fake_fail)

        r = assistant_service.assistant_turn(
            session_id="s5", project_id=self.pid,
            message="hola", channel="web", conn=self.conn,
        )
        assert "429" in r["assistant_message"]
        # Verify persisted
        msgs = _get_chat_messages(self.conn, r["session_id"])
        assert msgs[-1]["role"] == "assistant"
        assert "429" in msgs[-1]["content"]

    def test_max_iterations_respected(self, monkeypatch):
        """Loop stops after MAX_TOOL_ITERATIONS even if LLM keeps calling tools."""
        call_count = {"n": 0}

        def fake_always_tool(*a, **kw):
            call_count["n"] += 1
            return {
                "content": [{
                    "type": "tool_use",
                    "id": f"tu-{call_count['n']}",
                    "name": "project_context",
                    "input": {},
                }],
                "stop_reason": "tool_use",
            }

        monkeypatch.setattr(
            assistant_service, "call_anthropic", fake_always_tool,
        )
        r = assistant_service.assistant_turn(
            session_id="s6", project_id=self.pid,
            message="hola", channel="web", conn=self.conn,
        )
        # Should have stopped at MAX_TOOL_ITERATIONS
        assert len(r["actions_taken"]) <= assistant_service.MAX_TOOL_ITERATIONS
        assert call_count["n"] == assistant_service.MAX_TOOL_ITERATIONS

    def test_timeout_respected(self, monkeypatch):
        """Turn respects 30s deadline."""
        import time as _time

        original_monotonic = _time.monotonic
        # Simulate time passing: first call normal, second call near deadline
        call_count = {"n": 0}
        base = original_monotonic()

        def fast_time():
            call_count["n"] += 1
            if call_count["n"] > 4:
                return base + 29  # near the 30s deadline
            return base + call_count["n"]

        monkeypatch.setattr(_time, "monotonic", fast_time)

        def fake_tool(*a, **kw):
            return {
                "content": [{
                    "type": "tool_use", "id": "tu-t",
                    "name": "project_context", "input": {},
                }],
                "stop_reason": "tool_use",
            }
        monkeypatch.setattr(assistant_service, "call_anthropic", fake_tool)

        r = assistant_service.assistant_turn(
            session_id="s7", project_id=self.pid,
            message="hola", channel="web", conn=self.conn,
        )
        # Should have stopped due to timeout, not max iterations
        assert len(r["actions_taken"]) < assistant_service.MAX_TOOL_ITERATIONS

    def test_turn_persists_both_messages_on_success(self, monkeypatch):
        """Successful turn writes user + assistant to chat_messages."""
        monkeypatch.setattr(
            assistant_service, "call_anthropic",
            _fake_llm_simple("Respuesta."),
        )
        r = assistant_service.assistant_turn(
            session_id="s8", project_id=self.pid,
            message="pregunta", channel="web", conn=self.conn,
        )
        msgs = _get_chat_messages(self.conn, r["session_id"])
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "pregunta"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == "Respuesta."

    def test_approval_pre_routing_returns_ids(self, monkeypatch):
        """If LLM queries approvals, IDs appear in response."""
        # Seed a task + approval
        now = assistant_service._now_iso()
        tid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO tasks (id, title, area, project_id, status, "
            "priority, created_at, updated_at) "
            "VALUES (?, 'Blocked', 'proyecto', ?, 'en_progreso', 'media', ?, ?)",
            (tid, self.pid, now, now),
        )
        aid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO approvals (id, task_id, approval_type, reason, "
            "risk_level, status, requested_at) "
            "VALUES (?, ?, 'capability_denied', 'test', 'medium', 'pending', ?)",
            (aid, tid, now),
        )
        self.conn.commit()

        monkeypatch.setattr(
            assistant_service, "call_anthropic",
            _fake_llm_tool_then_text(
                "approval_list", {"status": "pending"}, "tu-a",
                "Hay una aprobación pendiente.",
            ),
        )
        r = assistant_service.assistant_turn(
            session_id="s9", project_id=self.pid,
            message="¿hay aprobaciones?", channel="web", conn=self.conn,
        )
        assert aid in r["approval_ids"]
