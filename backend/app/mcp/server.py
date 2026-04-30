"""MCP HTTP server — JSON-RPC 2.0 over HTTP for Niwa tools (Phase 7, MCP-02).

Transport: HTTP POST /mcp (request/response, no streaming).
Authentication: Bearer token required (NIWA_MCP_TOKEN env var or API token).

MCP protocol:
    Request:  {"jsonrpc": "2.0", "id": ..., "method": "...", "params": {...}}
    Response: {"jsonrpc": "2.0", "id": ..., "result": ...}
              {"jsonrpc": "2.0", "id": ..., "error": {"code": ..., "message": ...}}

Supported methods:
    ping                         → {pong: true, version: str}
    tools/list                   → list of tool definitions
    tools/call {name, arguments} → tool result

Tool scope mapping (API token scopes):
    read        → project_list, project_get, task_status, task_list
    task:create → task_create, task_attach
    task:write  → task_respond, task_cancel, task_retry
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..api.deps import get_session
from ..auth.token_store import validate_token
from .tools import projects as proj_tools
from .tools import tasks as task_tools

router = APIRouter(prefix="/mcp", tags=["mcp"])

_VERSION = "1.0.0"

# ── Auth ───────────────────────────────────────────────────────────────────────


def _get_mcp_token(request: Request, db: Session) -> set[str]:
    """Return the scopes for the Bearer token, or all scopes if env token matches."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")

    raw = auth[7:]

    # Accept env-var master token (dev/bootstrap)
    env_token = os.environ.get("NIWA_MCP_TOKEN")
    if env_token and raw == env_token:
        return {"read", "task:create", "task:write", "merge", "deploy", "admin"}

    # Validate DB token
    token = validate_token(db, raw)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked token")

    return set(token.scopes.split())


def _require_scope(scopes: set[str], scope: str) -> None:
    if "admin" in scopes or scope in scopes:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Scope '{scope}' required",
    )


# ── JSON-RPC helpers ──────────────────────────────────────────────────────────


def _ok(id_: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _err(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


# ── Tool definitions ───────────────────────────────────────────────────────────


_TOOLS = [
    {
        "name": "ping",
        "description": "Check connectivity to Niwa MCP server.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "project_list",
        "description": "List all Niwa projects. Requires scope: read.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "project_get",
        "description": "Get details of a project. Requires scope: read.",
        "inputSchema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        },
    },
    {
        "name": "task_list",
        "description": "List tasks for a project. Requires scope: read.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_slug": {"type": "string"}},
            "required": ["project_slug"],
        },
    },
    {
        "name": "task_create",
        "description": "Create a task in a project. Requires scope: task:create.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_slug": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["project_slug", "title"],
        },
    },
    {
        "name": "task_status",
        "description": "Get full status of a task. Requires scope: read.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "task_respond",
        "description": "Respond to a waiting_input task. Requires scope: task:write.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "response": {"type": "string"},
            },
            "required": ["task_id", "response"],
        },
    },
    {
        "name": "task_cancel",
        "description": "Cancel a task. Requires scope: task:write.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "task_retry",
        "description": "Retry a failed or cancelled task. Requires scope: task:write.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
]


# ── Main dispatch ─────────────────────────────────────────────────────────────


@router.post("")
async def mcp_dispatch(
    request: Request,
    db: Session = Depends(get_session),
) -> dict:
    """Single HTTP endpoint for all MCP JSON-RPC calls."""
    try:
        body = await request.json()
    except Exception:
        return _err(None, -32700, "Parse error")

    rpc_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})

    if body.get("jsonrpc") != "2.0":
        return _err(rpc_id, -32600, "Invalid Request: jsonrpc must be '2.0'")

    # Auth — all methods except ping require a token
    scopes: set[str] = set()
    if method != "ping":
        try:
            scopes = _get_mcp_token(request, db)
        except HTTPException as exc:
            return _err(rpc_id, -32001, exc.detail)

    try:
        result = _dispatch(method, params, scopes, db)
    except HTTPException as exc:
        return _err(rpc_id, -32000, exc.detail)
    except KeyError as exc:
        return _err(rpc_id, -32602, f"Missing param: {exc}")
    except Exception as exc:  # noqa: BLE001
        return _err(rpc_id, -32000, str(exc))

    return _ok(rpc_id, result)


def _dispatch(method: str, params: dict, scopes: set[str], db: Session) -> Any:
    if method == "ping":
        return {"pong": True, "version": _VERSION}

    if method == "tools/list":
        return {"tools": _TOOLS}

    if method == "tools/call":
        name = params.get("name") or params.get("tool")
        args = params.get("arguments") or params.get("params") or {}
        return _dispatch(name, args, scopes, db)

    if method == "project_list":
        _require_scope(scopes, "read")
        return proj_tools.project_list(db)

    if method == "project_get":
        _require_scope(scopes, "read")
        return proj_tools.project_get(db, params["slug"])

    if method == "task_list":
        _require_scope(scopes, "read")
        return task_tools.task_list(db, params["project_slug"])

    if method == "task_create":
        _require_scope(scopes, "task:create")
        return task_tools.task_create(
            db,
            params["project_slug"],
            params["title"],
            params.get("description"),
        )

    if method == "task_status":
        _require_scope(scopes, "read")
        return task_tools.task_status(db, int(params["task_id"]))

    if method == "task_respond":
        _require_scope(scopes, "task:write")
        return task_tools.task_respond(db, int(params["task_id"]), params["response"])

    if method == "task_cancel":
        _require_scope(scopes, "task:write")
        return task_tools.task_cancel(db, int(params["task_id"]))

    if method == "task_retry":
        _require_scope(scopes, "task:write")
        return task_tools.task_retry(db, int(params["task_id"]))

    raise HTTPException(status_code=404, detail=f"Unknown method: {method}")
