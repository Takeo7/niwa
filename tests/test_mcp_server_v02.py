"""Tests for MCP server v02-assistant tools — PR-09 Niwa v0.2.

Covers:
  - Contract filtering: with NIWA_MCP_CONTRACT=v02-assistant only 11 tools
  - Contract filtering: without NIWA_MCP_CONTRACT, 21 legacy tools
  - HTTP proxy: assistant_turn proxied to app endpoint
  - HTTP proxy: task_list proxied to /api/assistant/tools/task_list
  - Error mapping: HTTP errors translated to structured MCP errors

Run with: pytest tests/test_mcp_server_v02.py -v
"""
import json
import os
import sys
import threading
import time
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCP_DIR = os.path.join(ROOT_DIR, "servers", "tasks-mcp")
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")

# The mcp package is only available in Docker.  Mock it for local tests.
import types
if "mcp" not in sys.modules:
    mcp_mod = types.ModuleType("mcp")
    mcp_server_mod = types.ModuleType("mcp.server")
    mcp_stdio_mod = types.ModuleType("mcp.server.stdio")
    mcp_types_mod = types.ModuleType("mcp.types")

    class _FakeServer:
        def __init__(self, name): self.name = name
        def list_tools(self): return lambda fn: fn
        def call_tool(self): return lambda fn: fn
        def create_initialization_options(self): return {}
        async def run(self, *a, **k): pass

    class _FakeTool:
        def __init__(self, *, name, description, inputSchema):
            self.name = name
            self.description = description
            self.inputSchema = inputSchema

    class _FakeTextContent:
        def __init__(self, *, type, text):
            self.type = type
            self.text = text

    mcp_server_mod.Server = _FakeServer
    mcp_types_mod.Tool = _FakeTool
    mcp_types_mod.TextContent = _FakeTextContent

    async def _fake_stdio():
        class _Ctx:
            async def __aenter__(self): return (None, None)
            async def __aexit__(self, *a): pass
        return _Ctx()
    mcp_stdio_mod.stdio_server = _fake_stdio

    mcp_mod.server = mcp_server_mod
    mcp_mod.types = mcp_types_mod
    sys.modules["mcp"] = mcp_mod
    sys.modules["mcp.server"] = mcp_server_mod
    sys.modules["mcp.server.stdio"] = mcp_stdio_mod
    sys.modules["mcp.types"] = mcp_types_mod

if MCP_DIR not in sys.path:
    sys.path.insert(0, MCP_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


# ── Helpers ──────────────────────────────────────────────────────────

def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class FakeAppHandler(BaseHTTPRequestHandler):
    """Minimal fake Niwa app that returns canned responses."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        path = self.path

        # Verify auth token
        auth = self.headers.get("Authorization", "")
        if auth != "Bearer test-token":
            self._respond(401, {"error": "unauthorized"})
            return

        if path == "/api/assistant/turn":
            self._respond(200, {
                "assistant_message": "pong",
                "actions_taken": [],
                "task_ids": [],
                "approval_ids": [],
                "run_ids": [],
                "session_id": body.get("session_id", ""),
            })
        elif path.startswith("/api/assistant/tools/"):
            tool = path.split("/api/assistant/tools/")[-1]
            if tool == "task_list":
                self._respond(200, {"tasks": [], "count": 0})
            elif tool == "project_context":
                if body.get("project_id") == "bad":
                    self._respond(404, {"error": "project_not_found"})
                else:
                    self._respond(200, {"project": {"name": "Test"}, "task_summary": {}, "recent_tasks": [], "pending_approvals": 0})
            else:
                self._respond(200, {"ok": True, "tool": tool})
        else:
            self._respond(404, {"error": "not_found"})

    def _respond(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass  # suppress request logs


@pytest.fixture(scope="module")
def fake_app():
    """Start a fake Niwa app for HTTP proxy tests."""
    port = _free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), FakeAppHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    # Wait for server
    import urllib.request
    base = f"http://127.0.0.1:{port}"
    for _ in range(20):
        try:
            req = urllib.request.Request(f"{base}/health", method="POST",
                                         data=b'{}',
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": "Bearer test-token"})
            urllib.request.urlopen(req, timeout=1)
        except Exception:
            pass
        break
    yield {"base": base, "port": port}
    srv.shutdown()


# ── Contract filtering tests ─────────────────────────────────────────

class TestContractFiltering:

    def test_load_contract_tools_v02(self):
        """When NIWA_MCP_CONTRACT=v02-assistant, _load_contract_tools returns 11 tools."""
        import server as mcp_server
        # Patch the contract config dir to point at the real config
        config_path = os.path.join(ROOT_DIR, "config", "mcp-contract", "v02-assistant.json")
        assert os.path.isfile(config_path), f"Contract not found: {config_path}"

        with open(config_path) as f:
            data = json.load(f)
        tools = set(data["tools"])
        assert len(tools) == 11
        assert "assistant_turn" in tools
        assert "task_list" in tools
        assert "project_context" in tools

    def test_v02_tool_defs_count(self):
        """The server defines exactly 11 v02 tool defs."""
        import server as mcp_server
        assert len(mcp_server._V02_TOOL_DEFS) == 11

    def test_v02_tool_names_match_contract(self):
        """Tool names in _V02_TOOL_DEFS match the contract file."""
        import server as mcp_server
        config_path = os.path.join(ROOT_DIR, "config", "mcp-contract", "v02-assistant.json")
        with open(config_path) as f:
            data = json.load(f)
        contract_tools = set(data["tools"])
        server_tools = {t.name for t in mcp_server._V02_TOOL_DEFS}
        assert server_tools == contract_tools

    def test_legacy_tool_defs_count(self):
        """The server defines 21 legacy tool defs."""
        import server as mcp_server
        assert len(mcp_server._LEGACY_TOOL_DEFS) == 21

    def test_assistant_turn_schema_has_channel(self):
        """assistant_turn requires channel with correct enum."""
        import server as mcp_server
        at = [t for t in mcp_server._V02_TOOL_DEFS if t.name == "assistant_turn"][0]
        props = at.inputSchema["properties"]
        assert "channel" in props
        assert props["channel"]["enum"] == ["web", "telegram", "cli", "other"]
        assert "channel" in at.inputSchema["required"]


# ── HTTP proxy tests ─────────────────────────────────────────────────

class TestHTTPProxy:

    def test_assistant_turn_proxy(self, fake_app):
        """assistant_turn proxies to /api/assistant/turn."""
        import server as mcp_server
        with patch.object(mcp_server, "_APP_BASE_URL", fake_app["base"]), \
             patch.object(mcp_server, "_S2S_TOKEN", "test-token"):
            result = mcp_server._call_v02_tool("assistant_turn", {
                "session_id": "s1",
                "project_id": "p1",
                "message": "ping",
                "channel": "cli",
            })
        assert result["assistant_message"] == "pong"

    def test_task_list_proxy(self, fake_app):
        """task_list proxies to /api/assistant/tools/task_list."""
        import server as mcp_server
        with patch.object(mcp_server, "_APP_BASE_URL", fake_app["base"]), \
             patch.object(mcp_server, "_S2S_TOKEN", "test-token"):
            result = mcp_server._call_v02_tool("task_list", {
                "project_id": "p1",
            })
        assert result["count"] == 0
        assert result["tasks"] == []

    def test_error_mapping_404(self, fake_app):
        """HTTP 404 from app translates to error_code in proxy."""
        import server as mcp_server
        with patch.object(mcp_server, "_APP_BASE_URL", fake_app["base"]), \
             patch.object(mcp_server, "_S2S_TOKEN", "test-token"):
            result = mcp_server._call_v02_tool("project_context", {
                "project_id": "bad",
            })
        assert result.get("error_code") == "project_not_found"

    def test_error_mapping_auth_failure(self, fake_app):
        """Missing/wrong s2s token → auth_failure."""
        import server as mcp_server
        with patch.object(mcp_server, "_APP_BASE_URL", fake_app["base"]), \
             patch.object(mcp_server, "_S2S_TOKEN", "wrong-token"):
            result = mcp_server._call_v02_tool("task_list", {
                "project_id": "p1",
            })
        assert result.get("error_code") == "auth_failure"

    def test_connection_error(self):
        """Unreachable app → connection_error."""
        import server as mcp_server
        with patch.object(mcp_server, "_APP_BASE_URL", "http://127.0.0.1:1"), \
             patch.object(mcp_server, "_S2S_TOKEN", "test-token"):
            result = mcp_server._call_v02_tool("task_list", {
                "project_id": "p1",
            })
        assert result.get("error_code") == "connection_error"
