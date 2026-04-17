"""
Tasks MCP server — projects + tasks for Niwa

Read verbs:  task_list, task_get, project_list, project_get, pipeline_status
Write verbs: task_create, task_update_status

Backing store: /data/niwa.sqlite3 (mounted RW; reads still use mode=ro URI).
"""

import asyncio
import html
import json
import os
import sqlite3
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

DB_PATH = os.environ.get("NIWA_DB_PATH", "/data/niwa.sqlite3")

# ── PR-09: v02-assistant HTTP proxy config ───────────────────────────
# When NIWA_MCP_CONTRACT is set, the server only exposes tools listed
# in the contract JSON.  The v02-assistant tools proxy to the Niwa app
# HTTP API instead of accessing the DB directly.
_MCP_CONTRACT = os.environ.get("NIWA_MCP_CONTRACT", "")
_APP_BASE_URL = os.environ.get("NIWA_APP_URL", "http://app:8080")
_S2S_TOKEN = os.environ.get("NIWA_MCP_SERVER_TOKEN", "")

VALID_AREAS = ("personal", "empresa", "proyecto", "sistema")
VALID_STATUSES = ("inbox", "pendiente", "en_progreso", "bloqueada", "revision", "waiting_input", "hecha", "archivada")
VALID_PRIORITIES = ("baja", "media", "alta", "critica", "low", "medium", "high", "critical")

# Canonical task state machine (source of truth: niwa-app/backend/state_machines.py)
_TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    'inbox':         frozenset({'pendiente'}),
    'pendiente':     frozenset({'en_progreso', 'bloqueada', 'archivada'}),
    'en_progreso':   frozenset({'waiting_input', 'revision', 'bloqueada', 'hecha', 'archivada'}),
    'waiting_input': frozenset({'pendiente', 'archivada'}),
    'revision':      frozenset({'pendiente', 'hecha', 'archivada'}),
    'bloqueada':     frozenset({'pendiente', 'archivada'}),
    'hecha':         frozenset(),
    'archivada':     frozenset(),
}


def _assert_task_transition(from_status: str, to_status: str) -> None:
    """Raise ValueError if the task transition is not allowed."""
    allowed = _TASK_TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        raise ValueError(
            f"Invalid task transition: {from_status!r} → {to_status!r}. "
            f"Allowed from {from_status!r}: {sorted(allowed) if allowed else '(terminal state)'}"
        )

server = Server("tasks")


def _ro_conn() -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=10000")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def _rw_conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=10000")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@server.list_tools()
async def list_tools() -> list[Tool]:
    # PR-09: contract-based filtering.
    # When NIWA_MCP_CONTRACT is set, only expose tools in the contract.
    if _CONTRACT_TOOLS is not None:
        return [t for t in _V02_TOOL_DEFS if t.name in _CONTRACT_TOOLS]

    # No contract → expose legacy (v0.1) tools.
    return _LEGACY_TOOL_DEFS


# Legacy v0.1 tool definitions — preserved verbatim.
_LEGACY_TOOL_DEFS = [
        Tool(
            name="task_list",
            description="List tasks. Optional filters: status, area, project_id, limit (default 50, max 200).",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": list(VALID_STATUSES)},
                    "area": {"type": "string", "enum": list(VALID_AREAS)},
                    "project_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
            },
        ),
        Tool(
            name="task_get",
            description="Get a single task by id.",
            inputSchema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        ),
        Tool(
            name="project_list",
            description="List all projects.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="project_get",
            description="Get a single project by id.",
            inputSchema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
            },
        ),
        Tool(
            name="pipeline_status",
            description="Aggregate counts of tasks by status, plus totals.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="project_create",
            description="Create a new project. Required: name, area. Returns the created project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "area": {"type": "string", "enum": list(VALID_AREAS)},
                    "description": {"type": "string"},
                    "directory": {"type": "string", "description": "Filesystem path for the project"},
                    "url": {"type": "string", "description": "URL (repo, docs, etc.)"},
                },
                "required": ["name", "area"],
            },
        ),
        Tool(
            name="project_update",
            description="Update a project's fields. Required: project_id. Optional: name, description, directory, url, active.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "directory": {"type": "string"},
                    "url": {"type": "string", "description": "Live URL for preview (e.g. http://host:port)"},
                    "active": {"type": "boolean"},
                },
                "required": ["project_id"],
            },
        ),
        Tool(
            name="task_update",
            description="Update a task's fields. Required: task_id. Optional: title, description, project_id, priority, area, notes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "project_id": {"type": "string"},
                    "priority": {"type": "string", "enum": list(VALID_PRIORITIES)},
                    "area": {"type": "string", "enum": list(VALID_AREAS)},
                    "notes": {"type": "string"},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="task_create",
            description=(
                "Create a new task. Required: title, area. Set assigned_to_claude=true for "
                "auto-execution by the main model. Returns the created task."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "area": {"type": "string", "enum": list(VALID_AREAS)},
                    "project_id": {"type": "string"},
                    "status": {"type": "string", "enum": list(VALID_STATUSES), "default": "pendiente"},
                    "priority": {"type": "string", "enum": list(VALID_PRIORITIES), "default": "media"},
                    "description": {"type": "string"},
                    "notes": {"type": "string"},
                    "assigned_to_claude": {"type": "boolean", "default": False, "description": "Set true for auto-execution by the main model"},
                    "source": {"type": "string", "description": "Origin of the task (e.g. 'openclaw', 'mcp:tasks'). Defaults to 'mcp:tasks'."},
                },
                "required": ["title", "area"],
            },
        ),
        Tool(
            name="task_update_status",
            description=(
                "Update a task's status. Required: task_id, status. Optional: notes (appended to existing)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "status": {"type": "string", "enum": list(VALID_STATUSES)},
                    "notes": {"type": "string"},
                },
                "required": ["task_id", "status"],
            },
        ),
        Tool(
            name="project_context",
            description="Full project context in one call: metadata, active tasks, notes, decisions. Use at the start of working on a project task.",
            inputSchema={"type": "object", "properties": {"project_id": {"type": "string"}, "include_done": {"type": "boolean", "default": False}}, "required": ["project_id"]},
        ),
        Tool(
            name="task_log",
            description="Record a finding or progress update on a task (stored in task_events, not notes). kind: finding|progress|decision|warning.",
            inputSchema={"type": "object", "properties": {"task_id": {"type": "string"}, "message": {"type": "string"}, "kind": {"type": "string", "enum": ["finding","progress","decision","warning"], "default": "progress"}}, "required": ["task_id", "message"]},
        ),
        Tool(
            name="task_request_input",
            description="Formally ask the human a question before proceeding. Sets task to revision status. Use instead of just blocking.",
            inputSchema={"type": "object", "properties": {"task_id": {"type": "string"}, "question": {"type": "string"}, "context": {"type": "string"}}, "required": ["task_id", "question"]},
        ),
        Tool(
            name="web_search",
            description=(
                "Search the web for information. Uses SearXNG if configured (NIWA_SEARXNG_URL), "
                "otherwise DuckDuckGo instant answers. Returns titles, URLs, and snippets."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="memory_store",
            description=(
                "Persist a fact or preference to long-term memory. Use for cross-task knowledge: "
                "user preferences, architectural decisions, recurring patterns, learned constraints. "
                "Overwrites if same key + project_id already exists."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Short identifier, e.g. 'prefers-typescript'"},
                    "value": {"type": "string", "description": "The fact or preference to remember"},
                    "category": {
                        "type": "string",
                        "enum": ["preference", "decision", "constraint", "pattern", "general"],
                        "default": "general",
                    },
                    "project_id": {"type": "string", "description": "Scope to a project (omit for global)"},
                },
                "required": ["key", "value"],
            },
        ),
        Tool(
            name="memory_search",
            description="Search long-term memory by text. Returns matching memories ordered by recency.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to search in keys and values"},
                    "category": {"type": "string", "enum": ["preference", "decision", "constraint", "pattern", "general"]},
                    "project_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="memory_list",
            description="List all memories, optionally filtered by category or project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": ["preference", "decision", "constraint", "pattern", "general"]},
                    "project_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
            },
        ),
        Tool(
            name="deploy_web",
            description="Deploy a project as a static website. Makes it accessible via URL. Returns the live URL.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "slug": {"type": "string", "description": "URL slug (default: project slug)"},
                },
                "required": ["project_id"],
            },
        ),
        Tool(
            name="undeploy_web",
            description="Take down a deployed project website.",
            inputSchema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
            },
        ),
        Tool(
            name="list_deployments",
            description="List all currently deployed web projects with their URLs.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="generate_image",
            description="Generate an image from a text description using AI (DALL-E, Stability AI, etc.). Returns an image URL or path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Detailed text description of the image to generate"},
                    "size": {"type": "string", "description": "Image size: 1024x1024, 1792x1024, or 1024x1792", "default": "1024x1024"},
                },
                "required": ["prompt"],
            },
        ),
    ]


# ── reads ──
def _task_list(args: dict[str, Any]) -> list[dict[str, Any]]:
    where = []
    params: list[Any] = []
    for col in ("status", "area", "project_id"):
        if args.get(col):
            where.append(f"{col} = ?")
            params.append(args[col])
    sql = "SELECT * FROM tasks"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(min(int(args.get("limit", 50)), 200))
    with _ro_conn() as c:
        return [_row_to_dict(r) for r in c.execute(sql, params)]


def _task_get(task_id: str) -> dict[str, Any] | None:
    with _ro_conn() as c:
        row = c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_to_dict(row) if row else None


def _project_list() -> list[dict[str, Any]]:
    with _ro_conn() as c:
        return [_row_to_dict(r) for r in c.execute("SELECT * FROM projects ORDER BY name")]


def _project_get(project_id: str) -> dict[str, Any] | None:
    with _ro_conn() as c:
        row = c.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return _row_to_dict(row) if row else None


def _pipeline_status() -> dict[str, Any]:
    with _ro_conn() as c:
        by_status = {
            r["status"]: r["n"]
            for r in c.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status")
        }
        total = sum(by_status.values())
        active = sum(by_status.get(s, 0) for s in ("inbox", "pendiente", "en_progreso", "bloqueada", "revision", "waiting_input"))
        return {"total": total, "active": active, "by_status": by_status}


# ── writes ──
def _task_create(args: dict[str, Any]) -> dict[str, Any]:
    title = args["title"].strip()
    if not title:
        raise ValueError("title cannot be empty")
    area = args["area"]
    if area not in VALID_AREAS:
        raise ValueError(f"invalid area: {area}")
    status = args.get("status", "pendiente")
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    priority = args.get("priority", "media")
    if priority not in VALID_PRIORITIES:
        raise ValueError(f"invalid priority: {priority}")
    project_id = args.get("project_id")
    description = args.get("description")
    notes = args.get("notes")

    assigned_to_claude = 1 if args.get("assigned_to_claude") else 0
    source = args.get("source", "mcp:tasks")

    task_id = f"task-{uuid.uuid4().hex[:12]}"
    now = _now_iso()
    with _rw_conn() as c:
        c.execute(
            """
            INSERT INTO tasks (
                id, title, description, area, project_id, status, priority,
                urgent, source, notes, created_at, updated_at,
                assigned_to_yume, assigned_to_claude
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, 0, ?)
            """,
            (task_id, title, description, area, project_id, status, priority, source, notes, now, now, assigned_to_claude),
        )
        c.commit()
        row = c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_to_dict(row)


def _task_update_status(args: dict[str, Any]) -> dict[str, Any]:
    task_id = args["task_id"]
    new_status = args["status"]
    if new_status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {new_status}")
    extra_notes = args.get("notes", "")

    with _rw_conn() as c:
        row = c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise ValueError(f"task not found: {task_id}")
        _assert_task_transition(row["status"], new_status)
        current_notes = row["notes"] or ""
        merged_notes = (current_notes + ("\n" if current_notes and extra_notes else "") + extra_notes) or None
        now = _now_iso()
        completed_at = now if new_status == "hecha" else row["completed_at"]
        c.execute(
            "UPDATE tasks SET status = ?, notes = ?, updated_at = ?, completed_at = ? WHERE id = ?",
            (new_status, merged_notes, now, completed_at, task_id),
        )
        c.commit()
        updated = c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_to_dict(updated)



# ── web search ──

_SEARXNG_URL = os.environ.get("NIWA_SEARXNG_URL", "").rstrip("/")


def _get_setting(key: str) -> str:
    """Read a single setting from the SQLite settings table."""
    try:
        with _ro_conn() as c:
            row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row["value"] if row else ""
    except Exception:
        return ""


def _get_search_config() -> tuple[str, str]:
    """Get search provider and SearXNG URL from DB settings, falling back to env var."""
    provider = _get_setting("svc.search.provider") or "duckduckgo"
    searxng_url = _get_setting("svc.search.searxng_url") or _SEARXNG_URL
    return provider, searxng_url.rstrip("/") if searxng_url else ""


def _web_search(args: dict) -> dict:
    query = args.get("query", "").strip()
    max_results = min(int(args.get("max_results", 5)), 10)
    if not query:
        raise ValueError("query cannot be empty")

    # Read search config from DB (with env var fallback)
    provider, searxng_url = _get_search_config()

    # Try SearXNG first if configured
    if provider == "searxng" and searxng_url or (provider != "searxng" and _SEARXNG_URL):
        searxng_url = searxng_url or _SEARXNG_URL
        try:
            url = f"{searxng_url}/search?q={urllib.parse.quote(query)}&format=json&categories=general"
            req = urllib.request.Request(url, headers={"User-Agent": "niwa-mcp/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
            results = [
                {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
                for r in data.get("results", [])[:max_results]
            ]
            return {"query": query, "results": results, "source": "searxng"}
        except Exception:
            pass  # fall through to DuckDuckGo

    # Fallback: DuckDuckGo instant answers API
    try:
        url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(url, headers={"User-Agent": "niwa-mcp/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        results = []
        # AbstractText is the main answer
        if data.get("AbstractText"):
            results.append({
                "title": data.get("Heading", query),
                "url": data.get("AbstractURL", ""),
                "snippet": data["AbstractText"],
            })
        # RelatedTopics for more results
        for topic in data.get("RelatedTopics", [])[:max_results - len(results)]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "title": topic.get("Text", "")[:80],
                    "url": topic.get("FirstURL", ""),
                    "snippet": topic.get("Text", ""),
                })
        if not results:
            results.append({"title": "No instant answer", "url": f"https://duckduckgo.com/?q={urllib.parse.quote(query)}", "snippet": "Try the search URL directly for full results."})
        return {"query": query, "results": results, "source": "duckduckgo"}
    except Exception as e:
        return {"query": query, "results": [], "error": str(e)}


# ── memories ──

_MEMORIES_DDL = """
CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'general',
    project_id  TEXT,
    source      TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_key
    ON memories(key, COALESCE(project_id,''));
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_project   ON memories(project_id);
"""


def _ensure_memories_table() -> None:
    with _rw_conn() as c:
        c.executescript(_MEMORIES_DDL)


try:
    _ensure_memories_table()
except Exception:
    pass



# deployments table is created by schema.sql + migration 003_deployments.sql
# No runtime DDL needed.


def _memory_store(args: dict) -> dict:
    key = args.get("key", "").strip()
    value = args.get("value", "").strip()
    category = args.get("category", "general").strip() or "general"
    project_id = args.get("project_id") or None
    source = args.get("source", "claude").strip()
    if not key:
        raise ValueError("key cannot be empty")
    if not value:
        raise ValueError("value cannot be empty")
    now = _now_iso()
    mem_id = str(uuid.uuid4())
    with _rw_conn() as c:
        c.execute(
            """
            INSERT INTO memories (id, key, value, category, project_id, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key, COALESCE(project_id,'')) DO UPDATE
            SET value=excluded.value, category=excluded.category,
                source=excluded.source, updated_at=excluded.updated_at
            """,
            (mem_id, key, value, category, project_id, source, now, now),
        )
        c.commit()
    return {"ok": True, "key": key, "category": category}


def _memory_search(args: dict) -> list:
    q = args.get("query", "").strip().lower()
    category = args.get("category") or None
    project_id = args.get("project_id") or None
    limit = min(int(args.get("limit", 20)), 50)
    with _ro_conn() as c:
        parts, params = [], []
        if q:
            parts.append("(lower(key) LIKE ? OR lower(value) LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like])
        if category:
            parts.append("category = ?")
            params.append(category)
        if project_id:
            parts.append("(project_id = ? OR project_id IS NULL)")
            params.append(project_id)
        where = ("WHERE " + " AND ".join(parts)) if parts else ""
        rows = c.execute(
            f"SELECT * FROM memories {where} ORDER BY updated_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _memory_list(args: dict) -> list:
    category = args.get("category") or None
    project_id = args.get("project_id") or None
    limit = min(int(args.get("limit", 50)), 200)
    with _ro_conn() as c:
        parts, params = [], []
        if category:
            parts.append("category = ?")
            params.append(category)
        if project_id:
            parts.append("(project_id = ? OR project_id IS NULL)")
            params.append(project_id)
        where = ("WHERE " + " AND ".join(parts)) if parts else ""
        rows = c.execute(
            f"SELECT * FROM memories {where} ORDER BY category, key LIMIT ?",
            params + [limit],
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _project_update(args: dict) -> dict:
    project_id = args.get("project_id", "").strip()
    if not project_id:
        raise ValueError("project_id required")
    with _rw_conn() as c:
        row = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise ValueError(f"project not found: {project_id}")
        updates, params = [], []
        for field in ("name", "description", "directory", "url"):
            if field in args and args[field] is not None:
                updates.append(f"{field}=?")
                params.append(args[field])
        if "active" in args:
            updates.append("active=?")
            params.append(1 if args["active"] else 0)
        if not updates:
            return _row_to_dict(row)
        updates.append("updated_at=?")
        params.append(_now_iso())
        params.append(project_id)
        c.execute(f"UPDATE projects SET {', '.join(updates)} WHERE id=?", params)
        c.commit()
        return _row_to_dict(c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())


def _task_update(args: dict) -> dict:
    task_id = args.get("task_id", "").strip()
    if not task_id:
        raise ValueError("task_id required")
    with _rw_conn() as c:
        row = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise ValueError(f"task not found: {task_id}")
        updates, params = [], []
        for field in ("title", "description", "project_id", "priority", "area", "notes"):
            if field in args and args[field] is not None:
                updates.append(f"{field}=?")
                params.append(args[field])
        if not updates:
            return _row_to_dict(row)
        updates.append("updated_at=?")
        params.append(_now_iso())
        params.append(task_id)
        c.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id=?", params)
        c.commit()
        return _row_to_dict(c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())


def _project_create(args: dict) -> dict:
    """Create a project via the app's HTTP endpoint (PR-52).

    Previous implementation inserted rows directly using a weaker slug
    rule (``name.lower().replace(' ', '-')[:50]``), no slug dedup, no
    auto-generated directory, and no task linking. The HTTP endpoint
    (``POST /api/projects``) already handles all of that since PR-51;
    delegating to it guarantees MCP and UI create projects identically.

    If ``task_id`` is in ``args``, the HTTP endpoint also associates the
    task to the new project in the same transaction.
    """
    name = (args.get("name") or "").strip()
    if not name:
        raise ValueError("name cannot be empty")
    area = args.get("area") or "proyecto"
    if area not in VALID_AREAS:
        raise ValueError(f"invalid area: {area}")
    body = {
        "name": name,
        "area": area,
        "description": args.get("description", ""),
        "directory": args.get("directory", ""),
        "url": args.get("url", ""),
    }
    if args.get("task_id"):
        body["task_id"] = args["task_id"]
    status, resp = _app_request("/api/projects", method="POST", body=body)
    if status != 201:
        raise ValueError(
            f"project_create failed (status={status}): {resp.get('error', resp)}"
        )
    # Return the canonical row the HTTP endpoint constructed. Read it
    # back so the caller gets the same shape they always got (full
    # ``projects`` row) — keeps backward compat with existing callers.
    proj_id = resp["id"]
    with _ro_conn() as c:
        row = c.execute("SELECT * FROM projects WHERE id=?", (proj_id,)).fetchone()
    return _row_to_dict(row)


def _project_context(args):
    project_id = args["project_id"]
    include_done = args.get("include_done", False)
    with _ro_conn() as c:
        project = c.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not project:
            raise ValueError(f"project not found: {project_id}")
        sf = "" if include_done else "AND status NOT IN ('hecha','archivada')"
        tasks = c.execute(
            f"SELECT id,title,status,priority,description FROM tasks WHERE project_id=? {sf} ORDER BY CASE status WHEN 'en_progreso' THEN 0 WHEN 'pendiente' THEN 1 WHEN 'bloqueada' THEN 2 ELSE 3 END, updated_at DESC",
            (project_id,),
        ).fetchall()
        notes, decisions = [], []
        try:
            notes = c.execute("SELECT id,title,type,content,created_at FROM notes WHERE project_id=? AND type!='decision' ORDER BY updated_at DESC LIMIT 10", (project_id,)).fetchall()
            decisions = c.execute("SELECT id,title,content,created_at FROM notes WHERE project_id=? AND type='decision' ORDER BY updated_at DESC LIMIT 10", (project_id,)).fetchall()
        except Exception:
            pass
        return {
            "project": _row_to_dict(project),
            "tasks": [_row_to_dict(r) for r in tasks],
            "notes": [_row_to_dict(r) for r in notes],
            "decisions": [_row_to_dict(r) for r in decisions],
        }


def _task_log(args):
    task_id, message = args["task_id"], args["message"].strip()
    kind = args.get("kind", "progress")
    if not message:
        raise ValueError("message cannot be empty")
    with _rw_conn() as c:
        if not c.execute("SELECT id FROM tasks WHERE id=?", (task_id,)).fetchone():
            raise ValueError(f"task not found: {task_id}")
        eid = str(uuid.uuid4())
        c.execute(
            "INSERT INTO task_events(id,task_id,type,payload_json,created_at) VALUES(?,?,?,?,?)",
            (eid, task_id, "comment", json.dumps({"author":"claude","kind":kind,"message":message},ensure_ascii=False), _now_iso()),
        )
        c.commit()
    return {"ok": True, "event_id": eid, "kind": kind}


def _task_request_input(args):
    task_id, question = args["task_id"], args["question"].strip()
    context = args.get("context","").strip()
    if not question:
        raise ValueError("question cannot be empty")
    with _rw_conn() as c:
        row = c.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise ValueError(f"task not found: {task_id}")
        _assert_task_transition(row["status"], "waiting_input")
        now = _now_iso()
        c.execute("UPDATE tasks SET status='waiting_input', updated_at=? WHERE id=?", (now, task_id))
        eid = str(uuid.uuid4())
        c.execute(
            "INSERT INTO task_events(id,task_id,type,payload_json,created_at) VALUES(?,?,?,?,?)",
            (eid, task_id, "alerted", json.dumps({"author":"claude","question":question,"context":context},ensure_ascii=False), now),
        )
        c.commit()
    return {"ok": True, "status": "waiting_input", "event_id": eid, "question": question}

def _deploy_web(args):
    """Deploy a project's directory as a static site (PR-52).

    Delegates to the app's HTTP endpoint ``POST /api/projects/:id/deploy``.
    The previous MCP implementation only updated the ``deployments``
    table; it never called ``hosting.generate_caddyfile()`` or
    ``_reload_caddy()``, so Caddy kept serving the old config and the
    site wasn't actually reachable — a split-brain that looked
    "deployed" in the DB but wasn't live.

    The HTTP endpoint runs ``hosting.deploy_project()`` which writes
    the Caddyfile and reloads the server, so MCP and UI now produce
    the same side effect.
    """
    project_id = args["project_id"]
    status, resp = _app_request(
        f"/api/projects/{project_id}/deploy", method="POST", body={}
    )
    if status != 200:
        raise ValueError(
            f"deploy_web failed (status={status}): {resp.get('error', resp)}"
        )
    # HTTP endpoint returns {'ok': True, 'url': ..., 'slug': ...,
    # 'directory': ..., 'status': 'active'}. Drop the 'ok' flag to
    # keep backward-compat with existing MCP callers.
    return {
        "url": resp.get("url"),
        "slug": resp.get("slug"),
        "directory": resp.get("directory"),
        "status": "deployed",
    }


def _undeploy_web(args):
    project_id = args["project_id"]
    now = _now_iso()
    with _rw_conn() as c:
        c.execute(
            "UPDATE deployments SET status='inactive', updated_at=? WHERE project_id=?",
            (now, project_id),
        )
        c.commit()
    return {"ok": True}


def _list_deployments_handler(args):
    with _ro_conn() as c:
        rows = c.execute(
            "SELECT * FROM deployments WHERE status='active' ORDER BY deployed_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _generate_image(args: dict) -> dict:
    """Generate an image using the configured image generation service."""
    prompt = args.get("prompt", "").strip()
    if not prompt:
        raise ValueError("prompt cannot be empty")
    size = args.get("size", "1024x1024")

    # Read image service config from DB
    config = {}
    try:
        with _ro_conn() as c:
            for row in c.execute("SELECT key, value FROM settings WHERE key LIKE 'svc.image.%'").fetchall():
                short_key = row["key"].replace("svc.image.", "")
                config[short_key] = row["value"]
    except Exception:
        pass

    provider = config.get("provider", "openai")
    api_key = config.get("api_key", "")
    model = config.get("model", "dall-e-3")
    default_size = config.get("default_size", "1024x1024")

    if not api_key:
        return {"error": "No hay API key configurada para generación de imágenes. Pide al usuario que vaya a Sistema > Servicios para configurarla."}

    size = size or default_size

    if provider == "openai":
        return _generate_image_openai(prompt, api_key, model, size)
    elif provider == "stability":
        return _generate_image_stability(prompt, api_key, model, size)
    return {"error": f"Proveedor desconocido: {provider}"}


def _generate_image_openai(prompt, api_key, model, size):
    """Generate via OpenAI DALL-E API."""
    import json as _json
    url = "https://api.openai.com/v1/images/generations"
    payload = _json.dumps({"model": model, "prompt": prompt, "n": 1, "size": size, "response_format": "url"}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = _json.loads(resp.read())
            img = data["data"][0]
            return {"url": img.get("url"), "revised_prompt": img.get("revised_prompt", prompt), "model": model, "size": size, "provider": "openai"}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            msg = _json.loads(body).get("error", {}).get("message", body)
        except Exception:
            msg = body
        return {"error": f"OpenAI error: {msg}"}
    except Exception as e:
        return {"error": f"Error generando imagen: {e}"}


def _generate_image_stability(prompt, api_key, model, size):
    """Generate via Stability AI API."""
    import json as _json
    w, h = size.split("x")
    url = f"https://api.stability.ai/v1/generation/{model}/text-to-image"
    payload = _json.dumps({"text_prompts": [{"text": prompt, "weight": 1}], "cfg_scale": 7, "height": int(h), "width": int(w), "samples": 1, "steps": 30}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = _json.loads(resp.read())
            img = data["artifacts"][0]
            # Return base64 data for Stability (no URL)
            return {"base64": img["base64"], "model": model, "size": size, "provider": "stability"}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"error": f"Stability AI error: {body}"}
    except Exception as e:
        return {"error": f"Error generando imagen: {e}"}


# ── PR-09: v02-assistant tool definitions ────────────────────────────

_V02_TOOL_DEFS: list[Tool] = [
    Tool(
        name="assistant_turn",
        description=(
            "Process one conversational turn. The LLM interprets user intent "
            "and may invoke domain tools (create task, check status, etc.). "
            "Can take up to 30s. Requires routing_mode=v02."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Chat session identifier."},
                "project_id": {"type": "string", "description": "Project scope."},
                "message": {"type": "string", "description": "User message text."},
                "channel": {
                    "type": "string",
                    "enum": ["web", "telegram", "cli", "other"],
                    "description": "Origin channel. OpenClaw passes 'telegram', web chat passes 'web', smoke test passes 'cli'.",
                },
                "metadata": {"type": "object", "description": "Channel-specific data (optional)."},
            },
            "required": ["session_id", "project_id", "message", "channel"],
        },
    ),
    Tool(
        name="task_list",
        description="List tasks for a project, optionally filtered by status.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": list(VALID_STATUSES),
                },
                "limit": {"type": "integer", "description": "Max results (default 20, max 50)."},
            },
            "required": ["project_id"],
        },
    ),
    Tool(
        name="task_get",
        description="Get detailed information about a specific task.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "task_id": {"type": "string"},
            },
            "required": ["project_id", "task_id"],
        },
    ),
    Tool(
        name="task_create",
        description="Create a new task. Executed by the backend engine asynchronously.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "priority": {"type": "string", "enum": ["baja", "media", "alta", "critica"]},
            },
            "required": ["project_id", "title"],
        },
    ),
    Tool(
        name="task_cancel",
        description="Cancel a task and its active run (archives the task).",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "task_id": {"type": "string"},
            },
            "required": ["project_id", "task_id"],
        },
    ),
    Tool(
        name="task_resume",
        description="Resume a blocked or waiting task (transitions to pendiente).",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "task_id": {"type": "string"},
            },
            "required": ["project_id", "task_id"],
        },
    ),
    Tool(
        name="approval_list",
        description="List approval requests, optionally filtered by status or task.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "status": {"type": "string", "enum": ["pending", "approved", "rejected"]},
                "task_id": {"type": "string"},
            },
            "required": ["project_id"],
        },
    ),
    Tool(
        name="approval_respond",
        description="Respond to a pending approval (approve or reject).",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "approval_id": {"type": "string"},
                "decision": {"type": "string", "enum": ["approved", "rejected"]},
                "note": {"type": "string"},
            },
            "required": ["project_id", "approval_id", "decision"],
        },
    ),
    Tool(
        name="run_tail",
        description="Get recent events from a backend execution run.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "run_id": {"type": "string"},
                "limit": {"type": "integer", "description": "Max events (default 20)."},
            },
            "required": ["project_id", "run_id"],
        },
    ),
    Tool(
        name="run_explain",
        description="Explain routing decision and execution history for a task.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "task_id": {"type": "string"},
            },
            "required": ["project_id", "task_id"],
        },
    ),
    Tool(
        name="project_context",
        description="Get project metadata, task summary, and recent activity.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
            },
            "required": ["project_id"],
        },
    ),
]

_V02_TOOL_NAMES = {t.name for t in _V02_TOOL_DEFS}


def _load_contract_tools() -> set[str] | None:
    """Load the tool allow-list from the contract file.

    Returns None if no contract is configured (expose all legacy tools).
    Returns a set of tool names if a contract is active.
    """
    if not _MCP_CONTRACT:
        return None
    # Contract files are under config/mcp-contract/
    # In Docker the config is mounted at /config.
    for base in ("/config/mcp-contract", "config/mcp-contract"):
        path = os.path.join(base, f"{_MCP_CONTRACT}.json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data.get("tools", []))
    # Fallback: parse tool names from the env var itself if comma-separated
    # (defensive — primary path is the JSON file)
    return None


_CONTRACT_TOOLS: set[str] | None = _load_contract_tools()


# ── PR-52: generic HTTP delegation helper for project_create / deploy_web ──


def _app_request(path: str, method: str = "POST", body: dict | None = None) -> tuple[int, dict]:
    """Call the Niwa app HTTP API. Returns ``(status_code, body_json)``.

    Uses the shared ``_S2S_TOKEN`` so the app accepts it as service-to-
    service. HTTPErrors are captured and their body is parsed — callers
    inspect ``status`` to decide what to do.  Network errors still raise.
    """
    import urllib.error as _ue
    import urllib.request as _ur

    url = f"{_APP_BASE_URL}{path}"
    data = json.dumps(body or {}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if _S2S_TOKEN:
        headers["Authorization"] = f"Bearer {_S2S_TOKEN}"
    req = _ur.Request(url, data=data, headers=headers, method=method)
    try:
        with _ur.urlopen(req, timeout=35) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(raw) if raw else {})
    except _ue.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, (json.loads(raw) if raw else {})
        except json.JSONDecodeError:
            return exc.code, {"error": raw[:500]}


# ── PR-09: HTTP proxy for v02-assistant tools ────────────────────────

def _http_proxy(path: str, body: dict) -> dict:
    """POST to Niwa app and return the parsed JSON response.

    On HTTP errors, returns a dict with error_code and message instead
    of raising — the MCP layer translates to structured MCP errors.
    """
    import urllib.error as _ue
    import urllib.request as _ur

    url = f"{_APP_BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
    }
    if _S2S_TOKEN:
        headers["Authorization"] = f"Bearer {_S2S_TOKEN}"

    req = _ur.Request(url, data=data, headers=headers, method="POST")
    try:
        with _ur.urlopen(req, timeout=35) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except _ue.HTTPError as exc:
        try:
            body_text = exc.read().decode("utf-8", errors="replace")
            result = json.loads(body_text)
        except (json.JSONDecodeError, Exception):
            result = {}

        status = exc.code
        if status == 409:
            error_code = result.get("error", "routing_mode_mismatch")
        elif status == 401:
            error_code = "auth_failure"
        elif status == 404:
            error_code = result.get("error", "not_found")
        elif status >= 500:
            error_code = "internal_error"
        else:
            error_code = result.get("error", "request_error")

        return {
            "error_code": error_code,
            "message": result.get("message", result.get("error", f"HTTP {status}")),
            "http_status": status,
        }
    except _ue.URLError as exc:
        return {
            "error_code": "connection_error",
            "message": f"Cannot reach Niwa app: {exc.reason}",
        }
    except Exception as exc:
        return {
            "error_code": "internal_error",
            "message": str(exc),
        }


def _call_v02_tool(name: str, arguments: dict) -> dict:
    """Dispatch a v02-assistant tool call via HTTP proxy."""
    if name == "assistant_turn":
        return _http_proxy("/api/assistant/turn", {
            "session_id": arguments.get("session_id", ""),
            "project_id": arguments.get("project_id", ""),
            "message": arguments.get("message", ""),
            "channel": arguments.get("channel", "other"),
            "metadata": arguments.get("metadata"),
        })

    # All other v02 tools use /api/assistant/tools/{name}
    project_id = arguments.pop("project_id", "")
    return _http_proxy(f"/api/assistant/tools/{name}", {
        "project_id": project_id,
        "params": arguments,
    })


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        # PR-09: v02-assistant tools → HTTP proxy
        if name in _V02_TOOL_NAMES and _CONTRACT_TOOLS is not None and name in _CONTRACT_TOOLS:
            payload = _call_v02_tool(name, dict(arguments or {}))
            # Translate error_code to MCP structured error
            if isinstance(payload, dict) and "error_code" in payload:
                error_text = json.dumps(payload, ensure_ascii=False)
                return [TextContent(type="text", text=error_text)]
            return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, default=str))]

        if name == "task_list":
            payload = _task_list(arguments or {})
        elif name == "task_get":
            payload = _task_get(arguments["task_id"])
        elif name == "project_list":
            payload = _project_list()
        elif name == "project_get":
            payload = _project_get(arguments["project_id"])
        elif name == "pipeline_status":
            payload = _pipeline_status()
        elif name == "project_create":
            payload = _project_create(arguments or {})
        elif name == "project_update":
            payload = _project_update(arguments or {})
        elif name == "task_update":
            payload = _task_update(arguments or {})
        elif name == "task_create":
            payload = _task_create(arguments or {})
        elif name == "task_update_status":
            payload = _task_update_status(arguments or {})
        elif name == "project_context":
            payload = _project_context(arguments or {})
        elif name == "task_log":
            payload = _task_log(arguments or {})
        elif name == "task_request_input":
            payload = _task_request_input(arguments or {})
        elif name == "web_search":
            payload = _web_search(arguments or {})
        elif name == "memory_store":
            payload = _memory_store(arguments or {})
        elif name == "memory_search":
            payload = _memory_search(arguments or {})
        elif name == "memory_list":
            payload = _memory_list(arguments or {})
        elif name == "deploy_web":
            payload = _deploy_web(arguments or {})
        elif name == "undeploy_web":
            payload = _undeploy_web(arguments or {})
        elif name == "list_deployments":
            payload = _list_deployments_handler(arguments or {})
        elif name == "generate_image":
            payload = _generate_image(arguments or {})
        else:
            return [TextContent(type="text", text=json.dumps({"error": f"unknown tool: {name}"}))]
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, default=str))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e), "tool": name}))]


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
