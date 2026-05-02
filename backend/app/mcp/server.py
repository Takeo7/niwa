"""MCP HTTP server — JSON-RPC 2.0 over HTTP for Niwa tools (Phase 7, MCP-02).

Transport: HTTP POST /mcp (request/response, no streaming).
Authentication: Bearer token required (NIWA_MCP_TOKEN env var or API token).

MCP protocol:
    Request:  {"jsonrpc": "2.0", "id": ..., "method": "...", "params": {...}}
    Response: {"jsonrpc": "2.0", "id": ..., "result": ...}
              {"jsonrpc": "2.0", "id": ..., "error": {"code": ..., "message": ...}}

Supported methods:
    initialize                   → MCP handshake metadata
    ping                         → {pong: true, version: str}
    tools/list                   → list of tool definitions
    tools/call {name, arguments} → tool result

Tool scope mapping (API token scopes):
    read        → project_list, project_get, task_status, task_list,
                  deployment_status
    task:create → task_create, task_attach
    task:write  → task_respond, task_cancel, task_retry
    deploy      → deploy_trigger
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..api.deps import get_session
from ..auth.token_store import validate_token
from ..services.audit import log_event
from .tools import deployments as deploy_tools
from .tools import projects as proj_tools
from .tools import pulls as pull_tools
from .tools import tasks as task_tools

router = APIRouter(prefix="/mcp", tags=["mcp"])

_VERSION = "1.0.0"

# ── Auth ───────────────────────────────────────────────────────────────────────


def _get_mcp_token(request: Request, db: Session) -> tuple[set[str], str]:
    """Return (scopes, actor_id) for the Bearer token. actor_id = 'env' or token id str."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")

    raw = auth[7:]

    env_token = os.environ.get("NIWA_MCP_TOKEN")
    if env_token and raw == env_token:
        return ({"read", "task:create", "task:write", "merge", "deploy", "admin"}, "env")

    token = validate_token(db, raw)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked token")

    return (set(token.scopes.split()), str(token.id))


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


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _http_to_rpc_error(exc: HTTPException) -> JsonRpcError:
    detail = str(exc.detail)
    code_by_status = {
        400: -32602,
        401: -32001,
        403: -32003,
        404: -32004,
        409: -32009,
        413: -32013,
        502: -32052,
        503: -32053,
        504: -32054,
    }
    return JsonRpcError(code_by_status.get(exc.status_code, -32000), detail)


def _audit_payload(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "tools/call":
        name = params.get("name") or params.get("tool") or ""
        args = dict(params.get("arguments") or params.get("params") or {})
        return {"tool": name, "arguments": _redact_mcp_args(name, args)}
    return {"params": _redact_mcp_args(method, dict(params))}


def _redact_mcp_args(method: str, args: dict[str, Any]) -> dict[str, Any]:
    if method == "task_attach":
        redacted = dict(args)
        if "content" in redacted:
            redacted["content"] = "[REDACTED_ATTACHMENT_CONTENT]"
        return redacted
    return args


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
        "name": "task_attach",
        "description": "Attach text/base64 content to a task. Requires scope: task:create.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "filename": {"type": "string"},
                "content": {"type": "string"},
                "content_type": {"type": "string"},
                "encoding": {
                    "type": "string",
                    "enum": ["text", "base64"],
                    "default": "text",
                },
            },
            "required": ["task_id", "filename", "content"],
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
    {
        "name": "pull_list",
        "description": "List open pull requests for a project. Requires scope: read.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_slug": {"type": "string"}},
            "required": ["project_slug"],
        },
    },
    {
        "name": "pull_merge",
        "description": "Merge a pull request. Requires scope: merge.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_slug": {"type": "string"},
                "number": {"type": "integer"},
                "method": {
                    "type": "string",
                    "enum": ["squash", "merge", "rebase"],
                    "default": "squash",
                },
            },
            "required": ["project_slug", "number"],
        },
    },
    {
        "name": "deploy_trigger",
        "description": "Trigger a deployment for a project. Requires scope: deploy.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_slug": {"type": "string"}},
            "required": ["project_slug"],
        },
    },
    {
        "name": "deployment_status",
        "description": "Get latest project deployment or one deployment by id. Requires scope: read.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "deployment_id": {"type": "integer"},
                "project_slug": {"type": "string"},
            },
            "anyOf": [
                {"required": ["deployment_id"]},
                {"required": ["project_slug"]},
            ],
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

    # Auth — handshake/health methods are public; all tools require a token.
    scopes: set[str] = set()
    actor_id: str | None = None
    if method not in {"initialize", "ping"}:
        try:
            scopes, actor_id = _get_mcp_token(request, db)
        except HTTPException as exc:
            return _err(rpc_id, -32001, exc.detail)

    try:
        result = _dispatch(method, params, scopes, db)
    except JsonRpcError as exc:
        return _err(rpc_id, exc.code, exc.message)
    except HTTPException as exc:
        rpc_error = _http_to_rpc_error(exc)
        return _err(rpc_id, rpc_error.code, rpc_error.message)
    except KeyError as exc:
        return _err(rpc_id, -32602, f"Missing param: {exc}")
    except Exception as exc:  # noqa: BLE001
        return _err(rpc_id, -32000, str(exc))

    # Audit log: write actions only.
    write_actions = {
        "task_create",
        "task_attach",
        "task_respond",
        "task_cancel",
        "task_retry",
        "pull_merge",
        "deploy_trigger",
    }
    effective_method = method
    if method == "tools/call":
        effective_method = params.get("name") or params.get("tool") or ""
    if effective_method in write_actions:
        ip = request.client.host if request.client else None
        log_event(
            db,
            actor_type="mcp",
            actor_id=actor_id,
            action=f"mcp.{effective_method}",
            ip_address=ip,
            payload=_audit_payload(method, params),
        )

    return _ok(rpc_id, result)


def _dispatch(method: str, params: dict, scopes: set[str], db: Session) -> Any:
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "niwa", "version": _VERSION},
            "capabilities": {"tools": {"listChanged": False}},
        }

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

    if method == "task_attach":
        _require_scope(scopes, "task:create")
        return task_tools.task_attach(
            db,
            int(params["task_id"]),
            params["filename"],
            params["content"],
            content_type=params.get("content_type"),
            encoding=params.get("encoding", "text"),
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

    if method == "pull_list":
        _require_scope(scopes, "read")
        return pull_tools.pull_list(db, params["project_slug"])

    if method == "pull_merge":
        _require_scope(scopes, "merge")
        return pull_tools.pull_merge(
            db,
            params["project_slug"],
            int(params["number"]),
            params.get("method", "squash"),
        )

    if method == "deploy_trigger":
        _require_scope(scopes, "deploy")
        return deploy_tools.deploy_trigger(db, params["project_slug"])

    if method == "deployment_status":
        _require_scope(scopes, "read")
        return deploy_tools.deployment_status(
            db,
            deployment_id=(
                int(params["deployment_id"])
                if params.get("deployment_id") is not None
                else None
            ),
            project_slug=params.get("project_slug"),
        )

    raise JsonRpcError(-32601, f"Method not found: {method}")
