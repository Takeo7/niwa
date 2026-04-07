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


# ────────────────────────── logging ──────────────────────────
LOG_PATH = INSTALL_DIR / "logs" / "executor.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_PATH)),
    ],
)
log = logging.getLogger("niwa-executor")


# ────────────────────────── DB helpers ──────────────────────────
def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _claim_next_task() -> Optional[sqlite3.Row]:
    """Atomically pick the oldest pending task and mark it in_progress."""
    with _conn() as c:
        # Pending + assigned to a worker (yume or claude). If neither, the task
        # is for Arturo to do manually — we don't pick it.
        row = c.execute(
            """
            SELECT * FROM tasks
            WHERE status = 'pendiente'
              AND (assigned_to_yume = 1 OR assigned_to_claude = 1)
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        c.execute(
            "UPDATE tasks SET status = 'en_progreso', updated_at = ? WHERE id = ? AND status = 'pendiente'",
            (_now_iso(), row["id"]),
        )
        if c.total_changes == 0:
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
    if not LLM_COMMAND:
        return False, "NIWA_LLM_COMMAND is not configured"
    cmd = shlex.split(LLM_COMMAND) + [prompt]
    log.info("→ exec in %s: %s ...", cwd, " ".join(shlex.quote(c) for c in cmd[:6]))
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        if result.returncode == 0:
            return True, output
        return False, f"[exit {result.returncode}]\n{output}"
    except subprocess.TimeoutExpired:
        return False, f"[timeout after {TIMEOUT_SECONDS}s]"
    except FileNotFoundError as e:
        return False, f"[command not found: {e}]"
    except Exception as e:
        return False, f"[error: {e}]"


# ────────────────────────── main loop ──────────────────────────
_running = True


def _shutdown(signum, frame):
    global _running
    log.info("Received signal %d, shutting down...", signum)
    _running = False


def main() -> None:
    log.info("Niwa executor starting (db=%s, poll=%ds, timeout=%ds)",
             DB_PATH, POLL_SECONDS, TIMEOUT_SECONDS)
    if not LLM_COMMAND:
        log.error("NIWA_LLM_COMMAND not set in %s — executor will idle", INSTALL_DIR / "secrets" / "mcp.env")
    log.info("LLM command: %s", LLM_COMMAND or "(none)")

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while _running:
        try:
            task = _claim_next_task()
            if task is None:
                time.sleep(POLL_SECONDS)
                continue
            log.info("→ task %s: %s", task["id"], task["title"])
            project_dir = _resolve_project_dir(task["project_id"])
            cwd = project_dir or Path.home()
            prompt = _build_prompt(task, project_dir)
            success, output = _run_llm(prompt, cwd)
            if success:
                _finish_task(task["id"], "hecha", output)
                _record_event(task["id"], "completed", {"executor": "niwa-executor"})
                log.info("✓ task %s done", task["id"])
            else:
                _finish_task(task["id"], "bloqueada", output)
                _record_event(task["id"], "status_changed", {"to": "bloqueada", "reason": "executor failure"})
                log.warning("✗ task %s blocked: %s", task["id"], output[:200])
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.exception("executor loop error: %s", e)
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
