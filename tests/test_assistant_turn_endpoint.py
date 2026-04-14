"""Tests for POST /api/assistant/turn endpoint — PR-08 Niwa v0.2.

Covers:
  - Input validation (missing fields -> 400)
  - routing_mode mismatch -> 409
  - Success path (200) with fake LLM
  - Contract shape (all 5 required keys present)

Run with: pytest tests/test_assistant_turn_endpoint.py -v
"""
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


# ── Helpers ──────────────────────────────────────────────────────────

def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _post(base, path, body):
    data = json.dumps(body).encode()
    req = Request(
        f"{base}{path}", data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except Exception as e:
        if hasattr(e, "read"):
            return e.code, json.loads(e.read())
        raise


# ── Session-scoped fixture: one server for all tests ─────────────────

@pytest.fixture(scope="module")
def server():
    """Start the Niwa app on a random port with a temp DB (once per module)."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    port = _free_port()

    os.environ["NIWA_DB_PATH"] = db_path
    os.environ["NIWA_APP_PORT"] = str(port)
    os.environ["NIWA_APP_AUTH_REQUIRED"] = "0"
    os.environ["NIWA_APP_HOST"] = "127.0.0.1"

    # Patch assistant_service._call_anthropic (private — used as default
    # when llm_caller is not injected, which is the case for the HTTP
    # endpoint).
    import assistant_service

    _original_call = assistant_service._call_anthropic

    def fake_llm(*a, **kw):
        return {
            "content": [{"type": "text", "text": "Fake response."}],
            "stop_reason": "end_turn",
        }
    assistant_service._call_anthropic = fake_llm

    # Force app module to pick up new DB_PATH
    if "app" in sys.modules:
        import app
        from pathlib import Path
        app.DB_PATH = Path(db_path)
    else:
        import app

    app.HOST = "127.0.0.1"
    app.PORT = port
    # Bug 13 fix (PR-12): NIWA_APP_AUTH_REQUIRED se evalúa en app.py a
    # nivel de módulo al importar. Si otro test importó ``app`` antes
    # con auth=1, ``sys.modules["app"]`` queda cacheado y el env var
    # que pusimos arriba se ignora. Fijar el atributo directamente es
    # el patrón establecido en tests/test_runs_endpoints.py:79 (PR-10a).
    app.NIWA_APP_AUTH_REQUIRED = False

    app.init_db()

    # Seed project + API key
    conn = app.db_conn()
    now = app.now_iso()
    pid = str(uuid.uuid4())
    slug = f"test-{pid[:8]}"
    conn.execute(
        "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
        "VALUES (?, ?, 'Test', 'proyecto', ?, ?)",
        (pid, slug, now, now),
    )
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        ("svc.llm.anthropic.api_key", "sk-test"),
    )
    conn.commit()
    conn.close()

    srv = ThreadingHTTPServer(("127.0.0.1", port), app.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{port}"
    for _ in range(30):
        try:
            urlopen(f"{base}/api/settings", timeout=1)
            break
        except Exception:
            time.sleep(0.1)

    yield {"base": base, "pid": pid, "db_path": db_path}

    srv.shutdown()
    assistant_service._call_anthropic = _original_call
    os.close(fd)
    os.unlink(db_path)


# ── Tests ────────────────────────────────────────────────────────────

class TestAssistantTurnEndpoint:

    def test_success_path(self, server):
        status, body = _post(server["base"], "/api/assistant/turn", {
            "session_id": "ep-s1",
            "project_id": server["pid"],
            "message": "hola",
            "channel": "web",
        })
        assert status == 200
        assert body["assistant_message"] == "Fake response."
        assert "session_id" in body

    def test_missing_message_returns_400(self, server):
        status, body = _post(server["base"], "/api/assistant/turn", {
            "session_id": "ep-s2",
            "project_id": server["pid"],
            "message": "",
            "channel": "web",
        })
        assert status == 400
        assert body["error"] == "empty_message"

    def test_missing_project_returns_400(self, server):
        status, body = _post(server["base"], "/api/assistant/turn", {
            "session_id": "ep-s3",
            "project_id": "",
            "message": "hi",
            "channel": "web",
        })
        assert status == 400
        assert body["error"] == "missing_project_id"

    def test_routing_mode_legacy_returns_409(self, server):
        """Set routing_mode to legacy -> 409."""
        conn = sqlite3.connect(server["db_path"])
        conn.row_factory = sqlite3.Row
        conn.execute(
            "UPDATE settings SET value = 'legacy' WHERE key = 'routing_mode'",
        )
        conn.commit()
        conn.close()

        status, body = _post(server["base"], "/api/assistant/turn", {
            "session_id": "ep-s4",
            "project_id": server["pid"],
            "message": "hola",
            "channel": "web",
        })
        assert status == 409
        assert body["error"] == "routing_mode_mismatch"

        # Restore v02 for subsequent tests
        conn = sqlite3.connect(server["db_path"])
        conn.execute(
            "UPDATE settings SET value = 'v02' WHERE key = 'routing_mode'",
        )
        conn.commit()
        conn.close()

    def test_contract_shape(self, server):
        """Response always contains the 5 contract keys."""
        status, body = _post(server["base"], "/api/assistant/turn", {
            "session_id": "ep-s5",
            "project_id": server["pid"],
            "message": "test",
            "channel": "web",
        })
        assert status == 200
        for key in ("assistant_message", "actions_taken",
                     "task_ids", "approval_ids", "run_ids"):
            assert key in body, f"Missing key: {key}"

    def test_malformed_json_returns_400(self, server):
        """Invalid JSON body → 400 (handler returns empty dict → missing fields)."""
        req = Request(
            f"{server['base']}/api/assistant/turn",
            data=b"this is not json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=10) as resp:
                status = resp.status
                body = json.loads(resp.read())
        except Exception as e:
            status = e.code
            body = json.loads(e.read())
        assert status == 400
        assert body["error"] in ("missing_session_id", "empty_message")

    def test_wrong_content_type_returns_400(self, server):
        """Non-JSON Content-Type → handler parses as form, fields empty → 400."""
        req = Request(
            f"{server['base']}/api/assistant/turn",
            data=b"garbage=true",
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=10) as resp:
                status = resp.status
                body = json.loads(resp.read())
        except Exception as e:
            status = e.code
            body = json.loads(e.read())
        assert status == 400
        assert "error" in body
