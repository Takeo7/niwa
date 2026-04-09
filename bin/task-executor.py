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
DB_PATH = ENV.get("NIWA_DB_PATH") or str(INSTALL_DIR / "data" / "niwa.sqlite3")
LLM_COMMAND = ENV.get("NIWA_LLM_COMMAND", "").strip()
POLL_SECONDS = int(ENV.get("NIWA_EXECUTOR_POLL_SECONDS", "30"))
TIMEOUT_SECONDS = int(ENV.get("NIWA_EXECUTOR_TIMEOUT_SECONDS", "1800"))
MAX_OUTPUT_CHARS = int(ENV.get("NIWA_EXECUTOR_MAX_OUTPUT", "10000"))
HEARTBEAT_SECONDS = int(ENV.get("NIWA_EXECUTOR_HEARTBEAT_SECONDS", "60"))


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
MAX_CONSECUTIVE_FAILURES = int(ENV.get("NIWA_EXECUTOR_MAX_FAILURES", "3"))


# ────────────────────────── DB helpers ──────────────────────────
def _conn() -> sqlite3.Connection:
    """Open a sqlite connection with WAL + busy_timeout. WAL allows concurrent
    readers/writers (the heartbeat thread + the main loop + the web app), and
    busy_timeout=10s makes the rare contention non-fatal."""
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    # WAL is persistent — set once and the file stays in WAL mode across opens.
    # Set it on every connection anyway (it's idempotent and free) so a fresh
    # install or a DB recreated by the web app also gets it.
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=10000")
    except sqlite3.OperationalError:
        pass
    return c


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _claim_next_task() -> Optional[sqlite3.Row]:
    """Atomically pick the oldest pending task and mark it in_progress.

    Picks any task with status='pendiente'. If you want to mark some tasks as
    "do not auto-execute" (e.g. tasks for the human to do manually), set their
    status to 'inbox' instead and only move to 'pendiente' when you want the
    executor to take them.
    """
    with _conn() as c:
        row = c.execute(
            """
            SELECT * FROM tasks
            WHERE status = 'pendiente'
            ORDER BY CASE priority
              WHEN 'critica' THEN 4 WHEN 'critical' THEN 4
              WHEN 'alta' THEN 3 WHEN 'high' THEN 3
              WHEN 'media' THEN 2 WHEN 'medium' THEN 2
              WHEN 'baja' THEN 1 WHEN 'low' THEN 1
              ELSE 0 END DESC, created_at ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        c.execute(
            "UPDATE tasks SET status = 'en_progreso', updated_at = ? WHERE id = ? AND status = 'pendiente'",
            (_now_iso(), row["id"]),
        )
        changed = c.execute("SELECT changes()").fetchone()[0]
        if changed == 0:
            # Someone else got it first
            return None
        c.commit()
        # Re-fetch with updated status
        return c.execute("SELECT * FROM tasks WHERE id = ?", (row["id"],)).fetchone()


def _resolve_project_dir(project_id: Optional[str]) -> Optional[Path]:
    if not project_id:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT directory FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row and row["directory"]:
            p = Path(row["directory"]).expanduser()
            if p.is_dir():
                return p
    return None


class HeartbeatThread(threading.Thread):
    """Daemon thread that bumps tasks.updated_at every HEARTBEAT_SECONDS while
    a task is executing. Without this, long-running LLM calls or deploys can
    leave the row stale for 20+ minutes — making the web UI think the task is
    frozen and any future watchdog reset it as 'stuck'.

    Uses its own sqlite connection (WAL mode permits this safely)."""

    def __init__(self, task_id: str):
        super().__init__(daemon=True)
        self.task_id = task_id
        # NOTE: don't name this `_stop` — Thread has an internal `_stop` method
        # used by join(). Naming our Event `_stop` shadows it and breaks join.
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.wait(HEARTBEAT_SECONDS):
            try:
                with _conn() as c:
                    c.execute(
                        "UPDATE tasks SET updated_at = ? WHERE id = ? AND status = 'en_progreso'",
                        (_now_iso(), self.task_id),
                    )
                    c.commit()
            except Exception as e:
                # Don't crash the worker if a heartbeat fails — just log and keep going.
                log.warning("heartbeat failed for %s: %s", self.task_id, e)


def _record_event(task_id: str, event_type: str, payload: dict) -> None:
    import json
    with _conn() as c:
        c.execute(
            "INSERT INTO task_events (id, task_id, type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), task_id, event_type, json.dumps(payload, ensure_ascii=False), _now_iso()),
        )
        c.commit()


def _finish_task(task_id: str, status: str, output: str) -> None:
    with _conn() as c:
        row = c.execute("SELECT notes, completed_at FROM tasks WHERE id = ?", (task_id,)).fetchone()
        prev_notes = (row["notes"] if row else "") or ""
        suffix = "\n\n--- executor output ---\n" + output[:MAX_OUTPUT_CHARS]
        if len(output) > MAX_OUTPUT_CHARS:
            suffix += "\n[truncated]"
        new_notes = (prev_notes + suffix)[: MAX_OUTPUT_CHARS * 2]
        now = _now_iso()
        completed_at = now if status == "hecha" else (row["completed_at"] if row else None)
        c.execute(
            "UPDATE tasks SET status = ?, notes = ?, updated_at = ?, completed_at = ? WHERE id = ?",
            (status, new_notes, now, completed_at, task_id),
        )
        c.commit()


# ────────────────────────── prompt + execution ──────────────────────────
def _build_prompt(task: sqlite3.Row, project_dir: Optional[Path]) -> str:
    parts = [f"TASK: {task['title']}"]
    if task["description"]:
        parts.append(f"\nDESCRIPTION:\n{task['description']}")
    if task["notes"]:
        parts.append(f"\nNOTES:\n{task['notes']}")
    parts.append(f"\nAREA: {task['area']}")
    parts.append(f"PRIORITY: {task['priority']}")
    if project_dir:
        parts.append(f"\nWORKING DIRECTORY: {project_dir}")
    parts.append(
        "\nINSTRUCTIONS:\n"
        "1. Read any files relevant to understanding the task.\n"
        "2. Make the changes required.\n"
        "3. Verify your work (run tests/build/lint as appropriate).\n"
        "4. Reply with a brief summary of what you did.\n"
        "5. If the task is too large or unclear, explain why and stop."
    )
    return "\n".join(parts)


def _run_llm(prompt: str, cwd: Path) -> tuple[bool, str]:
    """Run the configured LLM command with the prompt as the LAST argument.
    Returns (success, combined_output)."""
    global _active_proc
    if not LLM_COMMAND:
        return False, "NIWA_LLM_COMMAND is not configured"
    cmd = shlex.split(LLM_COMMAND) + [prompt]
    log.info("→ exec in %s: %s ...", cwd, " ".join(shlex.quote(c) for c in cmd[:6]))
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(cwd),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        _active_proc = proc
        try:
            stdout, stderr = proc.communicate(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return False, f"[timeout after {TIMEOUT_SECONDS}s]"
        output = (stdout or "") + ("\n" + stderr if stderr else "")
        if proc.returncode == 0:
            return True, output
        return False, f"[exit {proc.returncode}]\n{output}"
    except FileNotFoundError as e:
        return False, f"[command not found: {e}]"
    except Exception as e:
        return False, f"[error: {e}]"


# ────────────────────────── main loop ──────────────────────────
_running = True
_active_proc: Optional[subprocess.Popen] = None


def _shutdown(signum, frame):
    global _running
    log.info("Received signal %d, shutting down...", signum)
    _running = False
    # Kill active LLM subprocess so we don't wait up to TIMEOUT_SECONDS
    if _active_proc and _active_proc.poll() is None:
        log.info("Terminating active subprocess (pid %d)...", _active_proc.pid)
        _active_proc.terminate()


def main() -> None:
    global _active_proc
    log.info("Niwa executor starting (db=%s, poll=%ds, timeout=%ds)",
             DB_PATH, POLL_SECONDS, TIMEOUT_SECONDS)
    if not LLM_COMMAND:
        log.error("NIWA_LLM_COMMAND not set in %s — executor will idle", INSTALL_DIR / "secrets" / "mcp.env")
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
            log.info("→ task %s: %s", task["id"], task["title"])
            project_dir = _resolve_project_dir(task["project_id"])
            if not project_dir and task["project_id"]:
                log.warning("Project dir not found for %s, using $HOME", task["project_id"])
            cwd = project_dir or Path.home()
            prompt = _build_prompt(task, project_dir)
            # Heartbeat keeps updated_at fresh while the LLM runs (could be 20+ min).
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
                log.info("✓ task %s done", task["id"])
                consecutive_failures = 0
            else:
                _finish_task(task["id"], "bloqueada", output)
                _record_event(task["id"], "status_changed", {"to": "bloqueada", "reason": "executor failure"})
                log.warning("✗ task %s blocked: %s", task["id"], output[:200])
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    log.error("Pausing: %d consecutive failures — LLM command may be broken. Sleeping %ds.",
                              consecutive_failures, POLL_SECONDS * 10)
                    time.sleep(POLL_SECONDS * 10)
                    consecutive_failures = 0
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.exception("executor loop error: %s", e)
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
