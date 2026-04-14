"""Assistant service — PR-08 Niwa v0.2.

Unified conversational layer.  Uses an LLM with function calling
to interpret user intent and invoke Niwa domain tools.

The LLM here is a *conversational brain* — distinct from the backend
adapters (PR-04/07) which are task execution engines.  The SPEC rule
"no LLM routing" applies to task routing in ``routing_service.decide()``,
not to conversational intent interpretation here.

Contract
--------
``assistant_turn()`` is the single public entry point.

Input:  session_id, project_id, message, channel, metadata, conn.
Output: dict with keys ``assistant_message``, ``actions_taken``,
        ``task_ids``, ``approval_ids``, ``run_ids``.
        On error the dict also contains ``error`` (code) and
        ``message`` (human-readable).

The function is synchronous with a hard 30 s deadline.  It always
persists the user message and the assistant response (even on error)
in ``chat_messages``.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any

import approval_service
import state_machines

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

MAX_TOOL_ITERATIONS = 8
TURN_TIMEOUT_S = 30
_LLM_MAX_TOKENS = 1024
_HISTORY_LIMIT = 20  # max messages loaded from chat_messages


# ── Helpers ──────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _make_result(
    *,
    assistant_message: str = "",
    actions_taken: list | None = None,
    task_ids: list | None = None,
    approval_ids: list | None = None,
    run_ids: list | None = None,
    error: str | None = None,
    message: str | None = None,
    session_id: str | None = None,
) -> dict:
    """Build a response dict that always satisfies the output contract."""
    d: dict[str, Any] = {
        "assistant_message": assistant_message,
        "actions_taken": actions_taken or [],
        "task_ids": task_ids or [],
        "approval_ids": approval_ids or [],
        "run_ids": run_ids or [],
    }
    if session_id is not None:
        d["session_id"] = session_id
    if error is not None:
        d["error"] = error
    if message is not None:
        d["message"] = message
    return d


def _ensure_session(session_id: str, channel: str,
                    metadata: dict | None, conn) -> str:
    """Ensure a chat_session row exists.  Returns canonical session id.

    - channel="web": session_id is a chat_sessions.id.
    - channel="openclaw": session_id is the external identifier;
      Niwa maps it to a chat_sessions row via external_ref.
    """
    metadata = metadata or {}

    if channel == "openclaw":
        external_ref = metadata.get("external_ref") or session_id
        row = conn.execute(
            "SELECT id FROM chat_sessions WHERE external_ref = ?",
            (external_ref,),
        ).fetchone()
        if row:
            return row["id"]
        new_id = str(uuid.uuid4())
        now = _now_iso()
        conn.execute(
            "INSERT INTO chat_sessions "
            "(id, title, external_ref, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (new_id, "OpenClaw session", external_ref, now, now),
        )
        conn.commit()
        return new_id

    # channel="web" (default)
    row = conn.execute(
        "SELECT id FROM chat_sessions WHERE id = ?", (session_id,),
    ).fetchone()
    if row:
        return row["id"]

    now = _now_iso()
    conn.execute(
        "INSERT INTO chat_sessions (id, title, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (session_id, "Nueva conversación", now, now),
    )
    conn.commit()
    return session_id


def _persist_user_message(session_id: str, content: str, conn) -> str:
    """Write the user message to chat_messages.  Returns the msg id."""
    msg_id = str(uuid.uuid4())
    now = _now_iso()
    conn.execute(
        "INSERT INTO chat_messages "
        "(id, session_id, role, content, status, created_at) "
        "VALUES (?, ?, 'user', ?, 'done', ?)",
        (msg_id, session_id, content, now),
    )
    # Update session title from first user message
    cnt = conn.execute(
        "SELECT COUNT(*) as cnt FROM chat_messages "
        "WHERE session_id = ? AND role = 'user'",
        (session_id,),
    ).fetchone()
    if cnt and cnt["cnt"] <= 1:
        title = content[:60] + ("..." if len(content) > 60 else "")
        conn.execute(
            "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, now, session_id),
        )
    else:
        conn.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
    conn.commit()
    return msg_id


def _persist_assistant_message(session_id: str, content: str, conn,
                               *, task_id: str | None = None) -> str:
    """Write the assistant response to chat_messages.  Returns msg id."""
    msg_id = str(uuid.uuid4())
    now = _now_iso()
    conn.execute(
        "INSERT INTO chat_messages "
        "(id, session_id, role, content, task_id, status, created_at) "
        "VALUES (?, ?, 'assistant', ?, ?, 'done', ?)",
        (msg_id, session_id, content, task_id, now),
    )
    conn.commit()
    return msg_id


# ── Domain tools ─────────────────────────────────────────────────────
# Each tool receives (conn, project_id, params) and returns a dict.
# Public API — reused by HTTP endpoints (PR-09) and MCP server.


def tool_task_list(conn, project_id, params):
    """List tasks for the current project."""
    status = params.get("status")
    limit = min(params.get("limit", 20), 50)

    clauses = ["project_id = ?"]
    args: list = [project_id]
    if status:
        clauses.append("status = ?")
        args.append(status)

    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT id, title, status, priority, created_at, updated_at "
        f"FROM tasks WHERE {where} ORDER BY updated_at DESC LIMIT ?",
        args + [limit],
    ).fetchall()
    return {"tasks": [dict(r) for r in rows], "count": len(rows)}


def tool_task_get(conn, project_id, params):
    """Get detailed information about a single task."""
    task_id = params.get("task_id")
    if not task_id:
        return {"error": "task_id is required"}
    row = conn.execute(
        "SELECT id, title, description, status, priority, project_id, "
        "source, notes, created_at, updated_at, current_run_id, "
        "approval_required "
        "FROM tasks WHERE id = ?",
        (task_id,),
    ).fetchone()
    if not row:
        return {"error": "task_not_found", "task_id": task_id}
    return dict(row)


def tool_task_create(conn, project_id, params):
    """Create a new task in the current project."""
    title = params.get("title", "").strip()
    if not title:
        return {"error": "title is required"}
    description = params.get("description", "")
    priority = params.get("priority", "media")
    if priority not in ("baja", "media", "alta", "critica"):
        priority = "media"

    task_id = str(uuid.uuid4())
    now = _now_iso()
    conn.execute(
        "INSERT INTO tasks "
        "(id, title, description, area, project_id, status, priority, "
        " source, created_at, updated_at) "
        "VALUES (?, ?, ?, 'proyecto', ?, 'pendiente', ?, 'assistant', ?, ?)",
        (task_id, title, description, project_id, priority, now, now),
    )
    conn.execute(
        "INSERT INTO task_events (id, task_id, type, payload_json, created_at) "
        "VALUES (?, ?, 'created', ?, ?)",
        (str(uuid.uuid4()), task_id,
         json.dumps({"source": "assistant_turn", "title": title}), now),
    )
    conn.commit()
    return {"task_id": task_id, "status": "pendiente"}


def tool_task_cancel(conn, project_id, params):
    """Cancel a task (transition to archivada) and its active run."""
    task_id = params.get("task_id")
    if not task_id:
        return {"error": "task_id is required"}

    task = conn.execute(
        "SELECT * FROM tasks WHERE id = ?", (task_id,),
    ).fetchone()
    if not task:
        return {"error": "task_not_found", "task_id": task_id}

    old_status = task["status"]
    if not state_machines.can_transition_task(old_status, "archivada"):
        return {
            "error": "cannot_cancel",
            "task_id": task_id,
            "current_status": old_status,
        }

    now = _now_iso()
    conn.execute(
        "UPDATE tasks SET status = 'archivada', updated_at = ? WHERE id = ?",
        (now, task_id),
    )
    conn.execute(
        "INSERT INTO task_events (id, task_id, type, payload_json, created_at) "
        "VALUES (?, ?, 'status_changed', ?, ?)",
        (str(uuid.uuid4()), task_id,
         json.dumps({"old_status": old_status, "new_status": "archivada",
                     "source": "assistant_turn"}), now),
    )

    # Cancel active run if any
    cancelled_run_ids: list[str] = []
    current_run_id = task["current_run_id"]
    if current_run_id:
        run = conn.execute(
            "SELECT id, status FROM backend_runs WHERE id = ?",
            (current_run_id,),
        ).fetchone()
        if run:
            rs = run["status"]
            target = (
                "cancelled" if rs in ("running", "waiting_input") else
                "failed" if rs in ("queued", "starting") else
                "rejected" if rs == "waiting_approval" else
                None
            )
            if target and state_machines.can_transition_run(rs, target):
                conn.execute(
                    "UPDATE backend_runs SET status = ?, updated_at = ? "
                    "WHERE id = ?",
                    (target, now, run["id"]),
                )
                cancelled_run_ids.append(run["id"])

    conn.commit()
    return {
        "task_id": task_id,
        "status": "archivada",
        "cancelled_run_ids": cancelled_run_ids,
    }


def tool_task_resume(conn, project_id, params):
    """Resume a blocked or waiting task (transition to pendiente).

    Mitigates Bug 8: if the last run has ``session_handle IS NULL``,
    a resume would fail with ``--resume None``.  We detect this and
    return an error so the LLM can explain instead of silently
    queueing a doomed re-execution.
    """
    task_id = params.get("task_id")
    if not task_id:
        return {"error": "task_id is required"}

    task = conn.execute(
        "SELECT * FROM tasks WHERE id = ?", (task_id,),
    ).fetchone()
    if not task:
        return {"error": "task_not_found", "task_id": task_id}

    old_status = task["status"]
    if not state_machines.can_transition_task(old_status, "pendiente"):
        return {
            "error": "cannot_resume",
            "task_id": task_id,
            "current_status": old_status,
        }

    # Bug 8 mitigation: check session_handle on latest run
    current_run_id = task["current_run_id"]
    if current_run_id:
        run = conn.execute(
            "SELECT session_handle, status FROM backend_runs WHERE id = ?",
            (current_run_id,),
        ).fetchone()
        if run and run["session_handle"] is None:
            # The run failed before emitting a session_id — resume would
            # attempt --resume None, which is broken.  See BUGS-FOUND Bug 8.
            return {
                "error": "session_handle_missing",
                "task_id": task_id,
                "run_id": current_run_id,
                "message": (
                    "Cannot resume: the last execution failed before "
                    "establishing a session. The task must be re-created "
                    "or the run retried from scratch."
                ),
            }

    now = _now_iso()
    conn.execute(
        "UPDATE tasks SET status = 'pendiente', updated_at = ? WHERE id = ?",
        (now, task_id),
    )
    conn.execute(
        "INSERT INTO task_events (id, task_id, type, payload_json, created_at) "
        "VALUES (?, ?, 'status_changed', ?, ?)",
        (str(uuid.uuid4()), task_id,
         json.dumps({"old_status": old_status, "new_status": "pendiente",
                     "source": "assistant_turn"}), now),
    )
    conn.commit()
    return {"task_id": task_id, "status": "pendiente"}


def tool_approval_list(conn, project_id, params):
    """List approvals, optionally filtered by status or task_id."""
    status = params.get("status")
    task_id = params.get("task_id")
    approvals = approval_service.list_approvals(
        conn, status=status, task_id=task_id,
    )
    return {"approvals": approvals, "count": len(approvals)}


def tool_approval_respond(conn, project_id, params):
    """Respond to a pending approval (approve or reject)."""
    approval_id = params.get("approval_id")
    decision = params.get("decision")
    if not approval_id:
        return {"error": "approval_id is required"}
    if decision not in ("approved", "rejected"):
        return {"error": "decision must be 'approved' or 'rejected'"}

    note = params.get("note", "")
    try:
        result = approval_service.resolve_approval(
            approval_id, decision, "assistant",
            conn, resolution_note=note,
        )
        return result
    except LookupError as exc:
        return {"error": "approval_not_found", "message": str(exc)}
    except ValueError as exc:
        return {"error": "invalid_operation", "message": str(exc)}


def tool_run_tail(conn, project_id, params):
    """Get recent events from a backend run."""
    run_id = params.get("run_id")
    if not run_id:
        return {"error": "run_id is required"}
    limit = min(params.get("limit", 20), 50)

    run = conn.execute(
        "SELECT id, task_id, status, started_at, finished_at, "
        "outcome, error_code "
        "FROM backend_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if not run:
        return {"error": "run_not_found", "run_id": run_id}

    rows = conn.execute(
        "SELECT id, event_type, message, created_at "
        "FROM backend_run_events WHERE backend_run_id = ? "
        "ORDER BY created_at DESC LIMIT ?",
        (run_id, limit),
    ).fetchall()

    return {
        "run": dict(run),
        "events": [dict(r) for r in reversed(rows)],
    }


def tool_run_explain(conn, project_id, params):
    """Explain the routing decision and run history for a task."""
    task_id = params.get("task_id")
    if not task_id:
        return {"error": "task_id is required"}

    decision = conn.execute(
        "SELECT * FROM routing_decisions WHERE task_id = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    if not decision:
        return {"task_id": task_id,
                "message": "No routing decision found for this task."}

    d = dict(decision)
    profile = conn.execute(
        "SELECT slug, display_name FROM backend_profiles WHERE id = ?",
        (d.get("selected_profile_id"),),
    ).fetchone()

    runs = conn.execute(
        "SELECT id, status, backend_kind, started_at, finished_at, "
        "outcome, error_code "
        "FROM backend_runs WHERE routing_decision_id = ? "
        "ORDER BY created_at",
        (d["id"],),
    ).fetchall()

    return {
        "task_id": task_id,
        "decision_id": d["id"],
        "selected_backend": dict(profile) if profile else None,
        "reason_summary": d.get("reason_summary_json"),
        "matched_rules": d.get("matched_rules_json"),
        "runs": [dict(r) for r in runs],
    }


def tool_project_context(conn, project_id, params):
    """Get project metadata, task summary, and recent activity."""
    project = conn.execute(
        "SELECT id, name, description, area, directory, url "
        "FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    if not project:
        return {"error": "project_not_found", "project_id": project_id}

    status_counts = conn.execute(
        "SELECT status, COUNT(*) as count FROM tasks "
        "WHERE project_id = ? GROUP BY status",
        (project_id,),
    ).fetchall()

    recent = conn.execute(
        "SELECT id, title, status, priority, updated_at FROM tasks "
        "WHERE project_id = ? ORDER BY updated_at DESC LIMIT 10",
        (project_id,),
    ).fetchall()

    pending_approvals = conn.execute(
        "SELECT COUNT(*) as count FROM approvals a "
        "JOIN tasks t ON a.task_id = t.id "
        "WHERE t.project_id = ? AND a.status = 'pending'",
        (project_id,),
    ).fetchone()

    return {
        "project": dict(project),
        "task_summary": {r["status"]: r["count"] for r in status_counts},
        "recent_tasks": [dict(r) for r in recent],
        "pending_approvals": pending_approvals["count"] if pending_approvals else 0,
    }


# Tool dispatch table (name → function)
# Functions are public (tool_*) so HTTP endpoints and MCP servers can
# reuse them.  Signature: (conn, project_id, params) → dict.
TOOL_DISPATCH: dict[str, Any] = {
    "task_list": tool_task_list,
    "task_get": tool_task_get,
    "task_create": tool_task_create,
    "task_cancel": tool_task_cancel,
    "task_resume": tool_task_resume,
    "approval_list": tool_approval_list,
    "approval_respond": tool_approval_respond,
    "run_tail": tool_run_tail,
    "run_explain": tool_run_explain,
    "project_context": tool_project_context,
}


# ── Tool schemas (Anthropic function calling format) ─────────────────

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "task_list",
        "description": "List tasks for the current project, optionally filtered by status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by task status.",
                    "enum": ["inbox", "pendiente", "en_progreso", "bloqueada",
                             "revision", "waiting_input", "hecha", "archivada"],
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 20, max 50).",
                },
            },
        },
    },
    {
        "name": "task_get",
        "description": "Get detailed information about a specific task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID."},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "task_create",
        "description": "Create a new task. It will be executed by the backend engine asynchronously.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short task title."},
                "description": {"type": "string", "description": "Detailed description."},
                "priority": {
                    "type": "string",
                    "enum": ["baja", "media", "alta", "critica"],
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "task_cancel",
        "description": "Cancel a task and its active run (archives the task).",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID to cancel."},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "task_resume",
        "description": "Resume a blocked or waiting task (transitions to pendiente).",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID to resume."},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "approval_list",
        "description": "List approval requests, optionally filtered.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "approved", "rejected"],
                },
                "task_id": {"type": "string", "description": "Filter by task."},
            },
        },
    },
    {
        "name": "approval_respond",
        "description": "Respond to a pending approval (approve or reject).",
        "input_schema": {
            "type": "object",
            "properties": {
                "approval_id": {"type": "string"},
                "decision": {"type": "string", "enum": ["approved", "rejected"]},
                "note": {"type": "string", "description": "Optional note."},
            },
            "required": ["approval_id", "decision"],
        },
    },
    {
        "name": "run_tail",
        "description": "Get recent events from a backend execution run.",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "limit": {"type": "integer", "description": "Max events (default 20)."},
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "run_explain",
        "description": "Explain routing decision and execution history for a task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "project_context",
        "description": "Get project metadata, task summary, and recent activity.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


# ── ID collection helper ────────────────────────────────────────────

def _collect_ids(tool_name: str, result: Any,
                 task_ids: set, approval_ids: set, run_ids: set) -> None:
    """Extract entity IDs from a tool result into collector sets."""
    if not isinstance(result, dict):
        return

    if "task_id" in result:
        task_ids.add(result["task_id"])
    if "tasks" in result and isinstance(result["tasks"], list):
        for t in result["tasks"]:
            if isinstance(t, dict) and "id" in t:
                task_ids.add(t["id"])

    if "approval_id" in result:
        approval_ids.add(result["approval_id"])
    if "approvals" in result and isinstance(result["approvals"], list):
        for a in result["approvals"]:
            if isinstance(a, dict) and "id" in a:
                approval_ids.add(a["id"])
    if tool_name == "approval_respond" and "id" in result:
        approval_ids.add(result["id"])

    if "run_id" in result:
        run_ids.add(result["run_id"])
    if "cancelled_run_ids" in result:
        run_ids.update(result["cancelled_run_ids"])
    if "runs" in result and isinstance(result["runs"], list):
        for r in result["runs"]:
            if isinstance(r, dict) and "id" in r:
                run_ids.add(r["id"])
    if "run" in result and isinstance(result["run"], dict) and "id" in result["run"]:
        run_ids.add(result["run"]["id"])


# ── Routing mode ─────────────────────────────────────────────────────

def _get_routing_mode(conn) -> str | None:
    """Read routing_mode from settings.  Returns None if absent."""
    row = conn.execute(
        "SELECT value FROM settings WHERE key = 'routing_mode'",
    ).fetchone()
    return row["value"] if row else None


# ── LLM config & API ────────────────────────────────────────────────

def _get_llm_config(conn) -> tuple[str, str]:
    """Resolve model name and API key from settings + environment.

    Model priority (Decision 1 PR-08):
      1. ``agent.assistant`` JSON → ``model``
      2. ``agent.chat`` JSON → ``model``
      3. ``svc.llm.anthropic.default_model``
      4. ``"claude-haiku-4-5"``

    API key priority:
      1. ``svc.llm.anthropic.api_key``
      2. ``int.llm_api_key`` (legacy)
      3. env ``ANTHROPIC_API_KEY``
      4. env ``NIWA_LLM_API_KEY``

    Returns (model, api_key).  api_key may be empty.
    """
    settings: dict[str, str] = {}
    for row in conn.execute("SELECT key, value FROM settings").fetchall():
        settings[row["key"]] = row["value"]

    # Model
    model = None
    for agent_key in ("agent.assistant", "agent.chat"):
        raw = settings.get(agent_key)
        if raw:
            try:
                model = json.loads(raw).get("model")
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
        if model:
            break

    if not model:
        cmd = settings.get("int.llm_command_chat", "")
        if "--model " in cmd:
            model = cmd.split("--model ")[-1].split()[0]

    if not model:
        model = settings.get("svc.llm.anthropic.default_model")

    if not model:
        model = "claude-haiku-4-5"

    # API key
    api_key = (
        settings.get("svc.llm.anthropic.api_key")
        or settings.get("int.llm_api_key")
        or os.environ.get("ANTHROPIC_API_KEY", "")
        or os.environ.get("NIWA_LLM_API_KEY", "")
    )

    return model, api_key


def _build_system_prompt(project_name: str, project_id: str) -> str:
    return (
        f'You are the Niwa project assistant for "{project_name}" '
        f"(project ID: {project_id}).\n\n"
        "Niwa is a task management and automated execution system. "
        "You help the user manage tasks, check execution status, "
        "handle approvals, and answer questions about their project.\n\n"
        "Guidelines:\n"
        "- Use the tools to fulfill requests. Do not guess at data.\n"
        "- To run code or automate work, create a task with task_create. "
        "Tasks are executed by the backend engine asynchronously.\n"
        "- For status queries, use task_list, task_get, run_tail, "
        "or run_explain.\n"
        "- Respond in the same language the user writes in.\n"
        "- Be concise.\n"
    )


def _call_anthropic(model: str, api_key: str, messages: list,
                    tools: list | None, system: str,
                    timeout: float) -> dict:
    """Call Anthropic Messages API.  Returns the parsed response dict.

    Private — callers use ``assistant_turn(llm_caller=...)`` for DI.

    Raises ``urllib.error.HTTPError``, ``urllib.error.URLError``,
    or ``TimeoutError`` on failure.
    """
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": _LLM_MAX_TOKENS,
        "system": system,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=max(timeout, 1)) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── Public entry point ───────────────────────────────────────────────

def assistant_turn(
    *,
    session_id: str,
    project_id: str,
    message: str,
    channel: str,
    metadata: dict[str, Any] | None = None,
    conn,
    llm_caller=None,
) -> dict[str, Any]:
    """Process one conversational turn.

    Parameters
    ----------
    session_id : str
        Chat session id (FK to chat_sessions.id for web, external ref
        for openclaw — mapped internally via ``_ensure_session``).
        Distinct from ``backend_runs.session_handle`` (CLI session).
    project_id : str
        Project scope (required — caller must resolve before calling).
    message : str
        User message text.
    channel : str
        Origin channel: ``"web"`` or ``"openclaw"``.
    metadata : dict | None
        Channel-specific data (e.g. ``external_ref`` for openclaw).
    conn
        sqlite3 connection with row_factory = sqlite3.Row.
    llm_caller : callable | None
        Dependency injection for the LLM API call.  Signature must
        match ``_call_anthropic(model, api_key, messages, tools,
        system, timeout) -> dict``.  Defaults to the real Anthropic
        API implementation.

    Returns
    -------
    dict satisfying the PR-08 output contract (see module docstring).
    """
    # ── Validate inputs ──────────────────────────────────────────
    if not session_id:
        return _make_result(
            error="missing_session_id",
            message="session_id is required.",
        )
    if not project_id:
        return _make_result(
            error="missing_project_id",
            message="project_id is required.",
        )
    if not message or not message.strip():
        return _make_result(
            error="empty_message",
            message="message cannot be empty.",
        )

    # ── Resolve session ──────────────────────────────────────────
    canonical_sid = _ensure_session(
        session_id, channel or "web", metadata, conn,
    )

    # ── Persist user message (always, even if we error out) ──────
    _persist_user_message(canonical_sid, message.strip(), conn)

    # ── Check routing_mode ───────────────────────────────────────
    routing_mode = _get_routing_mode(conn)
    if routing_mode != "v02":
        error_text = (
            f"assistant_turn requiere routing_mode='v02'. "
            f"Modo actual: {routing_mode!r}. "
            f"Configura routing_mode='v02' en settings o usa el "
            f"flujo de chat legacy."
        )
        _persist_assistant_message(canonical_sid, error_text, conn)
        return _make_result(
            session_id=canonical_sid,
            assistant_message=error_text,
            error="routing_mode_mismatch",
            message=error_text,
        )

    # ── Validate project exists ──────────────────────────────────
    project = conn.execute(
        "SELECT id, name FROM projects WHERE id = ?", (project_id,),
    ).fetchone()
    if not project:
        error_text = f"Proyecto no encontrado: {project_id!r}."
        _persist_assistant_message(canonical_sid, error_text, conn)
        return _make_result(
            session_id=canonical_sid,
            assistant_message=error_text,
            error="project_not_found",
            message=error_text,
        )

    # ── Get LLM config ───────────────────────────────────────────
    model, api_key = _get_llm_config(conn)
    if not api_key:
        error_text = (
            "No hay API key configurada para el LLM conversacional. "
            "Configura svc.llm.anthropic.api_key en settings o "
            "ANTHROPIC_API_KEY en el entorno."
        )
        _persist_assistant_message(canonical_sid, error_text, conn)
        return _make_result(
            session_id=canonical_sid,
            assistant_message=error_text,
            error="llm_not_configured",
            message=error_text,
        )

    # ── Load conversation history ────────────────────────────────
    history_rows = conn.execute(
        "SELECT role, content FROM chat_messages "
        "WHERE session_id = ? AND status = 'done' AND content != '' "
        "ORDER BY created_at ASC",
        (canonical_sid,),
    ).fetchall()

    messages: list[dict] = []
    for h in [dict(r) for r in history_rows[-_HISTORY_LIMIT:]]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message.strip()})

    system = _build_system_prompt(project["name"], project_id)

    # ── LLM conversation loop ────────────────────────────────────
    deadline = time.monotonic() + TURN_TIMEOUT_S
    _do_call = llm_caller or _call_anthropic
    actions_taken: list[dict] = []
    task_ids: set[str] = set()
    approval_ids: set[str] = set()
    run_ids: set[str] = set()
    assistant_text = ""

    try:
        for _round in range(MAX_TOOL_ITERATIONS):
            remaining = deadline - time.monotonic()
            if remaining < 3:
                logger.warning(
                    "assistant_turn: timeout approaching (%.1fs left), "
                    "stopping after %d rounds", remaining, _round,
                )
                if not assistant_text:
                    assistant_text = (
                        "Se agotó el tiempo de procesamiento. "
                        "Intenta de nuevo."
                    )
                break

            response = _do_call(
                model, api_key, messages, TOOL_DEFINITIONS,
                system, timeout=min(remaining - 1, 25),
            )

            # Parse response content blocks
            text_parts: list[str] = []
            tool_uses: list[dict] = []
            for block in response.get("content", []):
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block["text"])
                elif btype == "tool_use":
                    tool_uses.append(block)

            if text_parts:
                assistant_text = "\n".join(text_parts)

            if not tool_uses:
                break  # No tool calls — conversation complete

            # Append assistant message (with tool_use blocks) to history
            messages.append({
                "role": "assistant",
                "content": response["content"],
            })

            # Execute each tool and collect results
            tool_results: list[dict] = []
            for tu in tool_uses:
                tool_name = tu["name"]
                tool_input = tu.get("input", {})
                tool_id = tu["id"]

                fn = TOOL_DISPATCH.get(tool_name)
                if fn is None:
                    result = {"error": f"Unknown tool: {tool_name}"}
                else:
                    try:
                        result = fn(conn, project_id, tool_input)
                    except Exception as exc:
                        logger.exception("Tool %s raised: %s", tool_name, exc)
                        result = {"error": f"Tool error: {exc}"}

                _collect_ids(
                    tool_name, result, task_ids, approval_ids, run_ids,
                )
                actions_taken.append({
                    "tool": tool_name,
                    "input": tool_input,
                    "result": result,
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": json.dumps(
                        result, ensure_ascii=False, default=str,
                    ),
                })

            # Send tool results back to the LLM
            messages.append({"role": "user", "content": tool_results})

    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        logger.error("Anthropic API error %s: %s", exc.code, body)
        assistant_text = (
            f"Error al comunicar con el modelo de lenguaje "
            f"(HTTP {exc.code}). Intenta de nuevo."
        )
    except urllib.error.URLError as exc:
        logger.error("Anthropic API connection error: %s", exc.reason)
        assistant_text = (
            "No se pudo conectar con el modelo de lenguaje. "
            "Verifica la configuración de red."
        )
    except (TimeoutError, OSError) as exc:
        if "timed out" in str(exc).lower() or isinstance(exc, TimeoutError):
            logger.error("assistant_turn: socket timeout: %s", exc)
            assistant_text = (
                "Se agotó el tiempo de conexión con el modelo. "
                "Intenta con una solicitud más simple."
            )
        else:
            raise
    except Exception as exc:
        logger.exception("assistant_turn unexpected error: %s", exc)
        assistant_text = f"Error interno: {exc}"

    # ── Check hard timeout ───────────────────────────────────────
    elapsed = time.monotonic() - (deadline - TURN_TIMEOUT_S)
    if elapsed > TURN_TIMEOUT_S:
        logger.error(
            "assistant_turn: exceeded %ds deadline (%.1fs)",
            TURN_TIMEOUT_S, elapsed,
        )

    # ── Persist assistant message ────────────────────────────────
    if not assistant_text:
        assistant_text = "He procesado tu solicitud."

    first_task_id = next(iter(task_ids), None)
    _persist_assistant_message(
        canonical_sid, assistant_text, conn, task_id=first_task_id,
    )

    return _make_result(
        session_id=canonical_sid,
        assistant_message=assistant_text,
        actions_taken=actions_taken,
        task_ids=sorted(task_ids),
        approval_ids=sorted(approval_ids),
        run_ids=sorted(run_ids),
    )
