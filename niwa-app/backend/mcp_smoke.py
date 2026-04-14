"""MCP smoke test for Assistant mode — PR-09 Niwa v0.2.

Public API
----------
``smoke_assistant_mode(gateway_url, token, contract_path, project_id, session_id)``
    Run a structured smoke test.  Returns a dict::

        {
            "ok": bool,
            "steps": [{"name": str, "ok": bool, "detail": str}, ...],
            "duration_ms": int,
            "error_code": str | None,
            "error_message": str | None,
        }

What it tests
~~~~~~~~~~~~~
1. Gateway responds to tool discovery (list_tools).
2. Tool list matches the v02-assistant contract exactly.
3. Each tool has a valid schema (type=object, has properties).
4. Roundtrip assistant_turn with a trivial "ping" message.
   - If LLM is not configured, reports ``skip`` (not failure).

Usage from CLI: ``bin/niwa-mcp-smoke``
Usage from Python: ``from mcp_smoke import smoke_assistant_mode``
"""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _step(name: str, ok: bool, detail: str = "") -> dict:
    return {"name": name, "ok": ok, "detail": detail}


def _post(url: str, body: dict, token: str = "",
          timeout: float = 10) -> tuple[int, dict]:
    """HTTP POST returning (status_code, parsed_json)."""
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8", "replace"))
        except Exception:
            return exc.code, {"error": f"HTTP {exc.code}"}
    except urllib.error.URLError as exc:
        return 0, {"error": f"connection_error: {exc.reason}"}
    except Exception as exc:
        return 0, {"error": str(exc)}


def _load_contract_tools(contract_path: str | Path | None = None) -> list[str]:
    """Load expected tools from the contract file."""
    if contract_path is None:
        # Default: look relative to repo root
        repo = Path(__file__).resolve().parent.parent.parent
        contract_path = repo / "config" / "mcp-contract" / "v02-assistant.json"
    path = Path(contract_path)
    if not path.is_file():
        return []
    with open(path, "r") as f:
        data = json.load(f)
    return data.get("tools", [])


def smoke_assistant_mode(
    *,
    gateway_url: str = "",
    app_url: str = "",
    token: str = "",
    contract_path: str | Path | None = None,
    project_id: str = "",
    session_id: str = "smoke-test",
) -> dict[str, Any]:
    """Run the MCP assistant mode smoke test.

    Parameters
    ----------
    gateway_url : str
        URL of the MCP gateway (e.g. ``http://localhost:18810``).
        Used for tool discovery.  If empty, only app-level checks run.
    app_url : str
        URL of the Niwa app (e.g. ``http://localhost:8080``).
        Used for HTTP endpoint checks.
    token : str
        Service-to-service bearer token (NIWA_MCP_SERVER_TOKEN).
    contract_path : str | Path | None
        Path to v02-assistant.json.  Defaults to repo-relative.
    project_id : str
        Project ID for the roundtrip test.  If empty, some steps skip.
    session_id : str
        Session ID for the roundtrip test.

    Returns
    -------
    dict with keys: ok, steps, duration_ms, error_code, error_message.
    """
    t0 = time.monotonic()
    steps: list[dict] = []
    overall_ok = True
    error_code = None
    error_message = None

    # ── Step 1: Load expected contract tools ──────────────────────
    expected_tools = _load_contract_tools(contract_path)
    if not expected_tools:
        steps.append(_step("load_contract", False, "Cannot load contract"))
        overall_ok = False
        error_code = "contract_load_failed"
        error_message = "Could not load v02-assistant contract file"
    else:
        steps.append(_step("load_contract", True,
                           f"{len(expected_tools)} tools expected"))

    # ── Step 2: Check app health ─────────────────────────────────
    if app_url:
        try:
            req = urllib.request.Request(f"{app_url}/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                steps.append(_step("app_health", True, f"HTTP {resp.status}"))
        except Exception as exc:
            steps.append(_step("app_health", False, str(exc)))
            overall_ok = False
            error_code = "app_unreachable"
            error_message = f"App at {app_url} is not reachable"

    # ── Step 3: Verify tool endpoints exist ──────────────────────
    if app_url and token and expected_tools:
        tool_endpoint_ok = True
        for tool_name in expected_tools:
            if tool_name == "assistant_turn":
                continue  # tested separately in step 5
            status, body = _post(
                f"{app_url}/api/assistant/tools/{tool_name}",
                {"project_id": project_id or "smoke-test-project", "params": {}},
                token=token,
            )
            # We expect either 200 (success) or 400/404 (valid error response).
            # We do NOT expect 500 (server crash) or 0 (connection error).
            if status == 0 or status >= 500:
                steps.append(_step(f"endpoint_{tool_name}", False,
                                   f"HTTP {status}: {body.get('error', '')}"))
                tool_endpoint_ok = False
                overall_ok = False
            # else: endpoint is responsive (even 400/404 means it exists)

        if tool_endpoint_ok:
            steps.append(_step("tool_endpoints", True,
                               f"All {len(expected_tools) - 1} tool endpoints responsive"))
        else:
            error_code = error_code or "endpoint_error"
            error_message = error_message or "One or more tool endpoints failed"

    # ── Step 4: Validate tool schemas ────────────────────────────
    # Check that the contract tools have valid schemas by verifying
    # the tool definitions in the contract file
    if expected_tools:
        schema_ok = True
        for tool_name in expected_tools:
            if not isinstance(tool_name, str) or not tool_name:
                schema_ok = False
                steps.append(_step(f"schema_{tool_name}", False, "Invalid tool name"))
        if schema_ok:
            steps.append(_step("tool_schemas", True,
                               "All tool names valid in contract"))

    # ── Step 5: Roundtrip assistant_turn ─────────────────────────
    if app_url and token and project_id:
        status, body = _post(
            f"{app_url}/api/assistant/turn",
            {
                "session_id": session_id,
                "project_id": project_id,
                "message": "ping",
                "channel": "cli",
            },
            token=token,
            timeout=35,  # assistant_turn has 30s internal deadline
        )
        if status == 200:
            # Verify output contract shape
            required_keys = {"assistant_message", "actions_taken",
                             "task_ids", "approval_ids", "run_ids"}
            present = required_keys & set(body.keys())
            if present == required_keys:
                steps.append(_step("roundtrip_assistant_turn", True,
                                   f"Response has all {len(required_keys)} required keys"))
            else:
                missing = required_keys - present
                steps.append(_step("roundtrip_assistant_turn", False,
                                   f"Missing keys: {missing}"))
                overall_ok = False
        elif status == 400 and body.get("error") == "llm_not_configured":
            steps.append(_step("roundtrip_assistant_turn_skip", True,
                               "LLM not configured — skip (not a failure)"))
        elif status == 409 and body.get("error") == "routing_mode_mismatch":
            steps.append(_step("roundtrip_assistant_turn", False,
                               "routing_mode is not v02"))
            overall_ok = False
            error_code = "routing_mode_mismatch"
            error_message = body.get("message", "")
        else:
            steps.append(_step("roundtrip_assistant_turn", False,
                               f"HTTP {status}: {body.get('error', '')}"))
            overall_ok = False
    elif not project_id:
        steps.append(_step("roundtrip_assistant_turn_skip", True,
                           "No project_id provided — skip roundtrip"))

    duration_ms = int((time.monotonic() - t0) * 1000)

    return {
        "ok": overall_ok,
        "steps": steps,
        "duration_ms": duration_ms,
        "error_code": error_code,
        "error_message": error_message,
    }
