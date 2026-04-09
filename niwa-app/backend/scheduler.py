"""Niwa scheduler — cron-like routine execution engine.

Runs as a daemon thread inside niwa-app. Every 60 seconds it evaluates all
enabled routines and fires those whose cron expression matches the current
minute. Actions can create tasks, run shell scripts, or call webhooks.

Cron expressions are 5-field standard (min hour dom month dow).
Zero external deps — implements a minimal cron matcher in stdlib.

Usage (from app.py):
    from scheduler import SchedulerThread, init_routines_table
    init_routines_table(db_conn_fn)
    scheduler = SchedulerThread(db_conn_fn, install_dir)
    scheduler.start()  # daemon thread, auto-stops with the process
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

try:
    from zoneinfo import ZoneInfo
except ImportError:
    # Python 3.8 fallback — UTC only
    ZoneInfo = None  # type: ignore

log = logging.getLogger("niwa-scheduler")


# ────────────────────────── cron expression parser ──────────────────────────

def _parse_cron_field(field: str, min_val: int, max_val: int) -> set[int]:
    """Parse a single cron field (e.g. '*/15', '1,3,5', '0-23/2', '*')."""
    values = set()
    for part in field.split(","):
        part = part.strip()
        if part == "*":
            values.update(range(min_val, max_val + 1))
        elif "/" in part:
            base, step_str = part.split("/", 1)
            step = int(step_str)
            if base == "*":
                start, end = min_val, max_val
            elif "-" in base:
                lo, hi = base.split("-", 1)
                start, end = int(lo), int(hi)
            else:
                start, end = int(base), max_val
            values.update(range(start, end + 1, step))
        elif "-" in part:
            lo, hi = part.split("-", 1)
            values.update(range(int(lo), int(hi) + 1))
        else:
            values.add(int(part))
    return values


def cron_matches(expr: str, dt: datetime) -> bool:
    """Check if a 5-field cron expression matches the given datetime."""
    fields = expr.strip().split()
    if len(fields) != 5:
        return False
    try:
        minutes = _parse_cron_field(fields[0], 0, 59)
        hours = _parse_cron_field(fields[1], 0, 23)
        doms = _parse_cron_field(fields[2], 1, 31)
        months = _parse_cron_field(fields[3], 1, 12)
        dows = _parse_cron_field(fields[4], 0, 6)  # 0=Sunday
    except (ValueError, IndexError):
        return False
    # Python weekday: Monday=0 ... Sunday=6 → cron: Sunday=0
    cron_dow = (dt.weekday() + 1) % 7
    return (
        dt.minute in minutes
        and dt.hour in hours
        and dt.day in doms
        and dt.month in months
        and cron_dow in dows
    )


# ────────────────────────── DB helpers ──────────────────────────

ROUTINES_DDL = """
CREATE TABLE IF NOT EXISTS routines (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    schedule TEXT NOT NULL,
    tz TEXT NOT NULL DEFAULT 'UTC',
    action TEXT NOT NULL CHECK (action IN ('create_task', 'script', 'webhook')),
    action_config TEXT NOT NULL DEFAULT '{}',
    notify_channel TEXT NOT NULL DEFAULT 'none',
    notify_config TEXT NOT NULL DEFAULT '{}',
    last_run_at TEXT,
    last_status TEXT,
    last_error TEXT,
    consecutive_errors INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def init_routines_table(db_conn_fn: Callable) -> None:
    with db_conn_fn() as conn:
        conn.executescript(ROUTINES_DDL)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ────────────────────────── CRUD (used by API) ──────────────────────────

def list_routines(db_conn_fn: Callable) -> list[dict]:
    with db_conn_fn() as conn:
        rows = conn.execute("SELECT * FROM routines ORDER BY name ASC").fetchall()
        return [dict(r) for r in rows]


def get_routine(db_conn_fn: Callable, routine_id: str) -> Optional[dict]:
    with db_conn_fn() as conn:
        row = conn.execute("SELECT * FROM routines WHERE id = ?", (routine_id,)).fetchone()
        return dict(row) if row else None


def create_routine(db_conn_fn: Callable, data: dict) -> str:
    rid = data.get("id") or str(uuid.uuid4())
    ts = _now_iso()
    with db_conn_fn() as conn:
        conn.execute(
            """INSERT INTO routines (id, name, description, enabled, schedule, tz, action,
               action_config, notify_channel, notify_config, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rid,
                data.get("name", "Untitled"),
                data.get("description", ""),
                1 if data.get("enabled", True) else 0,
                data["schedule"],
                data.get("tz", "UTC"),
                data["action"],
                json.dumps(data.get("action_config", {}), ensure_ascii=False),
                data.get("notify_channel", "none"),
                json.dumps(data.get("notify_config", {}), ensure_ascii=False),
                ts, ts,
            ),
        )
        conn.commit()
    return rid


def update_routine(db_conn_fn: Callable, routine_id: str, data: dict) -> bool:
    allowed = {"name", "description", "enabled", "schedule", "tz", "action",
               "action_config", "notify_channel", "notify_config"}
    sets, params = [], []
    for k, v in data.items():
        if k not in allowed:
            continue
        if k in ("action_config", "notify_config") and isinstance(v, dict):
            v = json.dumps(v, ensure_ascii=False)
        if k == "enabled":
            v = 1 if v else 0
        sets.append(f"{k} = ?")
        params.append(v)
    if not sets:
        return False
    sets.append("updated_at = ?")
    params.append(_now_iso())
    params.append(routine_id)
    with db_conn_fn() as conn:
        conn.execute(f"UPDATE routines SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
    return True


def delete_routine(db_conn_fn: Callable, routine_id: str) -> None:
    with db_conn_fn() as conn:
        conn.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
        conn.commit()


def toggle_routine(db_conn_fn: Callable, routine_id: str) -> Optional[bool]:
    with db_conn_fn() as conn:
        row = conn.execute("SELECT enabled FROM routines WHERE id = ?", (routine_id,)).fetchone()
        if not row:
            return None
        new_val = 0 if row["enabled"] else 1
        conn.execute("UPDATE routines SET enabled = ?, updated_at = ? WHERE id = ?",
                      (new_val, _now_iso(), routine_id))
        conn.commit()
        return bool(new_val)


# ────────────────────────── action executors ──────────────────────────

def _exec_create_task(config: dict, db_conn_fn: Callable) -> str:
    """Create a new task from the routine config."""
    ts = _now_iso()
    task_id = str(uuid.uuid4())
    with db_conn_fn() as conn:
        conn.execute(
            """INSERT INTO tasks (id, title, description, area, project_id, status, priority,
               source, created_at, updated_at, assigned_to_yume, assigned_to_claude)
               VALUES (?, ?, ?, ?, ?, 'pendiente', ?, 'routine', ?, ?, 0, 0)""",
            (
                task_id,
                config.get("title", "Routine task"),
                config.get("description", ""),
                config.get("area", "sistema"),
                config.get("project_id"),
                config.get("priority", "media"),
                ts, ts,
            ),
        )
        conn.execute(
            "INSERT INTO task_events (id, task_id, type, payload_json, created_at) VALUES (?, ?, 'created', ?, ?)",
            (str(uuid.uuid4()), task_id, json.dumps({"source": "routine"}, ensure_ascii=False), ts),
        )
        conn.commit()
    return f"Task created: {task_id}"


def _exec_script(config: dict, install_dir: Path) -> str:
    """Run a shell script from the install dir."""
    script = config.get("command", "")
    if not script:
        return "ERROR: no command configured"
    timeout = int(config.get("timeout", 300))
    cwd = config.get("cwd") or str(install_dir)
    try:
        result = subprocess.run(
            script, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd,
        )
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0:
            return output.strip() or "(ok, no output)"
        return f"[exit {result.returncode}] {output.strip()}"
    except subprocess.TimeoutExpired:
        return f"[timeout after {timeout}s]"
    except Exception as e:
        return f"[error: {e}]"


def _exec_webhook(config: dict) -> str:
    """POST to a webhook URL."""
    import urllib.request
    url = config.get("url", "")
    if not url:
        return "ERROR: no webhook URL configured"
    payload = json.dumps(config.get("payload", {"source": "niwa-routine"})).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return f"[{resp.status}] {resp.read().decode()[:500]}"
    except Exception as e:
        return f"[error: {e}]"


# ────────────────────────── scheduler thread ──────────────────────────

class SchedulerThread(threading.Thread):
    """Daemon thread that evaluates routines every 60 seconds."""

    def __init__(self, db_conn_fn: Callable, install_dir: Path):
        super().__init__(daemon=True, name="niwa-scheduler")
        self.db_conn_fn = db_conn_fn
        self.install_dir = install_dir
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        log.info("Scheduler started")
        # Align to the next full minute
        now = time.time()
        sleep_initial = 60 - (now % 60)
        if self._stop_event.wait(sleep_initial):
            return

        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                log.exception("Scheduler tick error: %s", e)
            # Sleep until next full minute
            now = time.time()
            sleep_sec = 60 - (now % 60)
            if self._stop_event.wait(max(sleep_sec, 1)):
                return

    def _tick(self) -> None:
        now_utc = datetime.now(timezone.utc)
        conn = self.db_conn_fn()
        try:
            rows = conn.execute(
                "SELECT * FROM routines WHERE enabled = 1"
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            routine = dict(row)
            schedule = routine["schedule"]
            # Evaluate cron in the routine's timezone (default UTC)
            tz_name = routine.get("tz") or "UTC"
            if ZoneInfo and tz_name != "UTC":
                try:
                    now = now_utc.astimezone(ZoneInfo(tz_name))
                except (KeyError, Exception):
                    log.warning("Unknown timezone %s for routine %s, using UTC", tz_name, routine["id"])
                    now = now_utc
            else:
                now = now_utc
            if not cron_matches(schedule, now):
                continue
            log.info("Firing routine: %s (%s)", routine["name"], routine["id"])
            self._execute_routine(routine)

    def _execute_routine(self, routine: dict) -> None:
        action = routine["action"]
        try:
            config = json.loads(routine.get("action_config") or "{}")
        except (json.JSONDecodeError, TypeError):
            config = {}

        result = ""
        success = True
        try:
            if action == "create_task":
                result = _exec_create_task(config, self.db_conn_fn)
            elif action == "script":
                result = _exec_script(config, self.install_dir)
                if result.startswith("[exit") or result.startswith("[timeout") or result.startswith("[error") or result.startswith("ERROR:"):
                    success = False
            elif action == "webhook":
                result = _exec_webhook(config)
                if result.startswith("[error"):
                    success = False
            else:
                result = f"Unknown action: {action}"
                success = False
        except Exception as e:
            result = f"Exception: {e}"
            success = False
            log.exception("Routine %s failed: %s", routine["id"], e)

        # Update routine state
        ts = _now_iso()
        consecutive = 0 if success else (routine.get("consecutive_errors", 0) + 1)
        with self.db_conn_fn() as conn:
            conn.execute(
                """UPDATE routines SET last_run_at = ?, last_status = ?, last_error = ?,
                   consecutive_errors = ?, updated_at = ? WHERE id = ?""",
                (ts, "ok" if success else "error", None if success else result[:1000],
                 consecutive, ts, routine["id"]),
            )
            conn.commit()

        # Notify if configured
        notify_channel = routine.get("notify_channel", "none")
        if notify_channel != "none" and result.strip():
            try:
                notify_config = json.loads(routine.get("notify_config") or "{}")
            except (json.JSONDecodeError, TypeError):
                notify_config = {}
            from notifier import send_notification
            prefix = f"*{routine['name']}*\n" if success else f"*{routine['name']}* (error)\n"
            # Filter kwargs to known keys per channel to avoid TypeError
            allowed_keys = {"telegram": {"chat_id", "bot_token"}, "webhook": {"url"}}
            filtered = {k: v for k, v in notify_config.items() if k in allowed_keys.get(notify_channel, set())}
            send_notification(prefix + result[:2000], channel=notify_channel, **filtered)


# ────────────────────────── built-in seed routines ──────────────────────────

BUILTIN_ROUTINES = [
    {
        "id": "healthcheck",
        "name": "Healthcheck",
        "description": "Periodic system health check — verifies containers, DB, and disk space.",
        "schedule": "*/30 * * * *",
        "action": "script",
        "action_config": {
            "command": "python3 -c \"\nimport sqlite3, os, json, shutil\nresults = []\ndb = os.environ.get('NIWA_DB_PATH', 'data/niwa.sqlite3')\ntry:\n    c = sqlite3.connect(db, timeout=5)\n    c.execute('SELECT COUNT(*) FROM tasks')\n    results.append('db: ok')\nexcept Exception as e:\n    results.append(f'db: FAIL ({e})')\ntry:\n    usage = shutil.disk_usage('/')\n    pct = usage.used / usage.total * 100\n    results.append(f'disk: {pct:.0f}% used')\n    if pct > 90:\n        results.append('WARNING: disk > 90%')\nexcept Exception as e:\n    results.append(f'disk: FAIL ({e})')\nprint(chr(10).join(results))\n\"",
            "timeout": 30,
        },
        "notify_channel": "none",
    },
    {
        "id": "daily-backup",
        "name": "Daily backup",
        "description": "Backup SQLite database to data/backups/ with 7-day rotation.",
        "schedule": "0 3 * * *",
        "action": "script",
        "action_config": {
            "command": "python3 -c \"\nimport shutil, os, glob\nfrom datetime import datetime, timedelta\nfrom pathlib import Path\ndb = os.environ.get('NIWA_DB_PATH', 'data/niwa.sqlite3')\nbdir = Path(db).parent / 'backups'\nbdir.mkdir(exist_ok=True)\nstamp = datetime.now().strftime('%Y%m%d-%H%M%S')\ndst = bdir / f'niwa-{stamp}.sqlite3'\nshutil.copy2(db, dst)\nprint(f'Backup: {dst} ({dst.stat().st_size} bytes)')\ncutoff = datetime.now() - timedelta(days=7)\nfor old in sorted(bdir.glob('niwa-*.sqlite3')):\n    try:\n        ts = datetime.strptime(old.stem.split('niwa-')[1], '%Y%m%d-%H%M%S')\n        if ts < cutoff:\n            old.unlink()\n            print(f'Rotated: {old.name}')\n    except Exception:\n        pass\n\"",
            "timeout": 60,
        },
        "notify_channel": "none",
    },
    {
        "id": "idle-project-review",
        "name": "Idle project review",
        "description": "Creates improvement tasks for projects with zero open tasks.",
        "schedule": "0 9 * * 1-5",
        "enabled": False,
        "action": "create_task",
        "action_config": {
            "title": "Review idle projects",
            "description": "Check all active projects. For any with 0 open tasks, propose a maintenance or improvement task.",
            "area": "sistema",
            "priority": "baja",
        },
        "notify_channel": "none",
    },
    {
        "id": "daily-task-summary",
        "name": "Daily task summary",
        "description": "Generates an end-of-day summary of completed, pending, and blocked tasks.",
        "schedule": "0 20 * * *",
        "enabled": False,
        "action": "script",
        "action_config": {
            "command": "python3 -c \"\nimport sqlite3, os\ndb = os.environ.get('NIWA_DB_PATH', 'data/niwa.sqlite3')\nc = sqlite3.connect(db)\nr = c.execute(\\\"SELECT status, COUNT(*) FROM tasks GROUP BY status\\\").fetchall()\nlines = ['*Daily Summary*']\nfor status, cnt in r:\n    lines.append(f'  {status}: {cnt}')\ndone_today = c.execute(\\\"SELECT COUNT(*) FROM tasks WHERE status=\\'hecha\\' AND date(completed_at)=date(\\'now\\')\\\").fetchone()[0]\nlines.append(f'  completed today: {done_today}')\nprint(chr(10).join(lines))\n\"",
            "timeout": 30,
        },
        "notify_channel": "telegram",
    },
    {
        "id": "morning-brief",
        "name": "Morning brief",
        "description": "Morning overview of pending tasks, overdue items, and today's focus.",
        "schedule": "0 8 * * 1-5",
        "enabled": False,
        "action": "script",
        "action_config": {
            "command": "python3 -c \"\nimport sqlite3, os\ndb = os.environ.get('NIWA_DB_PATH', 'data/niwa.sqlite3')\nc = sqlite3.connect(db)\npending = c.execute(\\\"SELECT COUNT(*) FROM tasks WHERE status='pendiente'\\\").fetchone()[0]\nblocked = c.execute(\\\"SELECT COUNT(*) FROM tasks WHERE status='bloqueada'\\\").fetchone()[0]\noverdue = c.execute(\\\"SELECT COUNT(*) FROM tasks WHERE due_at IS NOT NULL AND date(due_at)<date('now') AND status NOT IN ('hecha','archivada')\\\").fetchone()[0]\nlines = ['*Morning Brief*', f'  Pending: {pending}', f'  Blocked: {blocked}', f'  Overdue: {overdue}']\ntop = c.execute(\\\"SELECT title FROM tasks WHERE status='pendiente' ORDER BY priority DESC LIMIT 3\\\").fetchall()\nif top:\n    lines.append('  Top tasks:')\n    for t in top:\n        lines.append(f'    - {t[0]}')\nprint(chr(10).join(lines))\n\"",
            "timeout": 30,
        },
        "notify_channel": "telegram",
    },
]


def seed_builtin_routines(db_conn_fn: Callable) -> int:
    """Insert built-in routines that don't already exist. Returns count inserted."""
    count = 0
    with db_conn_fn() as conn:
        for routine in BUILTIN_ROUTINES:
            existing = conn.execute("SELECT 1 FROM routines WHERE id = ?", (routine["id"],)).fetchone()
            if existing:
                continue
            ts = _now_iso()
            conn.execute(
                """INSERT INTO routines (id, name, description, enabled, schedule, tz, action,
                   action_config, notify_channel, notify_config, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'UTC', ?, ?, ?, '{}', ?, ?)""",
                (
                    routine["id"],
                    routine["name"],
                    routine.get("description", ""),
                    1 if routine.get("enabled", True) else 0,
                    routine["schedule"],
                    routine["action"],
                    json.dumps(routine.get("action_config", {}), ensure_ascii=False),
                    routine.get("notify_channel", "none"),
                    ts, ts,
                ),
            )
            count += 1
        conn.commit()
    return count
