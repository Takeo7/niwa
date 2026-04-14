"""Integration tests for MCP v02-assistant stack — PR-09 Niwa v0.2.

NOTE: Full MCP protocol integration tests (gateway → MCP server → app)
require an MCP client library, which is a new dependency not present in
this environment.  These tests cover the HTTP integration layer instead:
app running with real DB, all tool endpoints exercised end-to-end.

For full MCP protocol testing, use:
    bin/niwa-mcp-smoke --app-url http://localhost:8080 \\
                       --token <NIWA_MCP_SERVER_TOKEN> \\
                       --project-id <PROJECT_ID>

Or in Docker:
    docker compose up -d
    docker exec <app-container> python -c \\
        "from mcp_smoke import smoke_assistant_mode; \\
         print(smoke_assistant_mode(app_url='http://localhost:8080', ...))"

Run with: pytest tests/test_mcp_integration.py -v
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


S2S_TOKEN = "integration-test-token"


# ── Helpers ──────────────────────────────────────────────────────────

def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _post(base, path, body, token=None):
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(f"{base}{path}", data=data, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except Exception as e:
        if hasattr(e, "read"):
            return e.code, json.loads(e.read())
        raise


# ── Fixture: full app with real DB, s2s token, routing_mode=v02 ────

@pytest.fixture(scope="module")
def app_stack():
    """Start Niwa app configured for v02-assistant integration test."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    port = _free_port()

    os.environ["NIWA_DB_PATH"] = db_path
    os.environ["NIWA_APP_PORT"] = str(port)
    os.environ["NIWA_APP_AUTH_REQUIRED"] = "1"
    os.environ["NIWA_APP_HOST"] = "127.0.0.1"
    os.environ["NIWA_MCP_SERVER_TOKEN"] = S2S_TOKEN

    import importlib
    if "app" in sys.modules:
        import app
        from pathlib import Path
        app.DB_PATH = Path(db_path)
        app.NIWA_APP_AUTH_REQUIRED = True
        app.NIWA_MCP_SERVER_TOKEN = S2S_TOKEN
    else:
        import app

    app.HOST = "127.0.0.1"
    app.PORT = port
    app.init_db()

    # Seed: project + routing_mode=v02 + API key
    conn = app.db_conn()
    now = app.now_iso()
    pid = str(uuid.uuid4())
    slug = f"integ-{pid[:8]}"
    conn.execute(
        "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
        "VALUES (?, ?, 'Integration Test', 'proyecto', ?, ?)",
        (pid, slug, now, now),
    )
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        ("routing_mode", "v02"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        ("svc.llm.anthropic.api_key", "sk-test-integration"),
    )
    conn.commit()
    conn.close()

    # Patch LLM to avoid real API calls
    import assistant_service
    _orig = assistant_service._call_anthropic

    def fake_llm(*a, **kw):
        return {
            "content": [{"type": "text", "text": "Integration test response."}],
            "stop_reason": "end_turn",
        }
    assistant_service._call_anthropic = fake_llm

    srv = ThreadingHTTPServer(("127.0.0.1", port), app.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{port}"
    for _ in range(30):
        try:
            urlopen(f"{base}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.1)

    yield {"base": base, "pid": pid, "db_path": db_path}

    srv.shutdown()
    assistant_service._call_anthropic = _orig
    os.close(fd)
    os.unlink(db_path)


# ── Integration test: full workflow via HTTP endpoints ────────────────

class TestV02AssistantIntegration:
    """End-to-end test of the v02-assistant workflow via HTTP.

    Simulates what the MCP server does: call tool endpoints with s2s
    token, verify responses match the contract.
    """

    def test_01_project_context(self, app_stack):
        """Get project context — verifies DB + endpoints work."""
        status, body = _post(
            app_stack["base"], "/api/assistant/tools/project_context",
            {"project_id": app_stack["pid"], "params": {}},
            token=S2S_TOKEN,
        )
        assert status == 200
        assert body["project"]["name"] == "Integration Test"

    def test_02_create_task(self, app_stack):
        """Create a task via the tool endpoint."""
        status, body = _post(
            app_stack["base"], "/api/assistant/tools/task_create",
            {"project_id": app_stack["pid"], "params": {
                "title": "Integration test task",
                "description": "Created by test_mcp_integration",
                "priority": "alta",
            }},
            token=S2S_TOKEN,
        )
        assert status == 200
        assert "task_id" in body
        app_stack["task_id"] = body["task_id"]

    def test_03_task_list_shows_task(self, app_stack):
        """List tasks and verify the created task appears."""
        status, body = _post(
            app_stack["base"], "/api/assistant/tools/task_list",
            {"project_id": app_stack["pid"], "params": {}},
            token=S2S_TOKEN,
        )
        assert status == 200
        assert body["count"] >= 1
        ids = [t["id"] for t in body["tasks"]]
        assert app_stack.get("task_id") in ids

    def test_04_task_get_detail(self, app_stack):
        """Get task detail."""
        tid = app_stack.get("task_id")
        assert tid
        status, body = _post(
            app_stack["base"], "/api/assistant/tools/task_get",
            {"project_id": app_stack["pid"], "params": {"task_id": tid}},
            token=S2S_TOKEN,
        )
        assert status == 200
        assert body["title"] == "Integration test task"
        assert body["priority"] == "alta"

    def test_05_task_cancel(self, app_stack):
        """Cancel the task."""
        tid = app_stack.get("task_id")
        status, body = _post(
            app_stack["base"], "/api/assistant/tools/task_cancel",
            {"project_id": app_stack["pid"], "params": {"task_id": tid}},
            token=S2S_TOKEN,
        )
        assert status == 200
        assert body["status"] == "archivada"

    def test_06_assistant_turn_roundtrip(self, app_stack):
        """Full assistant_turn roundtrip with fake LLM."""
        status, body = _post(
            app_stack["base"], "/api/assistant/turn",
            {
                "session_id": "integ-session",
                "project_id": app_stack["pid"],
                "message": "ping",
                "channel": "cli",
            },
            token=S2S_TOKEN,
        )
        assert status == 200
        assert body["assistant_message"] == "Integration test response."
        # Verify contract shape
        for key in ("assistant_message", "actions_taken", "task_ids",
                     "approval_ids", "run_ids"):
            assert key in body, f"Missing key: {key}"

    def test_07_smoke_function_against_real_app(self, app_stack):
        """Run smoke_assistant_mode against the live test app."""
        from mcp_smoke import smoke_assistant_mode
        result = smoke_assistant_mode(
            app_url=app_stack["base"],
            token=S2S_TOKEN,
            project_id=app_stack["pid"],
        )
        assert result["ok"] is True, f"Smoke failed: {result}"
        assert result["duration_ms"] >= 0
