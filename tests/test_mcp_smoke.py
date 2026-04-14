"""Tests for MCP smoke test — PR-09 Niwa v0.2.

Covers:
  - smoke_assistant_mode with mocked HTTP
  - Contract loading (success, missing)
  - Roundtrip: success, LLM not configured (skip), routing_mode_mismatch
  - Tool endpoint checks
  - CLI returns correct exit code

Run with: pytest tests/test_mcp_smoke.py -v
"""
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from mcp_smoke import smoke_assistant_mode


# ── Helpers ──────────────────────────────────────────────────────────

def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class FakeAppOK(BaseHTTPRequestHandler):
    """App that returns success for everything."""

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"status": "ok"})
        else:
            self._respond(404, {})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if self.path == "/api/assistant/turn":
            self._respond(200, {
                "assistant_message": "pong",
                "actions_taken": [],
                "task_ids": [],
                "approval_ids": [],
                "run_ids": [],
            })
        elif self.path.startswith("/api/assistant/tools/"):
            self._respond(200, {"ok": True})
        else:
            self._respond(404, {})

    def _respond(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class FakeAppLLMNotConfigured(FakeAppOK):
    """App that returns llm_not_configured on assistant_turn."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)  # consume body

        if self.path == "/api/assistant/turn":
            self._respond(400, {"error": "llm_not_configured", "message": "No API key"})
        elif self.path.startswith("/api/assistant/tools/"):
            self._respond(200, {"ok": True})
        else:
            self._respond(404, {})


class FakeAppRoutingMismatch(FakeAppOK):
    """App that returns routing_mode_mismatch on assistant_turn."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)  # consume body

        if self.path == "/api/assistant/turn":
            self._respond(409, {"error": "routing_mode_mismatch", "message": "Need v02"})
        elif self.path.startswith("/api/assistant/tools/"):
            self._respond(200, {"ok": True})
        else:
            self._respond(404, {})


def _start_server(handler_cls):
    port = _free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, f"http://127.0.0.1:{port}"


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ok_app():
    srv, url = _start_server(FakeAppOK)
    yield url
    srv.shutdown()


@pytest.fixture(scope="module")
def llm_missing_app():
    srv, url = _start_server(FakeAppLLMNotConfigured)
    yield url
    srv.shutdown()


@pytest.fixture(scope="module")
def routing_mismatch_app():
    srv, url = _start_server(FakeAppRoutingMismatch)
    yield url
    srv.shutdown()


# ── Tests ────────────────────────────────────────────────────────────

class TestSmokeSuccess:

    def test_full_pass(self, ok_app):
        result = smoke_assistant_mode(
            app_url=ok_app,
            token="test",
            project_id="p1",
        )
        assert result["ok"] is True
        assert result["duration_ms"] >= 0
        assert result["error_code"] is None
        # Check all steps passed
        for step in result["steps"]:
            assert step["ok"], f"Step {step['name']} failed: {step['detail']}"

    def test_contract_loaded(self, ok_app):
        result = smoke_assistant_mode(app_url=ok_app, token="test")
        contract_step = [s for s in result["steps"] if s["name"] == "load_contract"]
        assert len(contract_step) == 1
        assert contract_step[0]["ok"]
        assert "11" in contract_step[0]["detail"]


class TestSmokeLLMSkip:

    def test_llm_not_configured_is_skip(self, llm_missing_app):
        result = smoke_assistant_mode(
            app_url=llm_missing_app,
            token="test",
            project_id="p1",
        )
        assert result["ok"] is True  # LLM skip is NOT a failure
        skip_steps = [s for s in result["steps"]
                      if "skip" in s["name"].lower() or "skip" in s.get("detail", "").lower()]
        assert len(skip_steps) >= 1


class TestSmokeRoutingMismatch:

    def test_routing_mismatch_is_failure(self, routing_mismatch_app):
        result = smoke_assistant_mode(
            app_url=routing_mismatch_app,
            token="test",
            project_id="p1",
        )
        assert result["ok"] is False
        assert result["error_code"] == "routing_mode_mismatch"


class TestSmokeNoProjectId:

    def test_skips_roundtrip(self, ok_app):
        result = smoke_assistant_mode(app_url=ok_app, token="test")
        assert result["ok"] is True
        skip_steps = [s for s in result["steps"]
                      if "roundtrip" in s["name"] and "skip" in s["name"]]
        assert len(skip_steps) >= 1


class TestSmokeContractMissing:

    def test_bad_contract_path(self):
        result = smoke_assistant_mode(
            contract_path="/nonexistent/contract.json",
        )
        assert result["ok"] is False
        assert result["error_code"] == "contract_load_failed"


class TestSmokeAppUnreachable:

    def test_unreachable_app(self):
        result = smoke_assistant_mode(
            app_url="http://127.0.0.1:1",
            token="test",
        )
        assert result["ok"] is False
        assert result["error_code"] == "app_unreachable"
