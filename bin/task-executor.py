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

import json
import logging
import os
import shlex
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


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
if _SETTINGS_PATH.exists():
    try:
        _SETTINGS = json.loads(_SETTINGS_PATH.read_text())
    except Exception:
        pass


def _cfg(key: str, env_key: str, default: str = "") -> str:
    return (_SETTINGS.get(f"int.{key}") or ENV.get(env_key, "") or default).strip()


DB_PATH = ENV.get("NIWA_DB_PATH") or str(INSTALL_DIR / "data" / "niwa.sqlite3")
LLM_COMMAND = _cfg("llm_command", "NIWA_LLM_COMMAND")
LLM_API_KEY = _cfg("llm_api_key", "NIWA_LLM_API_KEY")
LLM_SETUP_TOKEN = _cfg("llm_setup_token", "NIWA_LLM_SETUP_TOKEN")
POLL_SECONDS = int(_cfg("executor_poll_seconds", "NIWA_EXECUTOR_POLL_SECONDS", "30"))
TIMEOUT_SECONDS = int(_cfg("executor_timeout_seconds", "NIWA_EXECUTOR_TIMEOUT_SECONDS", "1800"))
MAX_OUTPUT_CHARS = int(ENV.get("NIWA_EXECUTOR_MAX_OUTPUT", "10000"))
HEARTBEAT_SECONDS = int(ENV.get("NIWA_EXECUTOR_HEARTBEAT_SECONDS", "60"))
MAX_CONSECUTIVE_FAILURES = int(ENV.get("NIWA_EXECUTOR_MAX_FAILURES", "3"))

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

    # Instructions
    parts.append("")
    parts.append("INSTRUCTIONS:")
    parts.append("1. Read any files relevant to understanding the task.")
    parts.append("2. Make the changes required.")
    parts.append("3. Verify your work (run tests/build/lint as appropriate).")
    parts.append("4. Reply with a brief summary of what you did.")
    parts.append("5. If the task is too large or unclear, explain why and stop.")
    parts.append("")
    parts.append("You have access to the Niwa MCP tools (tasks, notes, platform).")
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
        row = c.execute("SELECT completed_at FROM tasks WHERE id=?", (task_id,)).fetchone()
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
_active_proc: Optional[subprocess.Popen] = None


def _run_llm(prompt: str, cwd: Path) -> tuple[bool, str]:
    """Run LLM command with PTY so Claude Code output is captured.

    Claude Code writes to /dev/tty, bypassing stdout/stderr when piped.
    Using pty.openpty() gives it a real terminal to write to, and we
    read the master side to capture the output.
    """
    global _active_proc
    if not LLM_COMMAND:
        return False, "NIWA_LLM_COMMAND is not configured"
    import pty, select
    # Write prompt to temp file — Claude Code interprets long positional
    # args as file paths, causing ENAMETOOLONG with enriched prompts.
    import tempfile
    prompt_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", prefix="niwa-prompt-", delete=False,
    )
    prompt_file.write(prompt)
    prompt_file.close()
    cmd = shlex.split(LLM_COMMAND) + [prompt_file.name]
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
    try:
        master_fd, slave_fd = pty.openpty()
        proc = subprocess.Popen(
            cmd, cwd=str(cwd), env=run_env,
            stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            close_fds=True,
        )
        os.close(slave_fd)
        _active_proc = proc
        # Read output from master until process exits or timeout
        chunks: list[bytes] = []
        import time as _t
        deadline = _t.time() + TIMEOUT_SECONDS
        while True:
            if _t.time() > deadline:
                proc.kill()
                proc.wait()
                os.close(master_fd)
                return False, f"[timeout after {TIMEOUT_SECONDS}s]"
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
        try:
            os.unlink(prompt_file.name)
        except Exception:
            pass


# ────────────────────────── main loop ──────────────────────────
_running = True


def _shutdown(signum, frame):
    global _running
    log.info("Received signal %d, shutting down...", signum)
    _running = False
    if _active_proc and _active_proc.poll() is None:
        log.info("Terminating active subprocess (pid %d)...", _active_proc.pid)
        _active_proc.terminate()


def main() -> None:
    global _active_proc
    log.info(
        "Niwa executor starting (db=%s, poll=%ds, timeout=%ds)",
        DB_PATH, POLL_SECONDS, TIMEOUT_SECONDS,
    )
    if not LLM_COMMAND:
        log.error(
            "NIWA_LLM_COMMAND not set in %s — executor will idle",
            INSTALL_DIR / "secrets" / "mcp.env",
        )
    log.info("LLM command: %s", LLM_COMMAND or "(none)")

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    consecutive_failures = 0

    while _running:
        try:
            task = _claim_next_task()
            if task is None:
                time.sleep(POLL_SECONDS)
                continue
            log.info("task %s: %s", task["id"], task["title"])
            project_dir = _resolve_project_dir(task["project_id"])
            if not project_dir and task["project_id"]:
                log.warning("Project dir not found for %s, using $HOME", task["project_id"])
            cwd = project_dir or Path.home()
            prompt = _build_prompt(task, project_dir)
            log.debug("prompt: %d chars", len(prompt))
            heartbeat = HeartbeatThread(task["id"])
            heartbeat.start()
            try:
                success, output = _run_llm(prompt, cwd)
            finally:
                _active_proc = None
                heartbeat.stop()
                heartbeat.join(timeout=2)
            if success:
                _finish_task(task["id"], "hecha", output)
                _record_event(task["id"], "completed", {"executor": "niwa-executor"})
                log.info("task %s done", task["id"])
                consecutive_failures = 0
            else:
                _finish_task(task["id"], "bloqueada", output)
                _record_event(
                    task["id"], "status_changed",
                    {"to": "bloqueada", "reason": "executor failure"},
                )
                log.warning("task %s blocked: %s", task["id"], output[:200])
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    log.error(
                        "Pausing: %d consecutive failures. Sleeping %ds.",
                        consecutive_failures, POLL_SECONDS * 10,
                    )
                    time.sleep(POLL_SECONDS * 10)
                    consecutive_failures = 0
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.exception("executor loop error: %s", e)
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
