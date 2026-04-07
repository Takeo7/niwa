"""
Notes MCP server — typed notes for Niwa

Personal interface for notes, typed notes (decision/idea/research/diary)
and inbox. Backing store: /data/niwa.sqlite3.

Generic verbs:
  - note_list(type?, project_id?, tag?, status?, limit?)
  - note_get(note_id)
  - note_create(title, type?, content?, project_id?, tags?, metadata?, status?)
  - note_update(note_id, title?, content?, tags?, status?, metadata?)

Typed creates:
  - decision_create(title, context, decision, alternatives?, consequences?, project_id?)
  - idea_create(title, content?, project_id?)
  - research_create(title, topic, sources?, project_id?)
  - diary_append_today(personal_note, auto_summary?)

Rich verbs (Phase C):
  - idea_append(idea_id, content)
  - idea_set_status(idea_id, status)
  - idea_promote_to_task(idea_id, project_id?, area?, priority?)  → creates task + bidi link
  - research_append_finding(research_id, source, finding)
  - research_set_conclusion(research_id, conclusion)
  - research_link_to_decision(research_id, decision_id)

Typed reads (Phase D):
  - decision_list(project_id?, limit?)
  - idea_list(status?, project_id?, limit?)
  - research_list(topic?, project_id?, limit?)
  - diary_get_today()  → today's diary entry or null
  - diary_get(date)    → specific date's diary or null (date as YYYY-MM-DD)
  - diary_list(limit?) → recent diary entries, newest first

Inbox:
  - inbox_list(kind?, untriaged_only?, limit?)
  - inbox_create(kind, title, body?, source?)
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

VALID_INBOX_KINDS = ("task", "note", "email", "calendar", "file", "message")
VALID_NOTE_TYPES = ("decision", "idea", "research", "diary", "note")
VALID_IDEA_STATUSES = ("raw", "refining", "ready", "abandoned", "done")
VALID_TASK_AREAS = ("personal", "empresa", "proyecto", "sistema")
VALID_TASK_PRIORITIES = ("baja", "media", "alta", "critica", "low", "medium", "high", "critical")
VALID_TASK_STATUSES = ("inbox", "pendiente", "en_progreso", "bloqueada", "revision", "hecha", "archivada")

server = Server("notes")


def _ro_conn() -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _rw_conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _row(r: sqlite3.Row) -> dict[str, Any]:
    d = {k: r[k] for k in r.keys()}
    # Decode JSON columns for caller convenience
    for col in ("metadata", "linked_tasks", "linked_decisions"):
        if col in d and d[col]:
            try:
                d[col] = json.loads(d[col])
            except (TypeError, json.JSONDecodeError):
                pass
    return d


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _new_note_id() -> str:
    return f"note-{uuid.uuid4().hex[:12]}"


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # ── generic notes ──
        Tool(
            name="note_list",
            description=(
                "List notes. Optional filters: type (decision/idea/research/diary/note), project_id, "
                "tag (substring match), status, limit (default 50, max 200)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": list(VALID_NOTE_TYPES)},
                    "project_id": {"type": "string"},
                    "tag": {"type": "string"},
                    "status": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
            },
        ),
        Tool(
            name="note_get",
            description="Get a single note by id, with full content and decoded metadata.",
            inputSchema={
                "type": "object",
                "properties": {"note_id": {"type": "string"}},
                "required": ["note_id"],
            },
        ),
        Tool(
            name="note_create",
            description=(
                "Create a generic note. Required: title. Optional: type (default 'note'), content, "
                "project_id, tags (comma-separated), metadata (object — will be JSON-encoded), status."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "type": {"type": "string", "enum": list(VALID_NOTE_TYPES), "default": "note"},
                    "content": {"type": "string"},
                    "project_id": {"type": "string"},
                    "tags": {"type": "string"},
                    "metadata": {"type": "object"},
                    "status": {"type": "string"},
                },
                "required": ["title"],
            },
        ),
        Tool(
            name="note_update",
            description="Update a note. Any of title/content/tags/status/metadata. Updates updated_at.",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "tags": {"type": "string"},
                    "status": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["note_id"],
            },
        ),
        # ── typed creates ──
        Tool(
            name="decision_create",
            description=(
                "Record an architectural decision (ADR). Required: title, context, decision. "
                "Optional: alternatives (array of strings), consequences (array of strings), project_id."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "context": {"type": "string"},
                    "decision": {"type": "string"},
                    "alternatives": {"type": "array", "items": {"type": "string"}},
                    "consequences": {"type": "array", "items": {"type": "string"}},
                    "project_id": {"type": "string"},
                },
                "required": ["title", "context", "decision"],
            },
        ),
        Tool(
            name="idea_create",
            description=(
                "Capture a half-baked idea. Required: title. Optional: content, project_id. "
                "Status starts as 'raw' and can be moved to refining/ready/abandoned/done."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "content": {"type": "string"},
                    "project_id": {"type": "string"},
                },
                "required": ["title"],
            },
        ),
        Tool(
            name="research_create",
            description=(
                "Start a research log. Required: title, topic. Optional: sources (array of strings), "
                "project_id. Findings can be appended later via research_append_finding."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "topic": {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "string"}},
                    "project_id": {"type": "string"},
                },
                "required": ["title", "topic"],
            },
        ),
        # ── rich verbs (Phase C) ──
        Tool(
            name="idea_append",
            description="Append text to an idea's content (preserves existing content with newline separator).",
            inputSchema={
                "type": "object",
                "properties": {
                    "idea_id": {"type": "string"},
                    "content": {"type": "string", "minLength": 1},
                },
                "required": ["idea_id", "content"],
            },
        ),
        Tool(
            name="idea_set_status",
            description="Update an idea's status. Valid: raw, refining, ready, abandoned, done.",
            inputSchema={
                "type": "object",
                "properties": {
                    "idea_id": {"type": "string"},
                    "status": {"type": "string", "enum": list(VALID_IDEA_STATUSES)},
                },
                "required": ["idea_id", "status"],
            },
        ),
        Tool(
            name="idea_promote_to_task",
            description=(
                "Promote an idea to a task in the tasks table. Creates a new task with title from "
                "the idea, links bidirectionally (notes.linked_tasks ← task_id, task.notes references "
                "the idea), and marks the idea as 'ready'. Optional: project_id, area (default 'proyecto'), "
                "priority (default 'media')."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "idea_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "area": {"type": "string", "enum": list(VALID_TASK_AREAS), "default": "proyecto"},
                    "priority": {"type": "string", "enum": list(VALID_TASK_PRIORITIES), "default": "media"},
                },
                "required": ["idea_id"],
            },
        ),
        Tool(
            name="research_append_finding",
            description="Append a finding to a research note. Each finding has a source and a body.",
            inputSchema={
                "type": "object",
                "properties": {
                    "research_id": {"type": "string"},
                    "source": {"type": "string"},
                    "finding": {"type": "string"},
                },
                "required": ["research_id", "source", "finding"],
            },
        ),
        Tool(
            name="research_set_conclusion",
            description="Set the conclusion of a research note (overwrites previous if any).",
            inputSchema={
                "type": "object",
                "properties": {
                    "research_id": {"type": "string"},
                    "conclusion": {"type": "string"},
                },
                "required": ["research_id", "conclusion"],
            },
        ),
        Tool(
            name="research_link_to_decision",
            description=(
                "Link a research note to a decision (ADR). Updates linked_decisions on the research "
                "side. The link is one-way (research → decision); the decision can be queried for "
                "research that links to it via search."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "research_id": {"type": "string"},
                    "decision_id": {"type": "string"},
                },
                "required": ["research_id", "decision_id"],
            },
        ),
        Tool(
            name="diary_append_today",
            description=(
                "Append a personal note to today's diary entry. Creates the entry if it doesn't exist. "
                "Required: personal_note. Optional: auto_summary (overwrites the auto field)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "personal_note": {"type": "string", "minLength": 1},
                    "auto_summary": {"type": "string"},
                },
                "required": ["personal_note"],
            },
        ),
        # ── typed reads (Phase D) ──
        Tool(
            name="decision_list",
            description="List decisions (ADRs). Optional filters: project_id, limit (default 50, max 200).",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
            },
        ),
        Tool(
            name="idea_list",
            description="List ideas. Optional filters: status, project_id, limit (default 50, max 200).",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": list(VALID_IDEA_STATUSES)},
                    "project_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
            },
        ),
        Tool(
            name="research_list",
            description=(
                "List research notes. Optional filters: topic (substring match on metadata.topic), "
                "project_id, limit (default 50, max 200)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "project_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
            },
        ),
        Tool(
            name="diary_get_today",
            description="Get today's diary entry (or null if none exists yet).",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="diary_get",
            description="Get the diary entry for a specific date (YYYY-MM-DD), or null.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
                },
                "required": ["date"],
            },
        ),
        Tool(
            name="diary_list",
            description="List recent diary entries, newest first. Optional limit (default 30, max 200).",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 30},
                },
            },
        ),
        # ── inbox ──
        Tool(
            name="inbox_list",
            description=(
                "List inbox items (recordatorios, quick captures). Filters: kind, untriaged_only "
                "(default false), limit (default 50, max 200)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(VALID_INBOX_KINDS)},
                    "untriaged_only": {"type": "boolean", "default": False},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
            },
        ),
        Tool(
            name="inbox_create",
            description=(
                "Create an inbox item — Arturo's quick capture. Required: kind, title. "
                "Optional: body, source."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(VALID_INBOX_KINDS)},
                    "title": {"type": "string", "minLength": 1},
                    "body": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["kind", "title"],
            },
        ),
    ]


# ────────────────────────── notes (generic) ──────────────────────────
def _note_list(args: dict[str, Any]) -> list[dict[str, Any]]:
    where, params = [], []
    if args.get("type"):
        where.append("type = ?")
        params.append(args["type"])
    if args.get("project_id"):
        where.append("project_id = ?")
        params.append(args["project_id"])
    if args.get("tag"):
        where.append("tags LIKE ?")
        params.append(f"%{args['tag']}%")
    if args.get("status"):
        where.append("status = ?")
        params.append(args["status"])
    sql = "SELECT * FROM notes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(min(int(args.get("limit", 50)), 200))
    with _ro_conn() as c:
        return [_row(r) for r in c.execute(sql, params)]


def _note_get(note_id: str) -> dict[str, Any] | None:
    with _ro_conn() as c:
        r = c.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return _row(r) if r else None


def _note_create(args: dict[str, Any]) -> dict[str, Any]:
    title = args["title"].strip()
    if not title:
        raise ValueError("title cannot be empty")
    note_type = args.get("type", "note")
    if note_type not in VALID_NOTE_TYPES:
        raise ValueError(f"invalid type: {note_type}")
    metadata = args.get("metadata")
    metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata is not None else None
    note_id = _new_note_id()
    now = _now()
    with _rw_conn() as c:
        c.execute(
            "INSERT INTO notes (id, title, content, project_id, tags, type, metadata, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                note_id,
                title,
                args.get("content"),
                args.get("project_id"),
                args.get("tags"),
                note_type,
                metadata_json,
                args.get("status"),
                now,
                now,
            ),
        )
        c.commit()
        return _row(c.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone())


def _note_update(args: dict[str, Any]) -> dict[str, Any]:
    note_id = args["note_id"]
    fields, params = [], []
    for col in ("title", "content", "tags", "status"):
        if col in args and args[col] is not None:
            fields.append(f"{col} = ?")
            params.append(args[col])
    if "metadata" in args and args["metadata"] is not None:
        fields.append("metadata = ?")
        params.append(json.dumps(args["metadata"], ensure_ascii=False))
    if not fields:
        raise ValueError("nothing to update — provide at least one of title/content/tags/status/metadata")
    fields.append("updated_at = ?")
    params.append(_now())
    params.append(note_id)
    with _rw_conn() as c:
        cur = c.execute(f"UPDATE notes SET {', '.join(fields)} WHERE id = ?", params)
        if cur.rowcount == 0:
            raise ValueError(f"note not found: {note_id}")
        c.commit()
        return _row(c.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone())


# ────────────────────────── typed creates ──────────────────────────
def _decision_create(args: dict[str, Any]) -> dict[str, Any]:
    metadata = {
        "context": args["context"],
        "decision": args["decision"],
        "alternatives": args.get("alternatives", []),
        "consequences": args.get("consequences", []),
    }
    return _note_create(
        {
            "title": args["title"],
            "type": "decision",
            "metadata": metadata,
            "project_id": args.get("project_id"),
            "status": "ready",
        }
    )


def _idea_create(args: dict[str, Any]) -> dict[str, Any]:
    return _note_create(
        {
            "title": args["title"],
            "type": "idea",
            "content": args.get("content"),
            "project_id": args.get("project_id"),
            "status": "raw",
        }
    )


def _research_create(args: dict[str, Any]) -> dict[str, Any]:
    metadata = {
        "topic": args["topic"],
        "sources": args.get("sources", []),
        "findings": [],
        "conclusion": None,
    }
    return _note_create(
        {
            "title": args["title"],
            "type": "research",
            "metadata": metadata,
            "project_id": args.get("project_id"),
            "status": "refining",
        }
    )


# ────────────────────────── rich verbs (Phase C) ──────────────────────────
def _require_note_of_type(c: sqlite3.Connection, note_id: str, expected_type: str) -> sqlite3.Row:
    row = c.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        raise ValueError(f"note not found: {note_id}")
    if row["type"] != expected_type:
        raise ValueError(f"note {note_id} is type '{row['type']}', expected '{expected_type}'")
    return row


def _idea_append(args: dict[str, Any]) -> dict[str, Any]:
    idea_id = args["idea_id"]
    extra = args["content"]
    with _rw_conn() as c:
        row = _require_note_of_type(c, idea_id, "idea")
        existing = row["content"] or ""
        new_content = existing + ("\n\n" if existing else "") + extra
        c.execute(
            "UPDATE notes SET content = ?, updated_at = ? WHERE id = ?",
            (new_content, _now(), idea_id),
        )
        c.commit()
        return _row(c.execute("SELECT * FROM notes WHERE id = ?", (idea_id,)).fetchone())


def _idea_set_status(args: dict[str, Any]) -> dict[str, Any]:
    idea_id = args["idea_id"]
    status = args["status"]
    if status not in VALID_IDEA_STATUSES:
        raise ValueError(f"invalid idea status: {status}")
    with _rw_conn() as c:
        _require_note_of_type(c, idea_id, "idea")
        c.execute(
            "UPDATE notes SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), idea_id),
        )
        c.commit()
        return _row(c.execute("SELECT * FROM notes WHERE id = ?", (idea_id,)).fetchone())


def _idea_promote_to_task(args: dict[str, Any]) -> dict[str, Any]:
    idea_id = args["idea_id"]
    area = args.get("area", "proyecto")
    if area not in VALID_TASK_AREAS:
        raise ValueError(f"invalid area: {area}")
    priority = args.get("priority", "media")
    if priority not in VALID_TASK_PRIORITIES:
        raise ValueError(f"invalid priority: {priority}")
    project_id = args.get("project_id")
    task_id = f"task-{uuid.uuid4().hex[:12]}"
    now = _now()
    with _rw_conn() as c:
        idea = _require_note_of_type(c, idea_id, "idea")
        # Build task notes that reference the idea
        task_notes = (
            f"Promoted from idea {idea_id}: {idea['title']}\n\n"
            f"--- idea content ---\n{idea['content'] or '(empty)'}"
        )
        c.execute(
            "INSERT INTO tasks (id, title, description, area, project_id, status, priority, "
            "urgent, source, notes, created_at, updated_at, assigned_to_yume, assigned_to_claude) "
            "VALUES (?, ?, ?, ?, ?, 'inbox', ?, 0, 'mcp:notes:promote', ?, ?, ?, 0, 0)",
            (
                task_id,
                idea["title"],
                idea["content"],
                area,
                project_id,
                priority,
                task_notes,
                now,
                now,
            ),
        )
        # Append task_id to the idea's linked_tasks
        existing_links_raw = idea["linked_tasks"]
        try:
            existing_links = json.loads(existing_links_raw) if existing_links_raw else []
        except (TypeError, json.JSONDecodeError):
            existing_links = []
        if not isinstance(existing_links, list):
            existing_links = []
        existing_links.append(task_id)
        c.execute(
            "UPDATE notes SET linked_tasks = ?, status = 'ready', updated_at = ? WHERE id = ?",
            (json.dumps(existing_links), now, idea_id),
        )
        c.commit()
        return {
            "task": _row(c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()),
            "idea": _row(c.execute("SELECT * FROM notes WHERE id = ?", (idea_id,)).fetchone()),
        }


def _research_append_finding(args: dict[str, Any]) -> dict[str, Any]:
    research_id = args["research_id"]
    source = args["source"]
    finding = args["finding"]
    with _rw_conn() as c:
        row = _require_note_of_type(c, research_id, "research")
        try:
            md = json.loads(row["metadata"]) if row["metadata"] else {}
        except json.JSONDecodeError:
            md = {}
        findings = md.get("findings") or []
        if not isinstance(findings, list):
            findings = []
        findings.append({"source": source, "finding": finding, "added_at": _now()})
        md["findings"] = findings
        # Also extend sources if the source is new
        sources = md.get("sources") or []
        if not isinstance(sources, list):
            sources = []
        if source not in sources:
            sources.append(source)
        md["sources"] = sources
        c.execute(
            "UPDATE notes SET metadata = ?, updated_at = ? WHERE id = ?",
            (json.dumps(md, ensure_ascii=False), _now(), research_id),
        )
        c.commit()
        return _row(c.execute("SELECT * FROM notes WHERE id = ?", (research_id,)).fetchone())


def _research_set_conclusion(args: dict[str, Any]) -> dict[str, Any]:
    research_id = args["research_id"]
    conclusion = args["conclusion"]
    with _rw_conn() as c:
        row = _require_note_of_type(c, research_id, "research")
        try:
            md = json.loads(row["metadata"]) if row["metadata"] else {}
        except json.JSONDecodeError:
            md = {}
        md["conclusion"] = conclusion
        c.execute(
            "UPDATE notes SET metadata = ?, status = 'ready', updated_at = ? WHERE id = ?",
            (json.dumps(md, ensure_ascii=False), _now(), research_id),
        )
        c.commit()
        return _row(c.execute("SELECT * FROM notes WHERE id = ?", (research_id,)).fetchone())


def _research_link_to_decision(args: dict[str, Any]) -> dict[str, Any]:
    research_id = args["research_id"]
    decision_id = args["decision_id"]
    with _rw_conn() as c:
        row = _require_note_of_type(c, research_id, "research")
        # Verify the decision exists and is actually a decision
        _require_note_of_type(c, decision_id, "decision")
        existing_raw = row["linked_decisions"]
        try:
            existing = json.loads(existing_raw) if existing_raw else []
        except (TypeError, json.JSONDecodeError):
            existing = []
        if not isinstance(existing, list):
            existing = []
        if decision_id not in existing:
            existing.append(decision_id)
        c.execute(
            "UPDATE notes SET linked_decisions = ?, updated_at = ? WHERE id = ?",
            (json.dumps(existing), _now(), research_id),
        )
        c.commit()
        return _row(c.execute("SELECT * FROM notes WHERE id = ?", (research_id,)).fetchone())


def _diary_append_today(args: dict[str, Any]) -> dict[str, Any]:
    today = _today_iso_date()
    note = args["personal_note"]
    auto = args.get("auto_summary")
    with _rw_conn() as c:
        existing = c.execute(
            "SELECT * FROM notes WHERE type = 'diary' AND json_extract(metadata, '$.date') = ?",
            (today,),
        ).fetchone()
        if existing:
            md = json.loads(existing["metadata"] or "{}")
            personal = md.get("personal_notes") or []
            if isinstance(personal, str):
                personal = [personal]
            personal.append(note)
            md["personal_notes"] = personal
            if auto is not None:
                md["auto_summary"] = auto
            c.execute(
                "UPDATE notes SET metadata = ?, updated_at = ? WHERE id = ?",
                (json.dumps(md, ensure_ascii=False), _now(), existing["id"]),
            )
            c.commit()
            return _row(c.execute("SELECT * FROM notes WHERE id = ?", (existing["id"],)).fetchone())
        # Create new diary entry for today
        md = {"date": today, "auto_summary": auto, "personal_notes": [note]}
        return _note_create(
            {
                "title": f"Diary {today}",
                "type": "diary",
                "metadata": md,
                "status": "ready",
            }
        )


# ────────────────────────── typed reads (Phase D) ──────────────────────────
def _decision_list(args: dict[str, Any]) -> list[dict[str, Any]]:
    return _note_list({**args, "type": "decision"})


def _idea_list(args: dict[str, Any]) -> list[dict[str, Any]]:
    return _note_list({**args, "type": "idea"})


def _research_list(args: dict[str, Any]) -> list[dict[str, Any]]:
    where, params = ["type = 'research'"], []
    if args.get("project_id"):
        where.append("project_id = ?")
        params.append(args["project_id"])
    if args.get("topic"):
        where.append("json_extract(metadata, '$.topic') LIKE ?")
        params.append(f"%{args['topic']}%")
    sql = "SELECT * FROM notes WHERE " + " AND ".join(where) + " ORDER BY updated_at DESC LIMIT ?"
    params.append(min(int(args.get("limit", 50)), 200))
    with _ro_conn() as c:
        return [_row(r) for r in c.execute(sql, params)]


def _diary_get(date: str) -> dict[str, Any] | None:
    with _ro_conn() as c:
        r = c.execute(
            "SELECT * FROM notes WHERE type = 'diary' AND json_extract(metadata, '$.date') = ?",
            (date,),
        ).fetchone()
        return _row(r) if r else None


def _diary_get_today() -> dict[str, Any] | None:
    return _diary_get(_today_iso_date())


def _diary_list(args: dict[str, Any]) -> list[dict[str, Any]]:
    limit = min(int(args.get("limit", 30)), 200)
    with _ro_conn() as c:
        rows = c.execute(
            "SELECT * FROM notes WHERE type = 'diary' ORDER BY json_extract(metadata, '$.date') DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row(r) for r in rows]


# ────────────────────────── inbox ──────────────────────────
def _inbox_list(args: dict[str, Any]) -> list[dict[str, Any]]:
    where, params = [], []
    if args.get("kind"):
        where.append("kind = ?")
        params.append(args["kind"])
    if args.get("untriaged_only"):
        where.append("triaged = 0")
    sql = "SELECT * FROM inbox_items"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(min(int(args.get("limit", 50)), 200))
    with _ro_conn() as c:
        return [_row(r) for r in c.execute(sql, params)]


def _inbox_create(args: dict[str, Any]) -> dict[str, Any]:
    kind = args["kind"]
    if kind not in VALID_INBOX_KINDS:
        raise ValueError(f"invalid kind: {kind}")
    title = args["title"].strip()
    if not title:
        raise ValueError("title cannot be empty")
    item_id = f"inbox-{uuid.uuid4().hex[:12]}"
    now = _now()
    with _rw_conn() as c:
        c.execute(
            "INSERT INTO inbox_items (id, kind, title, body, source, triaged, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
            (item_id, kind, title, args.get("body"), args.get("source", "mcp:notes"), now, now),
        )
        c.commit()
        return _row(c.execute("SELECT * FROM inbox_items WHERE id = ?", (item_id,)).fetchone())


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        args = arguments or {}
        if name == "note_list":
            payload: Any = _note_list(args)
        elif name == "note_get":
            payload = _note_get(args["note_id"])
        elif name == "note_create":
            payload = _note_create(args)
        elif name == "note_update":
            payload = _note_update(args)
        elif name == "decision_create":
            payload = _decision_create(args)
        elif name == "idea_create":
            payload = _idea_create(args)
        elif name == "research_create":
            payload = _research_create(args)
        elif name == "idea_append":
            payload = _idea_append(args)
        elif name == "idea_set_status":
            payload = _idea_set_status(args)
        elif name == "idea_promote_to_task":
            payload = _idea_promote_to_task(args)
        elif name == "research_append_finding":
            payload = _research_append_finding(args)
        elif name == "research_set_conclusion":
            payload = _research_set_conclusion(args)
        elif name == "research_link_to_decision":
            payload = _research_link_to_decision(args)
        elif name == "diary_append_today":
            payload = _diary_append_today(args)
        elif name == "decision_list":
            payload = _decision_list(args)
        elif name == "idea_list":
            payload = _idea_list(args)
        elif name == "research_list":
            payload = _research_list(args)
        elif name == "diary_get_today":
            payload = _diary_get_today()
        elif name == "diary_get":
            payload = _diary_get(args["date"])
        elif name == "diary_list":
            payload = _diary_list(args)
        elif name == "inbox_list":
            payload = _inbox_list(args)
        elif name == "inbox_create":
            payload = _inbox_create(args)
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
