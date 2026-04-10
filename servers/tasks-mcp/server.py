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

VALID_AREAS = ("personal", "empresa", "proyecto", "sistema")
VALID_STATUSES = ("inbox", "pendiente", "en_progreso", "bloqueada", "revision", "hecha", "archivada")
VALID_PRIORITIES = ("baja", "media", "alta", "critica", "low", "medium", "high", "critical")

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
    return [
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
        active = sum(by_status.get(s, 0) for s in ("inbox", "pendiente", "en_progreso", "bloqueada", "revision"))
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

    task_id = f"task-{uuid.uuid4().hex[:12]}"
    now = _now_iso()
    with _rw_conn() as c:
        c.execute(
            """
            INSERT INTO tasks (
                id, title, description, area, project_id, status, priority,
                urgent, source, notes, created_at, updated_at,
                assigned_to_yume, assigned_to_claude
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'mcp:tasks', ?, ?, ?, 0, ?)
            """,
            (task_id, title, description, area, project_id, status, priority, notes, now, now, assigned_to_claude),
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


def _ensure_deployments_table() -> None:
    with _rw_conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS deployments (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, slug TEXT NOT NULL UNIQUE,
                directory TEXT NOT NULL, url TEXT, status TEXT NOT NULL DEFAULT 'active',
                deployed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
            );
            CREATE INDEX IF NOT EXISTS idx_deployments_project ON deployments(project_id);
        """)


try:
    _ensure_deployments_table()
except Exception:
    pass


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
    name = args.get("name", "").strip()
    if not name:
        raise ValueError("name cannot be empty")
    area = args.get("area", "proyecto")
    if area not in VALID_AREAS:
        raise ValueError(f"invalid area: {area}")
    description = args.get("description", "")
    directory = args.get("directory", "")
    url = args.get("url", "")
    slug = name.lower().replace(" ", "-").replace("_", "-")[:50]
    now = _now_iso()
    project_id = f"proj-{uuid.uuid4().hex[:12]}"
    with _rw_conn() as c:
        c.execute(
            "INSERT INTO projects (id, slug, name, area, description, active, created_at, updated_at, directory, url) "
            "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
            (project_id, slug, name, area, description, now, now, directory, url),
        )
        c.commit()
        row = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
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
        if not c.execute("SELECT id FROM tasks WHERE id=?", (task_id,)).fetchone():
            raise ValueError(f"task not found: {task_id}")
        now = _now_iso()
        c.execute("UPDATE tasks SET status='revision', updated_at=? WHERE id=?", (now, task_id))
        eid = str(uuid.uuid4())
        c.execute(
            "INSERT INTO task_events(id,task_id,type,payload_json,created_at) VALUES(?,?,?,?,?)",
            (eid, task_id, "alerted", json.dumps({"author":"claude","question":question,"context":context},ensure_ascii=False), now),
        )
        c.commit()
    return {"ok": True, "status": "revision", "event_id": eid, "question": question}

def _deploy_web(args):
    project_id = args["project_id"]
    slug = args.get("slug", "")
    with _rw_conn() as c:
        project = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            raise ValueError(f"Project not found: {project_id}")
        project = _row_to_dict(project)
        slug = slug or project.get("slug", project_id)
        directory = project.get("directory", "")
        if not directory:
            raise ValueError("Project has no directory set")

        now = _now_iso()
        existing = c.execute("SELECT id FROM deployments WHERE project_id=?", (project_id,)).fetchone()
        if existing:
            c.execute(
                "UPDATE deployments SET slug=?, directory=?, status='active', updated_at=? WHERE project_id=?",
                (slug, directory, now, project_id),
            )
        else:
            deploy_id = str(uuid.uuid4())
            c.execute(
                "INSERT INTO deployments (id, project_id, slug, directory, status, deployed_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (deploy_id, project_id, slug, directory, "active", now, now),
            )

        public_url = os.environ.get("NIWA_PUBLIC_URL", "http://localhost")
        port = os.environ.get("NIWA_HOSTING_PORT", "8880")
        url = f"{public_url}:{port}/{slug}/"

        c.execute("UPDATE deployments SET url=? WHERE project_id=?", (url, project_id))
        c.execute("UPDATE projects SET url=?, updated_at=? WHERE id=?", (url, now, project_id))
        c.commit()

    return {"url": url, "slug": slug, "directory": directory, "status": "deployed"}


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


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
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
