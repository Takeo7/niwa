"""Tests for POST /api/assistant/tools/* endpoints — PR-09 Niwa v0.2.

Covers:
  - Service-to-service bearer token auth (valid, missing, invalid)
  - Each of the 10 tool endpoints (task_list, task_get, task_create,
    task_cancel, task_resume, approval_list, approval_respond,
    run_tail, run_explain, project_context)
  - Unknown tool → 404
  - Missing project_id → 400
  - Error mapping (domain errors → correct HTTP status)

Run with: pytest tests/test_assistant_tool_endpoints.py -v
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


S2S_TOKEN = "test-s2s-token-pr09"


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
    req = Request(
        f"{base}{path}", data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except Exception as e:
        if hasattr(e, "read"):
            return e.code, json.loads(e.read())
        raise


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def server():
    """Start Niwa app with auth enabled and a known s2s token."""
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

    # Seed project
    conn = app.db_conn()
    now = app.now_iso()
    pid = str(uuid.uuid4())
    slug = f"test-{pid[:8]}"
    conn.execute(
        "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
        "VALUES (?, ?, 'TestProj', 'proyecto', ?, ?)",
        (pid, slug, now, now),
    )
    conn.commit()
    conn.close()

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
    os.close(fd)
    os.unlink(db_path)


# ── Auth tests ───────────────────────────────────────────────────────

class TestS2SAuth:

    def test_valid_token_passes(self, server):
        status, body = _post(
            server["base"], "/api/assistant/tools/task_list",
            {"project_id": server["pid"], "params": {}},
            token=S2S_TOKEN,
        )
        assert status == 200
        assert "tasks" in body

    def test_missing_token_returns_401(self, server):
        status, body = _post(
            server["base"], "/api/assistant/tools/task_list",
            {"project_id": server["pid"], "params": {}},
        )
        assert status == 401

    def test_invalid_token_returns_401(self, server):
        status, body = _post(
            server["base"], "/api/assistant/tools/task_list",
            {"project_id": server["pid"], "params": {}},
            token="wrong-token",
        )
        assert status == 401


# ── Endpoint contract tests ──────────────────────────────────────────

class TestToolEndpoints:

    def test_unknown_tool_returns_404(self, server):
        status, body = _post(
            server["base"], "/api/assistant/tools/nonexistent",
            {"project_id": server["pid"], "params": {}},
            token=S2S_TOKEN,
        )
        assert status == 404
        assert body["error"] == "unknown_tool"

    def test_missing_project_id_returns_400(self, server):
        status, body = _post(
            server["base"], "/api/assistant/tools/task_list",
            {"params": {}},
            token=S2S_TOKEN,
        )
        assert status == 400
        assert "project_id" in body["error"]

    # ── task_list ────────────────────────────────────────────────

    def test_task_list_empty(self, server):
        status, body = _post(
            server["base"], "/api/assistant/tools/task_list",
            {"project_id": server["pid"], "params": {}},
            token=S2S_TOKEN,
        )
        assert status == 200
        assert body["count"] == 0
        assert body["tasks"] == []

    # ── task_create + task_get ───────────────────────────────────

    def test_task_create_and_get(self, server):
        # Create
        status, body = _post(
            server["base"], "/api/assistant/tools/task_create",
            {"project_id": server["pid"], "params": {
                "title": "PR-09 test task",
                "description": "Created by endpoint test",
            }},
            token=S2S_TOKEN,
        )
        assert status == 200
        assert "task_id" in body
        tid = body["task_id"]

        # Get
        status, body = _post(
            server["base"], "/api/assistant/tools/task_get",
            {"project_id": server["pid"], "params": {"task_id": tid}},
            token=S2S_TOKEN,
        )
        assert status == 200
        assert body["title"] == "PR-09 test task"

    def test_task_create_missing_title(self, server):
        status, body = _post(
            server["base"], "/api/assistant/tools/task_create",
            {"project_id": server["pid"], "params": {}},
            token=S2S_TOKEN,
        )
        assert status == 400
        assert body["error"] == "title is required"

    # ── task_get not found ──────────────────────────────────────

    def test_task_get_not_found(self, server):
        status, body = _post(
            server["base"], "/api/assistant/tools/task_get",
            {"project_id": server["pid"], "params": {"task_id": "nope"}},
            token=S2S_TOKEN,
        )
        assert status == 404
        assert body["error"] == "task_not_found"

    # ── task_cancel ─────────────────────────────────────────────

    def test_task_cancel(self, server):
        # Create a task first
        _, cr = _post(
            server["base"], "/api/assistant/tools/task_create",
            {"project_id": server["pid"], "params": {"title": "to cancel"}},
            token=S2S_TOKEN,
        )
        tid = cr["task_id"]

        # Cancel it
        status, body = _post(
            server["base"], "/api/assistant/tools/task_cancel",
            {"project_id": server["pid"], "params": {"task_id": tid}},
            token=S2S_TOKEN,
        )
        assert status == 200
        assert body["status"] == "archivada"

    # ── task_resume (cannot resume from pendiente) ──────────────

    def test_task_resume_invalid_transition(self, server):
        _, cr = _post(
            server["base"], "/api/assistant/tools/task_create",
            {"project_id": server["pid"], "params": {"title": "resume test"}},
            token=S2S_TOKEN,
        )
        tid = cr["task_id"]

        # Pendiente → pendiente is not a valid transition
        status, body = _post(
            server["base"], "/api/assistant/tools/task_resume",
            {"project_id": server["pid"], "params": {"task_id": tid}},
            token=S2S_TOKEN,
        )
        assert status == 409
        assert body["error"] == "cannot_resume"

    # ── approval_list ───────────────────────────────────────────

    def test_approval_list_empty(self, server):
        status, body = _post(
            server["base"], "/api/assistant/tools/approval_list",
            {"project_id": server["pid"], "params": {}},
            token=S2S_TOKEN,
        )
        assert status == 200
        assert body["count"] == 0

    # ── approval_respond ────────────────────────────────────────

    def test_approval_respond_missing_id(self, server):
        """Missing approval_id returns 400."""
        status, body = _post(
            server["base"], "/api/assistant/tools/approval_respond",
            {"project_id": server["pid"], "params": {"decision": "approved"}},
            token=S2S_TOKEN,
        )
        assert status == 400
        assert body["error"] == "approval_id is required"

    def test_approval_respond_invalid_decision(self, server):
        """Decision must be 'approved' or 'rejected'."""
        status, body = _post(
            server["base"], "/api/assistant/tools/approval_respond",
            {"project_id": server["pid"], "params": {
                "approval_id": "any", "decision": "maybe",
            }},
            token=S2S_TOKEN,
        )
        assert status == 400
        assert "approved" in body["error"]

    def test_approval_respond_not_found(self, server):
        """Nonexistent approval_id → approval_not_found."""
        status, body = _post(
            server["base"], "/api/assistant/tools/approval_respond",
            {"project_id": server["pid"], "params": {
                "approval_id": "nonexistent-uuid",
                "decision": "approved",
            }},
            token=S2S_TOKEN,
        )
        assert status == 404
        assert body["error"] == "approval_not_found"

    # ── run_tail not found ──────────────────────────────────────

    def test_run_tail_not_found(self, server):
        status, body = _post(
            server["base"], "/api/assistant/tools/run_tail",
            {"project_id": server["pid"], "params": {"run_id": "nope"}},
            token=S2S_TOKEN,
        )
        assert status == 404
        assert body["error"] == "run_not_found"

    # ── run_explain no decision ─────────────────────────────────

    def test_run_explain_no_decision(self, server):
        _, cr = _post(
            server["base"], "/api/assistant/tools/task_create",
            {"project_id": server["pid"], "params": {"title": "explain test"}},
            token=S2S_TOKEN,
        )
        tid = cr["task_id"]

        status, body = _post(
            server["base"], "/api/assistant/tools/run_explain",
            {"project_id": server["pid"], "params": {"task_id": tid}},
            token=S2S_TOKEN,
        )
        assert status == 200
        assert "No routing decision" in body.get("message", "")

    # ── project_context ─────────────────────────────────────────

    def test_project_context(self, server):
        status, body = _post(
            server["base"], "/api/assistant/tools/project_context",
            {"project_id": server["pid"], "params": {}},
            token=S2S_TOKEN,
        )
        assert status == 200
        assert "project" in body
        assert body["project"]["name"] == "TestProj"

    def test_project_context_not_found(self, server):
        status, body = _post(
            server["base"], "/api/assistant/tools/project_context",
            {"project_id": "nonexistent", "params": {}},
            token=S2S_TOKEN,
        )
        assert status == 404
        assert body["error"] == "project_not_found"
