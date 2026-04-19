#!/usr/bin/env python3
"""
Niwa task executor — host-side worker for autonomous task execution.

Polls the Niwa database for pending tasks, dispatches each to a configured LLM
CLI, captures the output, and updates the task status. Designed to run as a
launchd agent (macOS) or systemd unit (Linux), keep-alive.

Reads its config from niwa.env in the install dir (looked up via NIWA_HOME env
or falls back to ~/.niwa). Required env vars in niwa.env:

    NIWA_DB_PATH                  path to niwa.sqlite3
    NIWA_LLM_COMMAND              shell command to run per task (gets prompt as arg)
    NIWA_EXECUTOR_POLL_SECONDS    poll interval (default 30)
    NIWA_EXECUTOR_TIMEOUT_SECONDS per-task timeout (default 1800 = 30 min)
    NIWA_EXECUTOR_MAX_OUTPUT      max chars of output to store (default 10000)

Zero external dependencies. Python stdlib only.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── v0.2 routing imports (PR-06, Bug 20 fix in PR-27) ───────────────
# The executor must be able to import backend modules for v0.2 routing.
#
# Resolution order:
#   1. ``NIWA_BACKEND_DIR`` env var (set by the installer in the
#      systemd unit — points at a niwa-readable copy of the backend
#      tree, typically ``/opt/<instance>/niwa-app/backend``).
#   2. Fallback to ``<this file>/../niwa-app/backend``, which only
#      resolves correctly when the executor runs from the repo
#      checkout (dev / CI).
#
# Bug 20 history: the executor is copied by ``setup.py`` to
# ``/home/niwa/.<instance>/bin/task-executor.py``, which makes the
# relative ``__file__`` path resolve to
# ``/home/niwa/.<instance>/niwa-app/backend`` — a directory that
# ``setup.py`` never created. The ``sys.path.insert`` below then
# silently pushed a non-existent path and ``import routing_service``
# raised ``ModuleNotFoundError``. The tier-3 fallback hid it for
# months. The env-var indirection makes the resolution explicit and
# installer-controlled.
_env_backend_dir = os.environ.get("NIWA_BACKEND_DIR")
if _env_backend_dir:
    _BACKEND_DIR = Path(_env_backend_dir)
else:
    _BACKEND_DIR = Path(__file__).resolve().parent.parent / "niwa-app" / "backend"

if not _BACKEND_DIR.is_dir():
    # Fail loud. PR-25's health check will turn a fail-loud exit
    # here into a visible install abort within 15 s, so the operator
    # sees a real error instead of a silent fallback to legacy.
    print(
        f"FATAL: niwa backend modules not found at {_BACKEND_DIR}.\n"
        f"  - If running from a repo checkout, keep bin/task-executor.py\n"
        f"    peer of niwa-app/backend/.\n"
        f"  - If running from a systemd install, set NIWA_BACKEND_DIR\n"
        f"    in the unit's Environment= to the installed backend tree\n"
        f"    (typically /opt/<instance>/niwa-app/backend).",
        file=sys.stderr,
    )
    sys.exit(2)

if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


# ────────────────────── task state machine ─────────────────────────
# Canonical source of truth: niwa-app/backend/state_machines.py
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


# ────────────────────────── env / config ──────────────────────────
def _read_env_file(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1].replace('\\"', '"')
        out[key.strip()] = value
    return out


def _resolve_install_dir() -> Path:
    candidates = []
    env_home = os.environ.get("NIWA_HOME")
    if env_home:
        candidates.append(Path(env_home))
    candidates.append(Path.home() / ".niwa")
    for c in candidates:
        if (c / "secrets" / "mcp.env").exists():
            return c
    raise SystemExit(
        "Could not find a Niwa install (looked for ~/.niwa or $NIWA_HOME). "
        "Run `niwa install` first."
    )


INSTALL_DIR = _resolve_install_dir()
ENV = _read_env_file(INSTALL_DIR / "secrets" / "mcp.env")

_SETTINGS_PATH = (
    Path(ENV.get("NIWA_DB_PATH", str(INSTALL_DIR / "data" / "niwa.sqlite3"))).parent
    / "settings.json"
)
_SETTINGS: dict = {}
# Read from settings.json (legacy fallback — app.py migrates this to SQLite on startup,
# but the executor may start before the app. Remove once all installs have migrated.)
if _SETTINGS_PATH.exists():
    try:
        _SETTINGS = json.loads(_SETTINGS_PATH.read_text())
    except Exception:
        pass


def _read_db_settings() -> dict:
    """Read all settings from SQLite settings table."""
    _db = ENV.get("NIWA_DB_PATH") or str(INSTALL_DIR / "data" / "niwa.sqlite3")
    try:
        c = sqlite3.connect(_db, timeout=5)
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT key, value FROM settings").fetchall()
        c.close()
        return {r["key"]: r["value"] for r in rows}
    except Exception:
        return {}


# Merge DB settings (primary) with JSON settings (legacy fallback)
_DB_SETTINGS = _read_db_settings()
_SETTINGS.update(_DB_SETTINGS)


def _cfg(key: str, env_key: str, default: str = "") -> str:
    return (_SETTINGS.get(f"int.{key}") or ENV.get(env_key, "") or default).strip()


DB_PATH = ENV.get("NIWA_DB_PATH") or str(INSTALL_DIR / "data" / "niwa.sqlite3")
LLM_COMMAND = _cfg("llm_command", "NIWA_LLM_COMMAND")
LLM_COMMAND_CHAT = _cfg("llm_command_chat", "NIWA_LLM_COMMAND_CHAT") or ""
LLM_COMMAND_PLANNER = _cfg("llm_command_planner", "NIWA_LLM_COMMAND_PLANNER") or ""
LLM_COMMAND_EXECUTOR = _cfg("llm_command_executor", "NIWA_LLM_COMMAND_EXECUTOR") or ""
PLANNER_TIMEOUT = int(ENV.get("NIWA_EXECUTOR_PLANNER_TIMEOUT_SECONDS", "300"))
PLANNER_MAX_TURNS = int(ENV.get("NIWA_EXECUTOR_PLANNER_MAX_TURNS", "10"))
# PR-B4a: description length above which the planner is auto-invoked
# even without an explicit ``decompose=1`` flag on the task.
PLANNER_DESCRIPTION_THRESHOLD = int(
    os.environ.get("NIWA_PLANNER_DESCRIPTION_THRESHOLD")
    or ENV.get("NIWA_PLANNER_DESCRIPTION_THRESHOLD")
    or "400"
)
LLM_API_KEY = _cfg("llm_api_key", "NIWA_LLM_API_KEY")
# Read setup token from new service key OR legacy key
LLM_SETUP_TOKEN = (_SETTINGS.get("svc.llm.anthropic.setup_token") or _cfg("llm_setup_token", "NIWA_LLM_SETUP_TOKEN"))
POLL_SECONDS = int(_cfg("executor_poll_seconds", "NIWA_EXECUTOR_POLL_SECONDS", "30"))
CHAT_POLL_SECONDS = int(ENV.get("NIWA_EXECUTOR_CHAT_POLL_SECONDS", "5"))
TIMEOUT_SECONDS = int(_cfg("executor_timeout_seconds", "NIWA_EXECUTOR_TIMEOUT_SECONDS", "1800"))
CHAT_TIMEOUT_SECONDS = int(ENV.get("NIWA_EXECUTOR_CHAT_TIMEOUT_SECONDS", "120"))
MAX_OUTPUT_CHARS = int(ENV.get("NIWA_EXECUTOR_MAX_OUTPUT", "10000"))
HEARTBEAT_SECONDS = int(ENV.get("NIWA_EXECUTOR_HEARTBEAT_SECONDS", "60"))
MAX_CONSECUTIVE_FAILURES = int(ENV.get("NIWA_EXECUTOR_MAX_FAILURES", "3"))
MAX_WORKERS = int(ENV.get("NIWA_EXECUTOR_MAX_WORKERS", "3"))
PUBLIC_URL = ENV.get("NIWA_PUBLIC_URL", "").strip()

# OpenClaw worker mode — when OpenClaw is the orchestrator, executor only runs
# tasks explicitly assigned by OpenClaw (source='openclaw') and skips the planner tier.
OPENCLAW_MODE = _SETTINGS.get('svc.openclaw.mode', 'disabled')
WORKER_MODE = OPENCLAW_MODE in ('mcp_client', 'bidirectional')

# Context limits — keep prompts reasonable
MAX_CONTEXT_TASKS = int(ENV.get("NIWA_EXECUTOR_CONTEXT_TASKS", "20"))
MAX_CONTEXT_NOTES = int(ENV.get("NIWA_EXECUTOR_CONTEXT_NOTES", "5"))
MAX_NOTE_CHARS = int(ENV.get("NIWA_EXECUTOR_CONTEXT_NOTE_CHARS", "500"))


# ────────────────────────── logging ──────────────────────────
LOG_PATH = INSTALL_DIR / "logs" / "executor.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
from logging.handlers import RotatingFileHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(str(LOG_PATH), maxBytes=10 * 1024 * 1024, backupCount=3),
    ],
)
log = logging.getLogger("niwa-executor")


# ────────────────────────── DB helpers ──────────────────────────
def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=10000")
        c.execute("PRAGMA foreign_keys=ON")
    except sqlite3.OperationalError:
        pass
    return c


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _claim_next_task() -> Optional[sqlite3.Row]:
    """Atomically pick the oldest pending task and mark it en_progreso."""
    with _conn() as c:
        row = c.execute(
            """
            SELECT * FROM tasks
            WHERE status = 'pendiente'
            ORDER BY CASE priority
              WHEN 'critica'  THEN 4 WHEN 'critical' THEN 4
              WHEN 'alta'     THEN 3 WHEN 'high'     THEN 3
              WHEN 'media'    THEN 2 WHEN 'medium'   THEN 2
              WHEN 'baja'     THEN 1 WHEN 'low'      THEN 1
              ELSE 0 END DESC, created_at ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        c.execute(
            "UPDATE tasks SET status='en_progreso', updated_at=? WHERE id=? AND status='pendiente'",
            (_now_iso(), row["id"]),
        )
        changed = c.execute("SELECT changes()").fetchone()[0]
        if changed == 0:
            return None
        c.commit()
        return c.execute("SELECT * FROM tasks WHERE id=?", (row["id"],)).fetchone()


def _claim_next_openclaw_task() -> Optional[sqlite3.Row]:
    """Worker mode: only pick tasks explicitly assigned by OpenClaw (source='openclaw')."""
    with _conn() as c:
        row = c.execute(
            """
            SELECT * FROM tasks
            WHERE status = 'pendiente'
            AND source = 'openclaw'
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        c.execute(
            "UPDATE tasks SET status='en_progreso', updated_at=? WHERE id=? AND status='pendiente'",
            (_now_iso(), row["id"]),
        )
        if c.execute("SELECT changes()").fetchone()[0] == 0:
            return None
        c.commit()
        return c.execute("SELECT * FROM tasks WHERE id=?", (row["id"],)).fetchone()


# ─────────────── PR-38: auto-registro de proyecto ───────────────

# Root directory where project folders live on the host. MUST be
# writable by the user that runs this executor (typically ``niwa``).
#
# Previous default lived under ``$INSTALL_DIR/data/projects`` which on
# sudo installs resolves to ``/root/.niwa/data/projects`` — owned by
# root and not writable by the ``niwa`` user. That caused Claude to
# fall back to ``/tmp`` silently (Bug 34 root cause).
#
# The env var ``NIWA_PROJECTS_ROOT`` takes precedence (set by the
# installer in mcp.env). Fallback is the executor user's home +
# ``projects`` which, for the ``niwa`` user, is ``/home/niwa/projects``.
def _resolve_projects_root() -> Path:
    env_root = os.environ.get("NIWA_PROJECTS_ROOT") or ENV.get("NIWA_PROJECTS_ROOT")
    if env_root:
        return Path(env_root)
    try:
        return Path.home() / "projects"
    except Exception:
        return INSTALL_DIR / "data" / "projects"


_AUTO_PROJECTS_ROOT = _resolve_projects_root()

# Best-effort: ensure the root exists at startup so we don't fail on
# the first task. Silent-OK if we can't create it — we'll log when a
# task actually tries and fails.
try:
    _AUTO_PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

_SLUG_ALLOWED = re.compile(r"[^a-z0-9-]+")


def _sanitize_slug(raw: str, fallback: str = "task") -> str:
    """Produce a filesystem-safe slug from a task title.

    Lowercases, replaces runs of non-[a-z0-9-] with '-', trims '-' from
    both ends, caps length at 40. Returns ``fallback`` if the result is
    empty (e.g. the title was all whitespace or all punctuation).
    """
    s = _SLUG_ALLOWED.sub("-", (raw or "").lower()).strip("-")
    s = s[:40].strip("-")
    return s or fallback


def _auto_project_prepare(task_dict: dict) -> Optional[dict]:
    """Pre-create a project directory for tasks without a project_id.

    Mutates ``task_dict`` by setting ``project_directory`` (so the
    backend adapter picks it up as cwd) and returns a context dict for
    the post-hook. If the task already has a ``project_id`` (user
    attached it explicitly), returns ``None`` — no auto-creation.

    Idempotency: the directory is created with ``exist_ok=True`` but
    the slug includes a random suffix, so the same task being retried
    won't pile up empty dirs — ``_auto_project_finalize`` cleans up
    empties.
    """
    if task_dict.get("project_id"):
        return None

    title = task_dict.get("title") or ""
    base = _sanitize_slug(title, fallback="task")
    slug = f"{base}-{uuid.uuid4().hex[:6]}"
    project_dir = _AUTO_PROJECTS_ROOT / slug

    try:
        project_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.warning(
            "auto-project: could not create %s: %s — skipping auto-registration",
            project_dir, e,
        )
        return None

    task_dict["project_directory"] = str(project_dir)
    return {
        "slug": slug,
        "directory": str(project_dir),
        "name": title or slug,
    }


def _auto_project_has_files(project_dir: Path) -> bool:
    """True iff ``project_dir`` contains at least one regular file
    (recursive, ignoring dotfiles at the top level)."""
    if not project_dir.is_dir():
        return False
    for p in project_dir.rglob("*"):
        if p.is_file() and not p.name.startswith("."):
            return True
    return False


def _auto_project_finalize(ctx: dict, task_id: str) -> None:
    """Run after adapter.start() to commit or discard the auto-project.

    - If the directory has no files: rmdir it AND drop the ``projects``
      row (if any) that Claude created via ``project_create`` MCP tool
      but never followed up with actual files. Otherwise the UI would
      show a phantom project. Also null out ``tasks.project_id`` for
      any task that got attached to that phantom row (PR-52 orphan
      policy).
    - If it has files and there is no ``projects`` row pointing at
      ``directory``: insert one (Claude wrote artifacts but did not
      call the ``project_create`` MCP tool).
    - In either "has files" branch: associate ``tasks.project_id`` to
      the row pointing at the directory, so the task shows up under
      its project in the UI.
    """
    project_dir = Path(ctx["directory"])
    if not _auto_project_has_files(project_dir):
        try:
            if project_dir.is_dir():
                shutil.rmtree(project_dir)
        except OSError:
            log.warning("auto-project: could not cleanup empty %s", project_dir)
        # Orphan cleanup: if Claude called ``project_create`` but then
        # wrote nothing useful, drop the row and detach tasks.
        try:
            with _conn() as c:
                row = c.execute(
                    "SELECT id FROM projects WHERE directory=?",
                    (ctx["directory"],),
                ).fetchone()
                if row:
                    c.execute(
                        "UPDATE tasks SET project_id=NULL "
                        "WHERE project_id=?",
                        (row["id"],),
                    )
                    c.execute(
                        "DELETE FROM projects WHERE id=?",
                        (row["id"],),
                    )
                    c.commit()
                    log.info(
                        "auto-project: orphan cleanup removed phantom "
                        "project %s (directory %s had no files)",
                        row["id"], ctx["directory"],
                    )
        except Exception:
            log.warning(
                "auto-project: orphan cleanup failed for %s",
                ctx["directory"], exc_info=True,
            )
        return

    now = _now_iso()
    with _conn() as c:
        row = c.execute(
            "SELECT id FROM projects WHERE directory=?",
            (ctx["directory"],),
        ).fetchone()
        if row:
            proj_id = row["id"]
        else:
            proj_id = f"proj-{uuid.uuid4().hex[:12]}"
            # Slug already carries a random suffix, so UNIQUE should
            # hold. On the off chance of collision (pre-existing row
            # with that slug but a different directory), degrade to a
            # longer suffix rather than crashing the executor.
            slug = ctx["slug"]
            existing_slug = c.execute(
                "SELECT id FROM projects WHERE slug=?", (slug,),
            ).fetchone()
            if existing_slug:
                slug = f"{slug}-{uuid.uuid4().hex[:4]}"
            c.execute(
                "INSERT INTO projects "
                "(id, slug, name, area, description, active, "
                " created_at, updated_at, directory, url) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (proj_id, slug, ctx["name"], "proyecto", "", 1,
                 now, now, ctx["directory"], ""),
            )

        c.execute(
            "UPDATE tasks SET project_id=?, updated_at=? "
            "WHERE id=? AND project_id IS NULL",
            (proj_id, now, task_id),
        )
        c.commit()


def _resolve_project_dir(project_id: Optional[str]) -> Optional[Path]:
    if not project_id:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT directory FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if row and row["directory"]:
            p = Path(row["directory"]).expanduser()
            if p.is_dir():
                return p
            # Auto-heal (PR-51): the project row declares a directory
            # that doesn't exist yet. If it lives under our managed
            # projects root (writable by us), mkdir it now so the
            # adapter/task can use it. Paths outside the root stay
            # untouched — they're user-provided and we don't want to
            # silently create arbitrary filesystem locations.
            try:
                projects_root = _AUTO_PROJECTS_ROOT.resolve()
                p_resolved = p.resolve()
                if str(p_resolved).startswith(str(projects_root) + os.sep) or p_resolved == projects_root:
                    p_resolved.mkdir(parents=True, exist_ok=True)
                    log.info(
                        "project_dir auto-heal: created %s for project %s",
                        p_resolved, project_id,
                    )
                    return p_resolved
                log.warning(
                    "project %s declares directory %s outside projects root %s; "
                    "not auto-creating",
                    project_id, p, projects_root,
                )
            except OSError as e:
                log.warning(
                    "project_dir auto-heal failed for %s: %s", p, e,
                )
    return None


# ────────────────────────── project context loader ──────────────────────────
def _load_memories(project_id: Optional[str]) -> list[dict]:
    """Load global + project-scoped memories to include in the prompt."""
    try:
        with _conn() as c:
            rows = c.execute(
                """
                SELECT key, value, category, project_id FROM memories
                WHERE project_id IS NULL OR project_id = ?
                ORDER BY category, updated_at DESC
                LIMIT 30
                """,
                (project_id or "",),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []  # table may not exist in older installs


def _load_project_context(project_id: Optional[str], current_task_id: str) -> dict:
    """Load rich context about the project to enrich the executor prompt."""
    ctx: dict = {
        "project": None,
        "tasks": [],
        "notes": [],
        "decisions": [],
        "events": [],
    }
    if not project_id:
        return ctx
    with _conn() as c:
        row = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row:
            ctx["project"] = dict(row)

        rows = c.execute(
            """
            SELECT id, title, status, priority, description, notes
            FROM tasks
            WHERE project_id=? AND id!=?
            ORDER BY
                CASE status
                    WHEN 'en_progreso' THEN 0
                    WHEN 'pendiente'   THEN 1
                    WHEN 'bloqueada'   THEN 2
                    WHEN 'revision'    THEN 3
                    WHEN 'hecha'       THEN 4
                    ELSE 5 END,
                updated_at DESC
            LIMIT ?
            """,
            (project_id, current_task_id, MAX_CONTEXT_TASKS),
        ).fetchall()
        ctx["tasks"] = [dict(r) for r in rows]

        try:
            rows = c.execute(
                """
                SELECT title, type, content, created_at
                FROM notes
                WHERE project_id=? AND type!='diary'
                ORDER BY updated_at DESC LIMIT ?
                """,
                (project_id, MAX_CONTEXT_NOTES),
            ).fetchall()
            ctx["notes"] = [dict(r) for r in rows]

            rows = c.execute(
                """
                SELECT title, content, created_at FROM notes
                WHERE project_id=? AND type='decision'
                ORDER BY updated_at DESC LIMIT 10
                """,
                (project_id,),
            ).fetchall()
            ctx["decisions"] = [dict(r) for r in rows]
        except Exception:
            pass

        try:
            rows = c.execute(
                """
                SELECT type, payload_json, created_at FROM task_events
                WHERE task_id=? ORDER BY created_at DESC LIMIT 10
                """,
                (current_task_id,),
            ).fetchall()
            ctx["events"] = [dict(r) for r in rows]
        except Exception:
            pass

    return ctx


def _format_task_line(t: dict) -> str:
    icon = {
        "hecha": "✓", "en_progreso": "▶", "pendiente": "○",
        "bloqueada": "✗", "revision": "◎", "inbox": "·",
    }.get(t.get("status", ""), "·")
    line = f"  {icon} [{t.get('priority', 'media')}] {t.get('title', '')}"
    if t.get("description"):
        line += f"\n      {t['description'][:120]}"
    return line


# ────────────────────────── prompt builder ──────────────────────────
def _build_prompt(task: sqlite3.Row, project_dir: Optional[Path]) -> str:
    ctx = _load_project_context(task["project_id"], task["id"])
    parts: list[str] = []

    # Project header
    if ctx["project"]:
        p = ctx["project"]
        parts.append(f"PROJECT: {p.get('name', '')} [{p.get('area', '')}]")
        if p.get("description"):
            parts.append(f"PROJECT DESCRIPTION: {p['description']}")
        if p.get("url"):
            parts.append(f"PROJECT URL: {p['url']}")

    if project_dir:
        parts.append(f"WORKING DIRECTORY: {project_dir}")
    if PUBLIC_URL:
        parts.append(f"PUBLIC URL: {PUBLIC_URL}")
        parts.append("When deploying web servers, use this as the base URL instead of localhost.")

    # Current task
    parts.append("")
    parts.append(f"CURRENT TASK: {task['title']}")
    parts.append(f"  priority: {task['priority']}  |  area: {task['area']}")
    if task["description"]:
        parts.append(f"  description: {task['description']}")
    if task["notes"]:
        parts.append(f"  notes: {task['notes'][:500]}")

    # Related tasks in project
    if ctx["tasks"]:
        active = [t for t in ctx["tasks"] if t["status"] not in ("hecha", "archivada")]
        done = [t for t in ctx["tasks"] if t["status"] == "hecha"]
        if active:
            parts.append("")
            parts.append("OTHER ACTIVE TASKS IN PROJECT:")
            for t in active[:10]:
                parts.append(_format_task_line(t))
        if done:
            parts.append("")
            parts.append(f"RECENTLY COMPLETED ({len(done)} tasks):")
            for t in done[:5]:
                parts.append(_format_task_line(t))

    # Architectural decisions
    if ctx["decisions"]:
        parts.append("")
        parts.append("ARCHITECTURAL DECISIONS:")
        for d in ctx["decisions"][:5]:
            content = (d.get("content") or "")[:MAX_NOTE_CHARS]
            parts.append(f"  [{d.get('created_at', '')[:10]}] {d.get('title', '')}")
            if content:
                parts.append(f"    {content}")

    # Project notes
    other_notes = [n for n in ctx["notes"] if n.get("type") != "decision"]
    if other_notes:
        parts.append("")
        parts.append("PROJECT NOTES:")
        for n in other_notes[:MAX_CONTEXT_NOTES]:
            content = (n.get("content") or "")[:MAX_NOTE_CHARS]
            parts.append(f"  [{n.get('type', 'note')}] {n.get('title', '')}")
            if content:
                parts.append(f"    {content}")

    # Memories
    memories = _load_memories(task["project_id"])
    if memories:
        parts.append("")
        parts.append("MEMORY (persistent knowledge from previous tasks):")
        by_cat: dict[str, list] = {}
        for m in memories:
            by_cat.setdefault(m.get("category", "general"), []).append(m)
        for cat, items in by_cat.items():
            parts.append(f"  [{cat}]")
            for m in items[:10]:
                scope = " (this project)" if m.get("project_id") else " (global)"
                parts.append(f"    {m['key']}: {m['value']}{scope}")

    # Instructions — different for chat vs tasks
    is_chat = dict(task).get("source") == "chat"
    parts.append("")
    if is_chat:
        parts.append("ROLE: You are Niwa's chat assistant. You are FAST and CONVERSATIONAL.")
        parts.append("You are Haiku — a lightweight model for quick responses.")
        parts.append("")
        parts.append("CRITICAL RULES:")
        parts.append("1. For simple questions, facts, planning, or conversation: answer directly.")
        parts.append("2. If the user asks for something that requires DOING WORK (coding, creating files,")
        parts.append("   refactoring, building, analysis, scripts, web pages, etc.):")
        parts.append("   a) Use the task_create MCP tool to create a task with a clear title and description")
        parts.append("   b) Set status='pendiente' so it gets picked up by the executor")
        parts.append("   b2) If working within a project context, pass project_id to task_create")
        parts.append("   c) Tell the user: 'He creado la tarea [title]. Se ejecutara automaticamente.'")
        parts.append("   d) STOP. Do NOT attempt the work yourself. Do NOT read/write files.")
        parts.append("   e) Do NOT ask follow-up questions about the task. Just create it and confirm.")
        parts.append("3. Use memory_store to save important facts the user mentions.")
        parts.append("4. Be brief. Max 2-3 sentences for simple responses.")
        parts.append("5. Reply in the same language the user writes in.")
        if PUBLIC_URL:
            parts.append(f"Note: The server's public URL is {PUBLIC_URL}. Use this for project URLs, not localhost.")
    else:
        parts.append("INSTRUCTIONS:")
        parts.append("1. Read any files relevant to understanding the task.")
        parts.append("2. Make the changes required.")
        parts.append("3. Verify your work (run tests/build/lint as appropriate).")
        parts.append("4. Reply with a brief summary of what you did.")
        parts.append("5. If the task is too large or unclear, explain why and stop.")
    parts.append("")
    parts.append("You have access to the Niwa MCP tools (tasks, notes, platform).")
    if not is_chat:
        parts.append("Use task_log to record findings or progress during your work.")
        parts.append("Use task_request_input if you need a human decision before proceeding.")

    return "\n".join(parts)


# ────────────────────────── heartbeat ──────────────────────────
class HeartbeatThread(threading.Thread):
    def __init__(self, task_id: str):
        super().__init__(daemon=True)
        self.task_id = task_id
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.wait(HEARTBEAT_SECONDS):
            try:
                with _conn() as c:
                    c.execute(
                        "UPDATE tasks SET updated_at=? WHERE id=? AND status='en_progreso'",
                        (_now_iso(), self.task_id),
                    )
                    c.commit()
            except Exception as e:
                log.warning("heartbeat failed for %s: %s", self.task_id, e)


# ────────────────────────── events ──────────────────────────
def _record_event(task_id: str, event_type: str, payload: dict) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO task_events(id,task_id,type,payload_json,created_at) VALUES(?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                task_id,
                event_type,
                json.dumps(payload, ensure_ascii=False),
                _now_iso(),
            ),
        )
        c.commit()


# ────────────────────────── OAuth token helpers ──────────────────────────
def _parse_jwt_payload(token: str):
    """Parse JWT payload without verification.
    NOTE: This duplicates oauth.parse_jwt(). Keep in sync."""
    if not token or token.count(".") != 2:
        return None
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None


def _refresh_openai_token(refresh_token: str):
    """Refresh OpenAI access token using refresh token."""
    try:
        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
        }).encode()
        req = urllib.request.Request("https://auth.openai.com/oauth/token", data=data, headers={
            "Content-Type": "application/x-www-form-urlencoded",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            token_data = json.loads(resp.read())
            new_access = token_data.get("access_token", "")
            new_refresh = token_data.get("refresh_token", refresh_token)
            claims = _parse_jwt_payload(new_access)
            expires = claims.get("exp", 0) if claims else 0
            with _conn() as c:
                c.execute(
                    'UPDATE oauth_tokens SET access_token=?, refresh_token=?, expires_at=?, updated_at=? WHERE provider=?',
                    (new_access, new_refresh, expires, _now_iso(), 'openai')
                )
                c.commit()
            return new_access
    except Exception as e:
        log.warning("Failed to refresh OpenAI token: %s", e)
        return None


def _get_openai_oauth_token():
    """Read fresh OpenAI OAuth token from DB, refreshing if needed."""
    try:
        with _conn() as c:
            row = c.execute(
                'SELECT access_token, refresh_token, expires_at FROM oauth_tokens WHERE provider=?',
                ('openai',)
            ).fetchone()
            if not row or not row['access_token']:
                return None
            expires = row['expires_at'] or 0
            if time.time() + 300 >= expires and row['refresh_token']:
                refreshed = _refresh_openai_token(row['refresh_token'])
                if refreshed:
                    return refreshed
                return None
            if time.time() + 300 >= expires:
                return None
            return row['access_token']
    except Exception:
        return None


def _get_openai_refresh_token():
    """Read OpenAI refresh token from DB."""
    try:
        with _conn() as c:
            row = c.execute(
                'SELECT refresh_token FROM oauth_tokens WHERE provider=?', ('openai',)
            ).fetchone()
            return row['refresh_token'] if row else None
    except Exception:
        return None


# ────────────────────────── task completion ──────────────────────────
def _finish_task(task_id: str, status: str, output: str) -> None:
    """
    Store executor output in task_events (not in task.notes) so human
    notes stay clean and executor output is queryable separately.
    """
    now = _now_iso()
    truncated = output[:MAX_OUTPUT_CHARS]
    if len(output) > MAX_OUTPUT_CHARS:
        truncated += "\n[output truncated]"

    with _conn() as c:
        row = c.execute("SELECT status, completed_at FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row:
            _assert_task_transition(row["status"], status)
        completed_at = now if status == "hecha" else (row["completed_at"] if row else None)
        c.execute(
            "UPDATE tasks SET status=?, updated_at=?, completed_at=? WHERE id=?",
            (status, now, completed_at, task_id),
        )
        c.commit()

    _record_event(task_id, "comment", {
        "author": "executor",
        "status": status,
        "output": truncated,
    })


# ────────────────────────── LLM runner ──────────────────────────


def _run_llm(prompt: str, cwd: Path, llm_command: str = "", timeout: int = 0) -> tuple[bool, str]:
    """Run LLM command with PTY so Claude Code output is captured.

    Claude Code writes to /dev/tty, bypassing stdout/stderr when piped.
    Using pty.openpty() gives it a real terminal to write to, and we
    read the master side to capture the output.
    """
    command = llm_command or LLM_COMMAND
    task_timeout = timeout or TIMEOUT_SECONDS
    if not command:
        return False, "NIWA_LLM_COMMAND is not configured"
    import pty, select
    # Pipe the prompt via stdin (see subprocess.Popen below). The old
    # approach wrote the prompt to a temp file and appended the path
    # as a positional argument — broken in two ways:
    #   1. ``claude -p <path>`` treats ``<path>`` as prompt *text*, not
    #      as a file reference. Claude then tries to open it via its
    #      Read tool permission system and fails, emitting
    #      "I need permission to read that file." as the whole output.
    #      Every task processed this way got garbage as its result.
    #   2. Long prompts passed as argv hit ``ENAMETOOLONG``.
    # Stdin piping avoids both. Verified empirically:
    #   ``claude -p /tmp/x.md``            → permission error
    #   ``cat /tmp/x.md | claude -p``       → correct answer
    cmd = shlex.split(command)
    log.info("exec in %s: %s ...", cwd, " ".join(shlex.quote(c) for c in cmd[:6]))
    run_env = os.environ.copy()
    run_env["TERM"] = "dumb"
    run_env["NO_COLOR"] = "1"
    # Only set keys not already in the environment to avoid overwriting
    if LLM_API_KEY:
        for key_name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
            if key_name not in run_env:
                run_env[key_name] = LLM_API_KEY
    if LLM_SETUP_TOKEN:
        run_env["CLAUDE_CODE_OAUTH_TOKEN"] = LLM_SETUP_TOKEN
    # Inject OpenAI OAuth token if available (for Codex CLI or direct API use)
    _codex_tmp_home = None
    openai_token = _get_openai_oauth_token()
    if openai_token:
        run_env["OPENAI_ACCESS_TOKEN"] = openai_token
        # Write temporary auth.json for Codex CLI compatibility
        import tempfile as _tmpfile
        _codex_tmp_home = _tmpfile.mkdtemp(prefix="niwa-codex-")
        auth_json = {
            "auth_mode": "chatgpt_oauth",
            "tokens": {
                "access_token": openai_token,
                "refresh_token": _get_openai_refresh_token() or "",
                "id_token": "",
            },
            "last_refresh": _now_iso(),
        }
        with open(os.path.join(_codex_tmp_home, "auth.json"), "w") as _af:
            json.dump(auth_json, _af)
        run_env["CODEX_HOME"] = _codex_tmp_home
    try:
        master_fd, slave_fd = pty.openpty()
        # stdin uses a regular pipe (separate from the PTY) so we can
        # write the prompt and send EOF cleanly. stdout/stderr keep the
        # PTY because Claude Code writes progress to ``/dev/tty`` and
        # would bypass a plain pipe entirely.
        proc = subprocess.Popen(
            cmd, cwd=str(cwd), env=run_env,
            stdin=subprocess.PIPE, stdout=slave_fd, stderr=slave_fd,
            close_fds=True,
        )
        os.close(slave_fd)
        # Feed the prompt and close stdin so the child sees EOF and
        # starts processing. A missing close() here would make claude
        # hang forever waiting for more input.
        if proc.stdin is not None:
            try:
                proc.stdin.write(prompt.encode("utf-8"))
            finally:
                proc.stdin.close()
        # Read output from master until process exits or timeout
        chunks: list[bytes] = []
        import time as _t
        deadline = _t.time() + task_timeout
        while True:
            if _t.time() > deadline:
                proc.kill()
                proc.wait()
                os.close(master_fd)
                return False, f"[timeout after {task_timeout}s]"
            ready, _, _ = select.select([master_fd], [], [], 1.0)
            if ready:
                try:
                    data = os.read(master_fd, 65536)
                    if not data:
                        break
                    chunks.append(data)
                except OSError:
                    break
            if proc.poll() is not None:
                # Process exited — drain remaining output
                while True:
                    ready, _, _ = select.select([master_fd], [], [], 0.1)
                    if not ready:
                        break
                    try:
                        data = os.read(master_fd, 65536)
                        if not data:
                            break
                        chunks.append(data)
                    except OSError:
                        break
                break
        os.close(master_fd)
        proc.wait()
        raw = b"".join(chunks).decode("utf-8", errors="replace")
        # Strip ANSI escape codes
        import re
        output = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\x1b\[[\?]?[0-9;]*[a-zA-Z]", "", raw).strip()
        if proc.returncode == 0:
            return True, output
        return False, f"[exit {proc.returncode}]\n{output}"
    except FileNotFoundError as e:
        return False, f"[command not found: {e}]"
    except Exception as e:
        return False, f"[error: {e}]"
    finally:
        # Clean up temporary Codex home dir
        if _codex_tmp_home:
            import shutil as _shutil
            try:
                _shutil.rmtree(_codex_tmp_home, ignore_errors=True)
            except Exception:
                pass


# ────────────────────────── main loop ──────────────────────────
_running = True


def _shutdown(signum, frame):
    global _running
    log.info("Received signal %d, shutting down...", signum)
    _running = False


def _claim_next_chat_task() -> Optional[sqlite3.Row]:
    """Fast-path: claim the oldest pending chat task."""
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM tasks WHERE status='pendiente' AND source='chat' "
            "ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        c.execute(
            "UPDATE tasks SET status='en_progreso', updated_at=? WHERE id=? AND status='pendiente'",
            (_now_iso(), row["id"]),
        )
        if c.execute("SELECT changes()").fetchone()[0] == 0:
            return None
        c.commit()
        return c.execute("SELECT * FROM tasks WHERE id=?", (row["id"],)).fetchone()


def _build_retry_prompt(task, project_dir, previous_error: str) -> str:
    """Build a prompt that includes the previous error for intelligent retry."""
    base = _build_prompt(task, project_dir)
    retry_section = (
        "\n\n⚠️ PREVIOUS ATTEMPT FAILED\n"
        f"Error from previous attempt:\n{previous_error[:2000]}\n\n"
        "Analyze what went wrong and try a different approach. "
        "If the error is unrecoverable (permissions, missing dependencies, etc.), "
        "use task_request_input to ask the human for help instead of failing again."
    )
    return base + retry_section


def _build_planner_prompt(task: sqlite3.Row, project_dir) -> str:
    """Build a prompt for the planner model to analyze and optionally split a task.

    The planner must reply with either ``EXECUTE_DIRECTLY`` (simple
    task) or a structured ``<SUBTASKS>[...]</SUBTASKS>`` JSON block
    that Niwa parses to create child tasks in the database. The
    previous prompt asked the model to create subtasks via the
    ``task_create`` MCP tool; switching to a structured output lets
    Niwa guarantee ``parent_task_id`` is set and gives us a testable
    parser (PR-B4a).
    """
    ctx = _load_project_context(task["project_id"], task["id"])
    memories = _load_memories(task["project_id"])

    parts = []

    # Project context (condensed)
    if ctx["project"]:
        p = ctx["project"]
        parts.append(f"PROJECT: {p.get('name', '')} [{p.get('area', '')}]")
        if p.get("description"):
            parts.append(f"DESCRIPTION: {p['description']}")
    if project_dir:
        parts.append(f"DIRECTORY: {project_dir}")

    # Current task
    parts.append("")
    parts.append(f"TASK TO ANALYZE: {task['title']}")
    if task["description"]:
        parts.append(f"DESCRIPTION: {task['description']}")
    if task["notes"]:
        parts.append(f"NOTES: {task['notes'][:300]}")

    # Related active tasks
    active = [t for t in ctx["tasks"] if t["status"] in ("pendiente", "en_progreso")]
    if active:
        parts.append("")
        parts.append("OTHER ACTIVE TASKS:")
        for t in active[:5]:
            parts.append(f"  - [{t['priority']}] {t['title']}")

    # Memories
    if memories:
        parts.append("")
        parts.append("RELEVANT MEMORIES:")
        for m in memories[:5]:
            parts.append(f"  {m['key']}: {m['value']}")

    # Planner instructions
    parts.append("")
    parts.append("=" * 60)
    parts.append("ROLE: You are the PLANNER. Analyze the task and decide execution strategy.")
    parts.append("")
    parts.append("Choose ONE of these two options and reply with nothing else:")
    parts.append("")
    parts.append("OPTION A — SIMPLE TASK (can be done in one step):")
    parts.append("  Reply with exactly: EXECUTE_DIRECTLY")
    parts.append("  Use for: single-file changes, questions, quick fixes.")
    parts.append("")
    parts.append("OPTION B — COMPLEX TASK (needs splitting into 2-5 subtasks):")
    parts.append("  Reply with a structured block:")
    parts.append("    <SUBTASKS>")
    parts.append('    [{"title": "short imperative title",')
    parts.append('      "description": "detailed instructions",')
    parts.append('      "priority": "baja|media|alta|critica"}, ...]')
    parts.append("    </SUBTASKS>")
    parts.append("  Rules:")
    parts.append("    - ``title`` is required; ``description`` recommended;")
    parts.append("      ``priority`` optional (defaults to media).")
    parts.append("    - Each subtask must be independently executable.")
    parts.append("    - Keep them ordered (first things first).")
    parts.append("")
    parts.append("IMPORTANT:")
    parts.append("- Do NOT implement anything yourself. Only plan.")
    parts.append("- Do NOT call ``task_create`` or any MCP tool; Niwa creates")
    parts.append("  the subtasks from the JSON block.")
    parts.append("- Output ONLY one of the two options above.")

    return "\n".join(parts)


# ────────────────────── PR-B4a planner split ─────────────────────────

def _should_run_planner(task) -> bool:
    """Return True when the planner tier should be invoked for ``task``.

    Triggers:
      - ``task.decompose == 1`` (explicit flag), OR
      - ``len(task.description) > PLANNER_DESCRIPTION_THRESHOLD``.
    """
    try:
        flag = int(task["decompose"] or 0)
    except (KeyError, IndexError, TypeError, ValueError):
        flag = 0
    if flag == 1:
        return True
    try:
        desc = task["description"]
    except (KeyError, IndexError):
        desc = None
    if desc and len(desc) > PLANNER_DESCRIPTION_THRESHOLD:
        return True
    return False


_VALID_PRIORITIES = frozenset({
    "baja", "media", "alta", "critica",
    "low", "medium", "high", "critical",
})


def _parse_planner_output(text: str) -> Optional[list[dict]]:
    """Extract a list of subtasks from the planner output.

    Looks for the first ``<SUBTASKS>...</SUBTASKS>`` block and expects
    its body to be a JSON array of objects with at least a non-empty
    ``title`` field. Returns ``None`` if no block is present, the JSON
    is invalid, the array is empty, or any item is missing ``title``.
    """
    if not text:
        return None
    start = text.find("<SUBTASKS>")
    end = text.find("</SUBTASKS>")
    if start < 0 or end <= start:
        return None
    block = text[start + len("<SUBTASKS>"):end].strip()
    try:
        parsed = json.loads(block)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    subs: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            return None
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            return None
        subs.append(item)
    return subs


def _create_subtasks(parent_task, subtasks: list[dict]) -> int:
    """Insert children in the ``tasks`` table and move parent to ``bloqueada``.

    Each child inherits ``project_id`` and gets ``parent_task_id`` =
    parent id. Priority is validated against the schema's CHECK
    whitelist; unknown values fall back to ``media``.
    """
    parent_id = parent_task["id"]
    project_id = parent_task["project_id"]
    now = _now_iso()
    with _conn() as c:
        for sub in subtasks:
            child_id = f"task-{uuid.uuid4().hex[:12]}"
            priority = (sub.get("priority") or "media").strip().lower()
            if priority not in _VALID_PRIORITIES:
                priority = "media"
            c.execute(
                "INSERT INTO tasks (id, title, description, area, "
                "project_id, status, priority, urgent, source, "
                "parent_task_id, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    child_id,
                    sub["title"].strip(),
                    (sub.get("description") or "").strip(),
                    "proyecto",
                    project_id,
                    "pendiente",
                    priority,
                    0,
                    "planner",
                    parent_id,
                    now,
                    now,
                ),
            )
        _assert_task_transition(parent_task["status"], "bloqueada")
        c.execute(
            "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
            ("bloqueada", now, parent_id),
        )
        c.commit()
    return len(subtasks)


def _try_planner_split(task) -> tuple[bool, str]:
    """Run the planner tier for ``task``.

    Returns ``(handled, result)``:
      - ``(True, "[planner] Split into N subtasks")`` when the planner
        produced a valid ``<SUBTASKS>`` block and Niwa persisted the
        children; the caller should treat the parent as done (blocked
        on children) and return ``result`` as its output.
      - ``(False, "")`` when the planner decided the task is simple
        (``EXECUTE_DIRECTLY``), the subprocess failed, or the output
        was unparseable. The caller must continue to the normal
        executor pipeline.
    """
    task_id = task["id"]
    project_dir = _resolve_project_dir(task["project_id"])
    cwd = project_dir or Path.home()

    log.info("task %s planning phase (tier-2 planner)", task_id)
    _record_event(task_id, "comment", {
        "author": "executor", "kind": "progress",
        "message": "Planning phase: analyzing task complexity...",
    })

    prompt = _build_planner_prompt(task, project_dir)
    success, output = _run_with_heartbeat(
        task_id, prompt, cwd, LLM_COMMAND_PLANNER, PLANNER_TIMEOUT,
    )

    if not success:
        log.warning(
            "task %s planner run failed, falling back to direct execution",
            task_id,
        )
        return False, ""

    subs = _parse_planner_output(output)
    if not subs:
        if "EXECUTE_DIRECTLY" in output:
            log.info(
                "task %s planner: EXECUTE_DIRECTLY, proceeding to executor",
                task_id,
            )
            _record_event(task_id, "comment", {
                "author": "executor", "kind": "progress",
                "message": "Planner: task is simple, executing directly.",
            })
        else:
            log.warning(
                "task %s planner output unparseable (len=%d); falling back",
                task_id, len(output or ""),
            )
        return False, ""

    try:
        count = _create_subtasks(task, subs)
    except (sqlite3.Error, ValueError) as e:
        log.error(
            "task %s could not persist planner subtasks: %s; falling back",
            task_id, e,
        )
        return False, ""

    log.info("task %s split into %d subtasks by planner", task_id, count)
    _record_event(task_id, "comment", {
        "author": "executor", "kind": "decision",
        "message": f"Planner split task into {count} subtasks.",
    })
    return True, f"[planner] Split into {count} subtasks"


def _run_with_heartbeat(task_id: str, prompt: str, cwd: Path, llm_cmd: str, timeout: int) -> tuple[bool, str]:
    """Run LLM with heartbeat thread. Returns (success, output)."""
    heartbeat = HeartbeatThread(task_id)
    heartbeat.start()
    try:
        return _run_llm(prompt, cwd, llm_command=llm_cmd, timeout=timeout)
    finally:
        heartbeat.stop()
        heartbeat.join(timeout=2)


# ────────────────────────── v0.2 routing (PR-06) ──────────────────────────

def _get_routing_mode() -> str:
    """Determine routing mode from settings.

    Returns ``"v02"`` for the new routing pipeline, ``"legacy"`` for the
    old 3-tier pipeline.

    Logic:
      - If ``routing_mode`` key exists in settings DB → use that value.
      - If key is absent (pre-v0.2 DB that never ran init_db v0.2) → "legacy".
      - Default for fresh installs (seeded by init_db) → "v02".
    """
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT value FROM settings WHERE key = 'routing_mode'"
            ).fetchone()
            if row:
                return row["value"]
    except Exception:
        pass
    return "legacy"


# ── Credential helpers for v0.2 adapters ──────────────────────────

def _mirror_claude_home(real_home: Path, tmp_home: Path) -> None:
    """Populate ``tmp_home`` so the Claude CLI finds everything it
    needs EXCEPT ``.credentials.json`` (PR final 5).

    Strategy: create ``tmp_home/.claude/`` and symlink each entry from
    ``real_home/.claude/`` into it, skipping the stale credentials.
    Also symlink ``real_home/.claude.json`` (user-scope MCP config)
    so ``claude mcp list`` sees the servers Niwa registered at
    install time.

    Preserved by the mirror:
      - ``projects/`` (session history for ``--resume``; new sessions
        written back to the real dir because symlink).
      - ``settings.json`` (user preferences).
      - ``mcp_servers.json`` and any other state files.
      - ``.claude.json`` sibling (MCP user-scope registrations).

    Hidden by the mirror:
      - ``.credentials.json``. Its absence makes the CLI fall back
        to ``CLAUDE_CODE_OAUTH_TOKEN`` env var cleanly.

    If ``real_home/.claude/`` doesn't exist (fresh install, no user
    config yet), we still create an empty ``tmp_home/.claude/`` so
    the CLI has a consistent layout.

    PR final 5 bis — first-run bootstrap: we also ensure
    ``real_home/.claude/projects/`` exists BEFORE the symlink loop.
    Without this, the first-ever Claude run through Niwa would write
    its session jsonl to ``tmp_home/.claude/projects/`` (a real dir,
    not a symlink, since nothing existed to mirror), and the file
    would evaporate on tmp cleanup — breaking ``--resume`` for that
    first task. The mkdir is idempotent: subsequent runs find it
    already there and the loop symlinks it like any other entry.
    """
    tmp_claude_dir = tmp_home / ".claude"
    tmp_claude_dir.mkdir(exist_ok=True)
    real_claude_dir = real_home / ".claude"
    # Ensure projects/ survives the first-ever run. parents=True also
    # covers the case where real_home/.claude itself didn't exist.
    try:
        (real_claude_dir / "projects").mkdir(parents=True, exist_ok=True)
    except OSError:
        log.warning(
            "claude-home mirror: could not bootstrap %s/projects",
            real_claude_dir,
        )
    if real_claude_dir.is_dir():
        for entry in real_claude_dir.iterdir():
            if entry.name == ".credentials.json":
                continue  # THE exclusion that makes this whole thing work
            link = tmp_claude_dir / entry.name
            try:
                link.symlink_to(entry)
            except OSError:
                # Best-effort: if symlink fails (perms, existing file),
                # log and continue — the cli just won't see that piece.
                log.warning(
                    "claude-home mirror: could not symlink %s → %s",
                    entry, link,
                )
    # ``~/.claude.json`` is a sibling file, not inside the .claude dir.
    real_claude_json = real_home / ".claude.json"
    if real_claude_json.is_file():
        try:
            (tmp_home / ".claude.json").symlink_to(real_claude_json)
        except OSError:
            log.warning(
                "claude-home mirror: could not symlink ~/.claude.json",
            )


def _prepare_backend_env(profile: dict) -> dict | None:
    """Build extra env vars for the subprocess of a v0.2 adapter.

    Returns a dict of env vars to merge, or None if nothing to add.
    For ``codex``: injects ``OPENAI_ACCESS_TOKEN`` and ``CODEX_HOME``.
    For ``claude_code``: injects ``ANTHROPIC_API_KEY`` and
    ``CLAUDE_CODE_OAUTH_TOKEN`` from executor globals.

    Additionally, for any v0.2 backend, injects the stored GitHub PAT
    as ``GITHUB_TOKEN`` + ``GH_TOKEN`` + ``GIT_ASKPASS`` (PR-50) so
    ``git clone``/``git push`` work transparently. No-op if the admin
    hasn't connected GitHub yet.

    Returns None if no credentials are available (caller decides
    whether that's fatal).
    """
    slug = profile.get("slug", "")
    extra: dict[str, str] = {}

    if slug == "codex":
        token = _get_openai_oauth_token()
        if not token:
            return None  # signal: no credentials available
        extra["OPENAI_ACCESS_TOKEN"] = token
        # Write temporary auth.json for Codex CLI compatibility
        import tempfile as _tmpfile
        codex_home = _tmpfile.mkdtemp(prefix="niwa-codex-v02-")
        auth_json = {
            "auth_mode": "chatgpt_oauth",
            "tokens": {
                "access_token": token,
                "refresh_token": _get_openai_refresh_token() or "",
                "id_token": "",
            },
            "last_refresh": _now_iso(),
        }
        with open(os.path.join(codex_home, "auth.json"), "w") as af:
            json.dump(auth_json, af)
        extra["CODEX_HOME"] = codex_home

    elif slug == "claude_code":
        if LLM_API_KEY:
            extra["ANTHROPIC_API_KEY"] = LLM_API_KEY
        if LLM_SETUP_TOKEN:
            extra["CLAUDE_CODE_OAUTH_TOKEN"] = LLM_SETUP_TOKEN
            # PR final 4 + PR final 5 — Bug 33 fix with surgical
            # isolation.
            #
            # The Claude CLI 2.1.97 prefers ``$HOME/.claude/
            # .credentials.json`` over the env var. If the host's
            # credentials.json is stale, the CLI exits 1 silently or
            # 401s even with a valid CLAUDE_CODE_OAUTH_TOKEN.
            #
            # PR final 4 pointed HOME at an empty tmp dir, which fixed
            # auth but BROKE two real contracts:
            #
            #   1. ``--resume`` — Claude persists sessions in
            #      ``$HOME/.claude/projects/<cwd>/<uuid>.jsonl``. An
            #      empty HOME = no previous sessions = resume dead.
            #   2. User-scope MCP + settings — Niwa registers its MCP
            #      servers via ``claude mcp add --scope user`` (lives
            #      in ``~/.claude.json``) plus ``settings.json`` in
            #      ``~/.claude/``. An empty HOME hides both, so tools
            #      like ``project_create`` disappear.
            #
            # PR final 5 fix: build a HOME tmp dir whose ``.claude/``
            # is a *symlink farm* mirroring the real user's
            # ``~/.claude/`` entry-by-entry, SKIPPING only
            # ``.credentials.json``. Also symlink the sibling
            # ``~/.claude.json`` (MCP user-scope config). The CLI
            # sees:
            #
            #   - projects/ → real (resume still works + new sessions
            #     written back to the real dir).
            #   - settings.json → real.
            #   - mcp_servers.json / other state → real.
            #   - .credentials.json → ABSENT (our trick). Falls back
            #     to the env var.
            #
            # We never touch the host's real ``.credentials.json``;
            # ``claude -p`` run by the operator standalone still sees
            # it unchanged.
            import tempfile as _tempfile
            claude_home = _tempfile.mkdtemp(prefix="niwa-claude-home-")
            _mirror_claude_home(Path.home(), Path(claude_home))
            extra["HOME"] = claude_home
        # Claude can also work with env vars already set in the
        # process, so empty extra is acceptable — return {} not None.

    # GitHub PAT injection (PR-50). Any v0.2 backend — claude_code or
    # codex — can benefit from ``git clone``/``git push`` with the admin's
    # stored PAT. If the admin hasn't connected GitHub, this is a no-op.
    try:
        import github_client as _gh_client
        pat = _gh_client.get_pat()
        if pat:
            extra["GITHUB_TOKEN"] = pat
            extra["GH_TOKEN"] = pat  # alias used by the `gh` CLI
            extra["GIT_TERMINAL_PROMPT"] = "0"
            askpass = _ensure_git_askpass_script()
            if askpass:
                extra["GIT_ASKPASS"] = askpass
    except Exception:
        # Never block task execution because of a GitHub integration
        # hiccup — the task may not even need git.
        log.warning("github PAT injection failed", exc_info=True)

    return extra if extra else {}


_GIT_ASKPASS_PATH = "/tmp/niwa-gh-askpass.sh"
_GIT_ASKPASS_BODY = """#!/bin/sh
# Niwa GitHub PAT ASKPASS helper — installed by task-executor.
# Reads the ``GITHUB_TOKEN`` env var (injected per-run by the executor)
# and answers Git's credential prompts without user interaction.
case "$1" in
  *[Uu]sername*) printf 'x-access-token' ;;
  *[Pp]assword*) printf '%s' "${GITHUB_TOKEN:-}" ;;
  *) printf '' ;;
esac
"""


def _ensure_git_askpass_script() -> str | None:
    """Ensure a tiny ASKPASS helper exists on disk and is executable.

    Returns the absolute path, or ``None`` if it couldn't be created.
    Idempotent and tolerant: if the file already has the expected body
    and mode, we just return its path. On any failure we return None so
    the caller treats it as "no helper available" rather than failing
    the whole task.
    """
    try:
        path = _GIT_ASKPASS_PATH
        needs_write = True
        try:
            with open(path, "r") as f:
                if f.read() == _GIT_ASKPASS_BODY:
                    needs_write = False
        except FileNotFoundError:
            pass
        if needs_write:
            with open(path, "w") as f:
                f.write(_GIT_ASKPASS_BODY)
        os.chmod(path, 0o700)
        return path
    except Exception:
        log.warning("could not create git askpass script", exc_info=True)
        return None


# ── Transient error codes eligible for fallback escalation ────────

_TRANSIENT_ERROR_CODES = frozenset({
    "auth_failed",
    "rate_limited",
    "timed_out",
    "adapter_exception",
    "subprocess_error",
})

# Bug 32 fix: sentinel que el adapter usa para señalizar al dispatcher
# que la tarea necesita clarificación (Claude solo habló, no ejecutó).
# Usamos un prefijo en el output en vez de cambiar la firma
# (bool, str) de toda la cadena _execute_task*. El dispatcher lo
# detecta en _handle_task_result y enruta a waiting_input.
_CLARIFICATION_SENTINEL = "__NIWA_CLARIFICATION__\n"


def _execute_task_v02(task: sqlite3.Row) -> tuple[bool, str]:
    """Execute a task through the v0.2 routing pipeline.

    1. Call routing_service.decide() to get routing decision.
    2. If approval required → leave task pending, return.
    3. Prepare backend-specific credentials.
    4. Execute primary backend via adapter.start().
    5. On raised exception OR returned failure with transient
       error_code → escalate once to the next backend in the
       fallback chain (``relation_type='fallback'``).
       Max 1 escalation per task (primary + 1 fallback).
       Non-transient failures (capability_denied, adapter_not_implemented)
       are NOT escalated.
    """
    try:
        import routing_service
        import runs_service
        from backend_registry import get_execution_registry
    except ImportError as e:
        log.error("v0.2 modules not available — cannot execute in v02 mode", exc_info=True)
        return False, f"[v02] missing module: {e}"

    task_dict = dict(task)
    task_id = task_dict["id"]

    # PR-38: auto-create a project directory for tasks without an
    # explicit project_id, so the adapter can set cwd there and so
    # files Claude writes show up under Proyectos in the UI. The
    # finalize in the ``finally`` block below either commits the
    # project row (files were written) or rmdirs the empty dir.
    auto_project_ctx = _auto_project_prepare(task_dict)

    # PR-41 / Bug 25: tmpdirs created by ``_prepare_backend_env`` for
    # the codex adapter (CODEX_HOME) must be cleaned up even if the
    # adapter crashes. Mutated by the body; read by the ``finally``.
    codex_tmpdirs: list[str] = []

    try:
        return _execute_task_v02_body(
            task_dict, task_id,
            routing_service, runs_service, get_execution_registry,
            codex_tmpdirs=codex_tmpdirs,
        )
    finally:
        for tmpdir in codex_tmpdirs:
            try:
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                log.exception(
                    "codex tmpdir cleanup failed for task %s: %s",
                    task_id, tmpdir,
                )
        if auto_project_ctx is not None:
            try:
                _auto_project_finalize(auto_project_ctx, task_id)
            except Exception:
                log.exception(
                    "auto-project finalize failed for task %s", task_id,
                )


def _build_retry_decision(
    task_id: str, retry_from_run_id: str, c: sqlite3.Connection,
) -> Optional[dict]:
    """Resolve a retry marker to a pseudo-decision dict (PR-57).

    Called before ``routing_service.decide()``. Reads the prior run
    and returns a dict matching the shape ``routing_service.decide``
    would produce, but with ``selected_backend_profile_id`` and
    ``routing_decision_id`` pinned to the prior run's values so the
    new ``backend_run`` ends up as a sibling retry instead of a
    reroute.

    Returns ``None`` if the prior run is missing or its
    ``backend_profile_id`` no longer exists (stale marker / GC'd
    data / admin manual edit). In that case the caller clears the
    marker and falls back to the normal routing path so the task
    never stays stuck.
    """
    prev = c.execute(
        "SELECT id, backend_profile_id, routing_decision_id "
        "FROM backend_runs WHERE id = ?",
        (retry_from_run_id,),
    ).fetchone()
    if not prev:
        return None
    # Sanity-check the backend still exists — the run could survive a
    # profile hard-delete and we'd crash later on FK.
    bp = c.execute(
        "SELECT id FROM backend_profiles WHERE id = ?",
        (prev["backend_profile_id"],),
    ).fetchone()
    if not bp:
        return None
    return {
        "routing_decision_id": prev["routing_decision_id"],
        "selected_backend_profile_id": prev["backend_profile_id"],
        "fallback_chain": [],  # retry is a single-attempt, not a reroute
        "reason_summary": f"retry of run {retry_from_run_id}",
        "relation_type_override": "retry",
        "previous_run_id_override": retry_from_run_id,
    }


def _execute_task_v02_body(
    task_dict: dict,
    task_id: str,
    routing_service,
    runs_service,
    get_execution_registry,
    *,
    codex_tmpdirs: list[str] | None = None,
) -> tuple[bool, str]:
    if codex_tmpdirs is None:
        codex_tmpdirs = []
    # Step 1: Route — unless this task is a retry (PR-57). When
    # ``retry_from_run_id`` is set, we bypass routing and reuse the
    # prior run's backend + routing decision so the new backend_run
    # becomes a ``relation_type='retry'`` sibling rather than a
    # rerouted attempt. Graceful degrade: if the marker points at a
    # prior run that no longer exists, clear it and fall back to the
    # normal routing path.
    retry_from = task_dict.get("retry_from_run_id")
    with _conn() as c:
        decision: Optional[dict] = None
        if retry_from:
            decision = _build_retry_decision(task_id, retry_from, c)
            if decision is None:
                log.warning(
                    "task %s: retry marker %s points to missing/stale data; "
                    "clearing marker and rerouting normally",
                    task_id, retry_from,
                )
            # Always clear the marker — either we consumed it
            # successfully into ``decision``, or we determined it's
            # corrupt and we want the task to proceed via routing.
            c.execute(
                "UPDATE tasks SET retry_from_run_id = NULL, updated_at = ? "
                "WHERE id = ?",
                (_now_iso(), task_id),
            )
            c.commit()
        if decision is None:
            decision = routing_service.decide(task_dict, c)

        if decision.get("approval_required"):
            log.info(
                "task %s: approval required (decision=%s, approval=%s). "
                "Transitioning to waiting_input.",
                task_id, decision["routing_decision_id"],
                decision.get("approval_id"),
            )
            # Bug 23 fix (PR-29): prior implementation UPDATEd status
            # to 'pendiente' here, which violates the task state
            # machine (en_progreso → pendiente is not allowed per
            # state_machines.TASK_TRANSITIONS). That caused a
            # processing loop: the executor would re-claim the
            # pendiente task on its next poll, the approval gate
            # would still be unresolved, status would flip back to
            # pendiente — forever, until the operator approved.
            #
            # The canonical state for "task needs human action
            # before proceeding" is ``waiting_input`` (SPEC-v0.2
            # §2). The operator's approval resolution transitions
            # the task back to pendiente so the executor picks it
            # up normally.
            current = c.execute(
                "SELECT status FROM tasks WHERE id = ?", (task_id,),
            ).fetchone()
            if current:
                _assert_task_transition(current["status"], "waiting_input")
            c.execute(
                "UPDATE tasks SET status = 'waiting_input', updated_at = ? "
                "WHERE id = ?",
                (_now_iso(), task_id),
            )
            c.commit()
            return True, f"[routing] Approval required: {decision['reason_summary']}"

        selected_profile_id = decision.get("selected_backend_profile_id")
        if not selected_profile_id:
            log.warning(
                "task %s: no backend selected by router", task_id,
            )
            return False, "[routing] No backend profile available"

    # Step 2: Build the execution chain (primary + up to 1 fallback)
    fallback_chain = decision.get("fallback_chain", [])
    if selected_profile_id not in fallback_chain:
        fallback_chain = [selected_profile_id] + fallback_chain
    execution_chain = fallback_chain[:2]

    import capability_service

    # PR-57: when the retry path synthesised the decision, the very
    # first run in the chain must be a ``relation_type='retry'`` with
    # ``previous_run_id`` pointing at the original. Subsequent entries
    # in the chain (if any fallback were used) still use 'fallback'.
    retry_previous_run_id = decision.get("previous_run_id_override")
    retry_relation_type = decision.get("relation_type_override")

    prior_run_id: str | None = retry_previous_run_id
    last_error = ""

    for chain_idx, profile_id in enumerate(execution_chain):
        if chain_idx == 0 and retry_relation_type:
            relation_type = retry_relation_type
        elif chain_idx > 0:
            relation_type = "fallback"
        else:
            relation_type = None

        with _conn() as c:
            profile = c.execute(
                "SELECT * FROM backend_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()
            if not profile:
                log.warning("task %s: profile %s not found, skipping",
                            task_id, profile_id)
                continue
            profile = dict(profile)

            project_dir = _resolve_project_dir(task_dict.get("project_id"))
            artifact_root = None
            if project_dir:
                artifact_root = str(
                    project_dir / ".niwa" / "runs"
                    / decision["routing_decision_id"]
                )

            run = runs_service.create_run(
                task_id=task_id,
                routing_decision_id=decision["routing_decision_id"],
                backend_profile_id=profile_id,
                conn=c,
                previous_run_id=prior_run_id,
                relation_type=relation_type,
                backend_kind=profile.get("backend_kind"),
                runtime_kind=profile.get("runtime_kind"),
                model_resolved=profile.get("default_model"),
                artifact_root=artifact_root,
            )

            c.execute(
                "UPDATE tasks SET current_run_id = ?, updated_at = ? "
                "WHERE id = ?",
                (run["id"], _now_iso(), task_id),
            )
            c.commit()

            log.info(
                "task %s: %s to %s (run=%s, decision=%s)",
                task_id,
                "fallback" if relation_type else "routed",
                profile["slug"], run["id"],
                decision["routing_decision_id"],
            )

        # Step 3: Prepare credentials for this backend
        extra_env = _prepare_backend_env(profile)
        # PR-41 / Bug 25: track the codex tmpdir for cleanup in the
        # wrapper's finally. _prepare_backend_env creates
        # /tmp/niwa-codex-v02-* on demand and the adapter only uses
        # it for the duration of one run. Leaking is slow accumulation
        # under /tmp on repeated codex tasks.
        if extra_env and "CODEX_HOME" in extra_env:
            codex_tmpdirs.append(extra_env["CODEX_HOME"])
        # PR final 4: same cleanup contract for the Claude isolated
        # HOME. The list is named ``codex_tmpdirs`` for historical
        # reasons (PR-41) but semantically holds "adapter tmp dirs
        # to rmtree on exit" — no need to rename the variable for
        # this addition.
        if (
            extra_env
            and profile["slug"] == "claude_code"
            and "HOME" in extra_env
            and Path(extra_env["HOME"]).name.startswith("niwa-claude-home-")
        ):
            codex_tmpdirs.append(extra_env["HOME"])
        if extra_env is None:
            # No credentials available — fail this run, do NOT escalate.
            # queued → failed directly (run never started).
            log.error(
                "task %s: no credentials for %s — blocking task",
                task_id, profile["slug"],
            )
            try:
                with _conn() as c:
                    runs_service.record_event(
                        run["id"], "credential_error", c,
                        message=(
                            f"No credentials available for "
                            f"{profile['slug']}."
                        ),
                    )
                    runs_service.finish_run(
                        run["id"], "failure", c,
                        error_code="codex_no_token",
                        exit_code=1,
                    )
            except Exception:
                log.exception(
                    "Failed to mark run %s as failed", run["id"])
            return False, (
                f"[{profile['slug']}] no OpenAI token available"
            )

        # Inject extra_env into profile for the adapter to pick up
        profile["_extra_env"] = extra_env

        # PR-34: --dangerously-skip-permissions is always on (the
        # niwa user is the OS-level sandbox). The _dangerous_mode
        # toggle from PR-33 is removed — scoped settings.json
        # proved unreliable in claude -p non-interactive mode.

        # Step 4: Execute via adapter
        try:
            registry = get_execution_registry(_conn)
            adapter = registry.resolve(profile["slug"])

            with _conn() as c:
                cap_profile = capability_service.get_effective_profile(
                    task_dict.get("project_id"), c,
                )

            result = adapter.start(task_dict, run, profile, cap_profile)

            # Check for transient failures eligible for fallback
            error_code = result.get("error_code", "")
            if error_code and error_code in _TRANSIENT_ERROR_CODES:
                log.warning(
                    "task %s: adapter %s returned transient failure "
                    "(error_code=%s) — escalating to fallback",
                    task_id, profile["slug"], error_code,
                )
                try:
                    with _conn() as c:
                        runs_service.record_event(
                            run["id"], "fallback_escalation", c,
                            message=(
                                f"Adapter {profile['slug']} returned "
                                f"transient failure: {error_code}. "
                                f"Escalating to next backend."
                            ),
                        )
                except Exception:
                    pass
                prior_run_id = run["id"]
                last_error = (
                    f"{profile['slug']} transient: {error_code}"
                )
                continue

            # PR-34: check adapter outcome. If the run failed
            # (permission denied, execution error, etc.) the TASK
            # must NOT be marked as hecha. Return False so the
            # caller leaves the task in a non-terminal state.
            adapter_status = result.get("status", "")
            if adapter_status == "failed":
                error_code = result.get("error_code", "unknown")
                log.warning(
                    "task %s: adapter %s returned failed "
                    "(error_code=%s)",
                    task_id, profile["slug"], error_code,
                )
                return False, (
                    f"[v02] Backend {profile['slug']} failed: "
                    f"error_code={error_code}. "
                    f"{str(result)[:300]}"
                )

            # Bug 32 fix: clarification — Claude salió exit 0 pero
            # solo habló (sin tool_use) en una tarea ejecutiva. La
            # tarea queda a la espera de input del usuario, NO se
            # marca como hecha ni se retryea. Signalizamos al caller
            # con el prefijo ``__NIWA_CLARIFICATION__`` en el output
            # para evitar cambiar la firma (bool, str) de todo el
            # pipeline — el top-level dispatcher lo detecta y
            # enruta a waiting_input.
            if adapter_status == "needs_clarification":
                log.info(
                    "task %s: adapter %s needs clarification — "
                    "no tool_use calls emitted, transitioning "
                    "task to waiting_input",
                    task_id, profile["slug"],
                )
                return True, (
                    _CLARIFICATION_SENTINEL
                    + (result.get("result_text", "") or "")
                )

            # PR-35: pass the human-readable result text as output
            # so _finish_task stores it in task_events and the UI
            # can show what Claude actually did. Before this, the
            # output was a technical dict repr — useless for the user.
            result_text = result.get("result_text", "")
            if result_text:
                return True, result_text
            return True, (
                f"[v02] Backend {profile['slug']} completed: "
                f"{str(result)[:500]}"
            )

        except Exception as e:
            log.warning(
                "task %s: adapter %s raised exception — "
                "escalating to fallback: %s",
                task_id, profile["slug"], e,
            )
            try:
                with _conn() as c:
                    runs_service.record_event(
                        run["id"], "fallback_escalation", c,
                        message=(
                            f"Adapter {profile['slug']} raised: {e}. "
                            f"Escalating to next backend."
                        ),
                    )
                    runs_service.finish_run(
                        run["id"], "failure", c,
                        error_code="adapter_exception",
                        exit_code=1,
                    )
            except Exception:
                log.exception(
                    "Failed to mark run %s as failed", run["id"])
            prior_run_id = run["id"]
            last_error = str(e)
            continue

    # All backends in the chain failed
    return False, f"[v02] All backends in fallback chain failed: {last_error}"


def _execute_task_legacy(task: sqlite3.Row, retry_prompt: str = "") -> tuple[bool, str]:
    """Legacy 3-tier pipeline (Haiku→Opus→Sonnet).

    Preserved for backward compatibility. Used when routing_mode='legacy'
    or when v0.2 modules are unavailable.
    """
    is_chat = dict(task).get("source") == "chat"
    project_dir = _resolve_project_dir(task["project_id"])
    if not project_dir and task["project_id"]:
        log.warning("Project dir not found for %s, using $HOME", task["project_id"])
    cwd = project_dir or Path.home()

    # Tier 1: Chat → Haiku (fast path)
    if is_chat and LLM_COMMAND_CHAT:
        if retry_prompt:
            prompt = retry_prompt
        else:
            prompt = _build_prompt(task, project_dir)
        log.info("chat task %s (tier-1 haiku)", task["id"])
        return _run_with_heartbeat(task["id"], prompt, cwd, LLM_COMMAND_CHAT, CHAT_TIMEOUT_SECONDS)

    # Tier 3: Executor → Sonnet (or default LLM_COMMAND)
    # The planner tier (tier 2) used to live here; PR-B4a moved it to
    # ``_execute_task`` so both legacy and v0.2 pipelines share the
    # same trigger (``_should_run_planner``) and DB-level persistence
    # of child tasks via ``_try_planner_split``.
    if retry_prompt:
        prompt = retry_prompt
    else:
        prompt = _build_prompt(task, project_dir)

    executor_cmd = LLM_COMMAND_EXECUTOR or LLM_COMMAND
    log.info("task %s executing (tier-3 executor)", task["id"])
    return _run_with_heartbeat(task["id"], prompt, cwd, executor_cmd, TIMEOUT_SECONDS)


def _execute_task(task: sqlite3.Row, retry_prompt: str = "") -> tuple[bool, str]:
    """Run a task through the appropriate pipeline.

    Dispatches to v0.2 routing pipeline or legacy 3-tier based on
    the ``routing_mode`` setting.

    Chat tasks always use the legacy path (fast Haiku response).
    Retry prompts always use the legacy path.
    """
    is_chat = dict(task).get("source") == "chat"

    # Chat tasks and retries always go through legacy pipeline
    if is_chat or retry_prompt:
        return _execute_task_legacy(task, retry_prompt=retry_prompt)

    # PR-B4a: planner tier. Runs before pipeline selection so both
    # v0.2 and legacy benefit. Triggered only when ``decompose=1`` is
    # set on the task or the description exceeds the threshold, and
    # only when a planner command is configured and OpenClaw is not
    # orchestrating.
    if (LLM_COMMAND_PLANNER and not WORKER_MODE
            and _should_run_planner(task)):
        handled, result = _try_planner_split(task)
        if handled:
            return True, result

    routing_mode = _get_routing_mode()
    if routing_mode == "v02":
        log.info("task %s: using v0.2 routing pipeline", task["id"])
        return _execute_task_v02(task)

    # Legacy mode (default for pre-v0.2 installs)
    return _execute_task_legacy(task, retry_prompt=retry_prompt)


def _handle_task_result(task_id: str, success: bool, output: str, was_retry: bool, task_row) -> tuple[bool, int]:
    """Process a completed task result. Returns (task_done, failure_delta)."""
    if success:
        # Bug 32 fix: si el adapter señalizó clarification (Claude salió
        # exit 0 pero solo habló en una tarea ejecutiva), transicionar
        # la task a waiting_input en vez de hecha. El texto tras el
        # sentinel es la respuesta exacta de Claude y se guarda como
        # output/comment para que el usuario vea qué se le preguntó.
        if output.startswith(_CLARIFICATION_SENTINEL):
            claude_text = output[len(_CLARIFICATION_SENTINEL):]
            _finish_task(task_id, "waiting_input", claude_text)
            _record_event(
                task_id, "comment",
                {
                    "author": "executor",
                    "kind": "warning",
                    "message": (
                        "Claude respondió sin ejecutar nada — "
                        "la tarea queda a la espera de que aclares "
                        "la especificación. Respuesta de Claude:\n\n"
                        f"{claude_text[:1500]}"
                    ),
                },
            )
            log.info(
                "task %s: waiting_input — needs clarification", task_id,
            )
            return True, 0  # neither success nor failure for counter
        _finish_task(task_id, "hecha", output)
        _record_event(task_id, "completed", {"executor": "niwa-executor"})
        log.info("task %s done", task_id)
        return True, -1  # success, reset failures
    else:
        is_chat = dict(task_row).get("source") == "chat"
        if not is_chat and not was_retry:
            log.warning("task %s failed, retrying with error context...", task_id)
            _record_event(task_id, "comment", {
                "author": "executor",
                "kind": "warning",
                "message": f"First attempt failed: {output[:500]}. Retrying..."
            })
            retry_prompt = _build_retry_prompt(task_row, _resolve_project_dir(task_row["project_id"]), output)
            success2, output2 = _execute_task(task_row, retry_prompt=retry_prompt)
            if success2:
                _finish_task(task_id, "hecha", output2)
                _record_event(task_id, "completed", {"executor": "niwa-executor", "retry": True})
                log.info("task %s done (after retry)", task_id)
                return True, -1
            output = f"[attempt 1]\n{output}\n\n[attempt 2]\n{output2}"

        _finish_task(task_id, "bloqueada", output)
        _record_event(
            task_id, "status_changed",
            {"to": "bloqueada", "reason": "executor failure"},
        )
        log.warning("task %s blocked: %s", task_id, output[:200])
        return False, 1  # failure, increment counter


def _reload_config():
    """Hot-reload configuration from settings.json and DB settings table."""
    global LLM_COMMAND, LLM_COMMAND_CHAT, LLM_COMMAND_PLANNER, LLM_COMMAND_EXECUTOR
    global LLM_API_KEY, LLM_SETUP_TOKEN, POLL_SECONDS, TIMEOUT_SECONDS
    global OPENCLAW_MODE, WORKER_MODE

    # Re-read settings.json
    global _SETTINGS
    if _SETTINGS_PATH.exists():
        try:
            _SETTINGS = json.loads(_SETTINGS_PATH.read_text())
        except Exception:
            pass

    # Also read from DB settings table (which is now the primary store)
    db_settings = {}
    try:
        with _conn() as c:
            for row in c.execute("SELECT key, value FROM settings").fetchall():
                db_settings[row["key"]] = row["value"]
    except Exception:
        pass

    # Merge: DB takes priority over settings.json
    merged = dict(_SETTINGS)
    merged.update(db_settings)

    def _cfg_reload(key, env_key, default=""):
        return (merged.get(f"int.{key}") or ENV.get(env_key, "") or default).strip()

    LLM_COMMAND = _cfg_reload("llm_command", "NIWA_LLM_COMMAND")
    LLM_COMMAND_CHAT = _cfg_reload("llm_command_chat", "NIWA_LLM_COMMAND_CHAT") or ""
    LLM_COMMAND_PLANNER = _cfg_reload("llm_command_planner", "NIWA_LLM_COMMAND_PLANNER") or ""
    LLM_COMMAND_EXECUTOR = _cfg_reload("llm_command_executor", "NIWA_LLM_COMMAND_EXECUTOR") or ""
    LLM_API_KEY = _cfg_reload("llm_api_key", "NIWA_LLM_API_KEY")
    # Read setup token from new service key OR legacy key
    LLM_SETUP_TOKEN = (merged.get("svc.llm.anthropic.setup_token") or _cfg_reload("llm_setup_token", "NIWA_LLM_SETUP_TOKEN"))
    POLL_SECONDS = int(_cfg_reload("executor_poll_seconds", "NIWA_EXECUTOR_POLL_SECONDS", "30"))
    TIMEOUT_SECONDS = int(_cfg_reload("executor_timeout_seconds", "NIWA_EXECUTOR_TIMEOUT_SECONDS", "1800"))

    # Reload OpenClaw worker mode
    OPENCLAW_MODE = merged.get('svc.openclaw.mode', 'disabled')
    WORKER_MODE = OPENCLAW_MODE in ('mcp_client', 'bidirectional')

    log.info("Configuration reloaded — LLM: %s, Chat: %s, Planner: %s, Executor: %s, Worker: %s",
             LLM_COMMAND or "(none)", LLM_COMMAND_CHAT or "(same)", LLM_COMMAND_PLANNER or "(none)",
             LLM_COMMAND_EXECUTOR or "(same)", WORKER_MODE)


def _check_reload_requested(start_time_iso: str) -> bool:
    """Check if a config reload has been requested via DB flag (atomic delete)."""
    try:
        with _conn() as c:
            deleted = c.execute(
                "DELETE FROM settings WHERE key='sys.executor_restart_requested' AND value > ?",
                (start_time_iso,)
            ).rowcount
            if deleted:
                c.commit()
                return True
    except Exception:
        pass
    return False


def main() -> None:
    start_time_iso = _now_iso()
    log.info(
        "Niwa executor starting (workers=%d, db=%s, poll=%ds, chat_poll=%ds)",
        MAX_WORKERS, DB_PATH, POLL_SECONDS, CHAT_POLL_SECONDS,
    )
    if not LLM_COMMAND:
        log.error(
            "NIWA_LLM_COMMAND not set in %s — executor will idle",
            INSTALL_DIR / "secrets" / "mcp.env",
        )
    log.info("LLM command (tasks):    %s", LLM_COMMAND or "(none)")
    log.info("LLM command (chat):     %s", LLM_COMMAND_CHAT or "(same as tasks)")
    log.info("LLM command (planner):  %s", LLM_COMMAND_PLANNER or "(not set)")
    log.info("LLM command (executor): %s", LLM_COMMAND_EXECUTOR or "(same as tasks)")
    log.info("Models: chat=%s, planner=%s, executor=%s",
        LLM_COMMAND_CHAT.split("--model ")[-1].split(" ")[0] if "--model" in (LLM_COMMAND_CHAT or "") else "default",
        LLM_COMMAND_PLANNER.split("--model ")[-1].split(" ")[0] if "--model" in (LLM_COMMAND_PLANNER or "") else "none",
        LLM_COMMAND_EXECUTOR.split("--model ")[-1].split(" ")[0] if "--model" in (LLM_COMMAND_EXECUTOR or "") else "default",
    )
    if PUBLIC_URL:
        log.info("Public URL: %s", PUBLIC_URL)
    if WORKER_MODE:
        log.info("Worker mode: OpenClaw is the orchestrator. Executor only runs explicitly assigned tasks.")

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    consecutive_failures = 0
    last_poll = 0.0

    executor_pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    active_futures: dict[str, Future] = {}  # task_id -> future
    active_tasks: dict[str, object] = {}    # task_id -> task row (for result handling)

    while _running:
        try:
            # Clean completed futures
            done_ids = [tid for tid, f in active_futures.items() if f.done()]
            for tid in done_ids:
                try:
                    success, output = active_futures.pop(tid).result()
                    task_row = active_tasks.pop(tid, None)
                    if task_row is not None:
                        done, delta = _handle_task_result(tid, success, output, False, task_row)
                        if delta == -1:
                            consecutive_failures = 0
                        elif delta == 1:
                            consecutive_failures += 1
                            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                                log.error(
                                    "Pausing: %d consecutive failures. Sleeping %ds.",
                                    consecutive_failures, POLL_SECONDS * 10,
                                )
                                time.sleep(POLL_SECONDS * 10)
                                consecutive_failures = 0
                except Exception as e:
                    log.exception("task %s raised: %s", tid, e)
                    active_tasks.pop(tid, None)

            # Check for config reload request
            if _check_reload_requested(start_time_iso):
                _reload_config()
                start_time_iso = _now_iso()

            # Don't spawn new tasks if at capacity
            if len(active_futures) >= MAX_WORKERS:
                time.sleep(CHAT_POLL_SECONDS)
                continue

            # Try to claim a task (chat first, then regular or openclaw)
            task = _claim_next_chat_task()
            if not task:
                now = time.time()
                if now - last_poll >= POLL_SECONDS:
                    if WORKER_MODE:
                        task = _claim_next_openclaw_task()
                    else:
                        task = _claim_next_task()
                    last_poll = now

            if task:
                task_id = task["id"]
                log.info("task %s: %s [source=%s]", task_id, task["title"], dict(task).get("source", "manual"))
                future = executor_pool.submit(_execute_task, task)
                active_futures[task_id] = future
                active_tasks[task_id] = task
            else:
                time.sleep(CHAT_POLL_SECONDS)

        except KeyboardInterrupt:
            break
        except Exception as e:
            log.exception("executor loop error: %s", e)
            time.sleep(CHAT_POLL_SECONDS)

    executor_pool.shutdown(wait=True)


if __name__ == "__main__":
    main()
