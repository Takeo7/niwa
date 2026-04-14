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


def call_anthropic(model: str, api_key: str, messages: list,
                   tools: list | None, system: str,
                   timeout: float) -> dict:
    """Call Anthropic Messages API.  Returns the parsed response dict.

    Exposed as module-level (not underscore-prefixed) so tests can
    monkey-patch it without reaching into private names.

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

    # ── TODO: LLM conversation loop (steps 2-5) ─────────────────
    raise NotImplementedError(
        "LLM conversation loop not yet implemented (PR-08 step 2+)."
    )
