"""
Tasks MCP server — projects + tasks for Niwa

Read verbs:  task_list, task_get, project_list, project_get, pipeline_status
Write verbs: task_create, task_update_status

Backing store: /data/niwa.sqlite3 (mounted RW; reads still use mode=ro URI).
"""

import asyncio
import json
import os
import sqlite3
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
            name="task_create",
            description=(
                "Create a new task. Required: title, area. Optional: project_id, status (default 'inbox'), "
                "priority (default 'media'), description, notes. Returns the created task."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "area": {"type": "string", "enum": list(VALID_AREAS)},
                    "project_id": {"type": "string"},
                    "status": {"type": "string", "enum": list(VALID_STATUSES), "default": "inbox"},
                    "priority": {"type": "string", "enum": list(VALID_PRIORITIES), "default": "media"},
                    "description": {"type": "string"},
                    "notes": {"type": "string"},
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
    status = args.get("status", "inbox")
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    priority = args.get("priority", "media")
    if priority not in VALID_PRIORITIES:
        raise ValueError(f"invalid priority: {priority}")
    project_id = args.get("project_id")
    description = args.get("description")
    notes = args.get("notes")

    task_id = f"task-{uuid.uuid4().hex[:12]}"
    now = _now_iso()
    with _rw_conn() as c:
        c.execute(
            """
            INSERT INTO tasks (
                id, title, description, area, project_id, status, priority,
                urgent, source, notes, created_at, updated_at,
                assigned_to_yume, assigned_to_claude
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'mcp:tasks', ?, ?, ?, 0, 0)
            """,
            (task_id, title, description, area, project_id, status, priority, notes, now, now),
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
        elif name == "task_create":
            payload = _task_create(arguments or {})
        elif name == "task_update_status":
            payload = _task_update_status(arguments or {})
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
