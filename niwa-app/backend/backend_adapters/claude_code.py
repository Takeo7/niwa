"""Claude Code backend adapter — PR-04 Niwa v0.2.

Real implementation of the Claude Code CLI backend.  Uses
``claude -p --output-format stream-json`` for execution and
``--resume <session_id>`` for resume.

Streaming events from the CLI are written to ``backend_run_events``
in real time.  Session handles, usage signals, and artifacts are
persisted at the appropriate lifecycle points.

Resource-budget fields (``estimated_resource_cost``, ``cost_confidence``,
``quota_risk``, ``latency_tier``) default to unknowns here.  PR-06 will
populate them with deterministic routing logic.
"""

import hashlib
import json
import logging
import os
import shlex
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backend_adapters.base import BackendAdapter

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────

# Heartbeat interval in seconds.  The adapter updates
# backend_runs.heartbeat_at at this cadence while the Claude
# process is alive.
HEARTBEAT_INTERVAL_SECONDS = 5

# Grace period after SIGTERM before escalating to SIGKILL.
CANCEL_SIGTERM_WAIT_SECONDS = 5

# Default CLI binary name.  Can be overridden via command_template
# in the backend_profile.
CLAUDE_CLI_COMMAND = "claude"

# ── Usage signals schema (PR-04 minimal) ──────────────────────────
# Fields: input_tokens, output_tokens, cache_read_tokens,
#         cache_creation_tokens, model, cost_usd, duration_ms, turns.
# If the CLI doesn't expose a field, it stays None — never fabricated.
USAGE_SIGNAL_FIELDS = (
    "input_tokens", "output_tokens", "cache_read_tokens",
    "cache_creation_tokens", "model", "cost_usd", "duration_ms", "turns",
)


# ── Approval gate stub (TODO PR-05) ──────────────────────────────

def check_approval_gate(task: dict, run: dict, profile: dict,
                        capability_profile: dict) -> bool:
    """Check whether execution is approved.

    TODO PR-05: Replace with real capability_profiles + approvals
    system.  PR-05 will implement risk-based approval gating based
    on ``project_capability_profiles`` and ``approval_service``.

    Currently always returns True (execution permitted).
    """
    return True


# ── Helpers ────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class ClaudeCodeAdapter(BackendAdapter):
    """Adapter for the Claude Code CLI backend.

    Constructor accepts an optional ``db_conn_factory`` callable that
    returns a ``sqlite3.Connection``.  When provided, the adapter
    writes streaming events, heartbeats, and usage signals to the
    database in real time.  When ``None`` (e.g., in unit tests that
    only call ``capabilities()``), no DB interaction occurs.
    """

    def __init__(self, *, db_conn_factory: Callable | None = None):
        self._db_conn_factory = db_conn_factory
        # Active subprocesses keyed by run_id — used by cancel/heartbeat.
        self._processes: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    # ── Interface implementation ───────────────────────────────────

    def capabilities(self) -> dict[str, Any]:
        return {
            "resume_modes": ["session_restore", "context_summary"],
            "fs_modes": ["full", "repo_only", "readonly"],
            "shell_modes": ["unrestricted", "restricted", "off"],
            "network_modes": ["full", "restricted", "off"],
            "approval_modes": ["always", "risk_based", "never"],
            "secrets_modes": ["env_inject", "file_mount", "none"],
            # Resource-budget defaults — PR-06 fills with real logic.
            "estimated_resource_cost": None,
            "cost_confidence": "unknown",
            "quota_risk": "unknown",
            "latency_tier": "unknown",
        }

    def _require_db(self) -> None:
        """Raise if the adapter was created without a DB connection factory."""
        if self._db_conn_factory is None:
            raise RuntimeError(
                "ClaudeCodeAdapter requires db_conn_factory for execution. "
                "Use backend_registry.register_adapter() with a factory."
            )

    def start(self, task: dict, run: dict, profile: dict,
              capability_profile: dict) -> dict:
        """Start a new Claude Code execution for *task*."""
        self._require_db()
        if not check_approval_gate(task, run, profile, capability_profile):
            return {"status": "rejected", "reason": "approval_denied"}

        artifact_root = run.get("artifact_root")
        if artifact_root:
            Path(artifact_root).mkdir(parents=True, exist_ok=True)

        prompt = self._build_prompt(task)
        model = profile.get("default_model") or "claude-sonnet-4-6"
        cmd = self._build_command(model=model, profile=profile)
        cwd = self._resolve_cwd(task, artifact_root)

        return self._execute(
            cmd=cmd, cwd=cwd, run=run, task=task,
            prompt_text=prompt, artifact_root=artifact_root,
        )

    def resume(self, task: dict, prior_run: dict, new_run: dict,
               profile: dict, capability_profile: dict) -> dict:
        """Resume execution from *prior_run*'s Claude session."""
        self._require_db()
        if not check_approval_gate(task, new_run, profile, capability_profile):
            return {"status": "rejected", "reason": "approval_denied"}

        session_id = prior_run.get("session_handle")
        if not session_id:
            return {
                "status": "failed", "outcome": "failure",
                "error_code": "no_session_handle",
                "reason": "Prior run has no session_handle to resume from.",
            }

        artifact_root = new_run.get("artifact_root")
        if artifact_root:
            Path(artifact_root).mkdir(parents=True, exist_ok=True)

        prompt = self._build_prompt(task)
        model = profile.get("default_model") or "claude-sonnet-4-6"
        cmd = self._build_command(
            model=model, resume_session_id=session_id, profile=profile,
        )
        cwd = self._resolve_cwd(task, artifact_root)

        return self._execute(
            cmd=cmd, cwd=cwd, run=new_run, task=task,
            prompt_text=prompt, artifact_root=artifact_root,
        )

    def cancel(self, run: dict) -> dict:
        """Cancel a running execution.  Idempotent.

        Sends SIGTERM, waits ``CANCEL_SIGTERM_WAIT_SECONDS``, then
        SIGKILL if the process hasn't exited.
        """
        run_id = run["id"]

        with self._lock:
            proc = self._processes.get(run_id)

        if proc is None:
            logger.info("cancel: no active process for run %s", run_id)
            return {"status": "cancelled", "outcome": "cancelled"}

        # SIGTERM first
        try:
            proc.terminate()
            logger.info("cancel: SIGTERM run %s pid %d", run_id, proc.pid)
        except OSError:
            pass

        # Wait for graceful shutdown
        try:
            proc.wait(timeout=CANCEL_SIGTERM_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            # Escalate to SIGKILL
            try:
                proc.kill()
                proc.wait(timeout=5)
                logger.warning("cancel: SIGKILL run %s pid %d", run_id, proc.pid)
            except OSError:
                pass

        with self._lock:
            self._processes.pop(run_id, None)

        # Record cancellation in DB
        if self._db_conn_factory:
            import runs_service
            conn = self._db_conn_factory()
            try:
                runs_service.record_event(
                    run_id, "cancelled", conn,
                    message="Execution cancelled by user request.",
                )
                # Only finish if not already in a terminal state
                current = conn.execute(
                    "SELECT status FROM backend_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
                if current and current["status"] not in (
                    "succeeded", "failed", "cancelled", "timed_out", "rejected",
                ):
                    runs_service.finish_run(
                        run_id, "cancelled", conn, exit_code=-15,
                    )
            finally:
                conn.close()

        return {"status": "cancelled", "outcome": "cancelled"}

    def heartbeat(self, run: dict) -> dict:
        """Check liveness and update ``heartbeat_at``."""
        run_id = run["id"]

        with self._lock:
            proc = self._processes.get(run_id)

        if proc is None:
            return {"alive": False, "details": "No active process tracked."}

        alive = proc.poll() is None

        if alive and self._db_conn_factory:
            import runs_service
            conn = self._db_conn_factory()
            try:
                runs_service.record_heartbeat(run_id, conn)
            finally:
                conn.close()

        return {
            "alive": alive,
            "details": f"pid={proc.pid}" if alive else "process exited",
        }

    def collect_artifacts(self, run: dict) -> list[dict]:
        """Scan ``artifact_root`` and register files in ``artifacts`` table."""
        artifact_root = run.get("artifact_root")
        if not artifact_root or not Path(artifact_root).is_dir():
            return []

        artifacts: list[dict] = []
        root = Path(artifact_root)

        for fpath in sorted(root.rglob("*")):
            if not fpath.is_file():
                continue
            stat = fpath.stat()
            sha = hashlib.sha256(fpath.read_bytes()).hexdigest()
            rel = str(fpath.relative_to(root))
            atype = self._classify_artifact_type(fpath.suffix.lower())

            artifact = {
                "artifact_type": atype,
                "path": rel,
                "size_bytes": stat.st_size,
                "sha256": sha,
            }
            artifacts.append(artifact)

            if self._db_conn_factory:
                import runs_service
                conn = self._db_conn_factory()
                try:
                    runs_service.register_artifact(
                        task_id=run["task_id"], run_id=run["id"],
                        artifact_type=atype, path=rel, conn=conn,
                        size_bytes=stat.st_size, sha256=sha,
                    )
                finally:
                    conn.close()

        return artifacts

    def parse_usage_signals(self, raw_output: str) -> dict:
        """Extract usage signals from accumulated stream-json output.

        Scans all JSON lines for ``result`` type messages to extract
        token counts, cost, and model info.  Returns a dict matching
        the ``USAGE_SIGNAL_FIELDS`` schema.
        """
        signals: dict[str, Any] = {f: None for f in USAGE_SIGNAL_FIELDS}
        turns = 0

        for line in raw_output.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            msg_type = msg.get("type", "")

            # Count assistant messages as conversational turns
            if msg_type == "assistant":
                turns += 1

            # Extract usage data from the final result message
            if msg_type == "result":
                signals["cost_usd"] = msg.get("cost_usd")
                signals["duration_ms"] = msg.get("duration_ms")
                signals["model"] = msg.get("model")
                usage = msg.get("usage") or {}
                if usage:
                    signals["input_tokens"] = usage.get("input_tokens")
                    signals["output_tokens"] = usage.get("output_tokens")
                    signals["cache_read_tokens"] = usage.get(
                        "cache_read_input_tokens",
                    )
                    signals["cache_creation_tokens"] = usage.get(
                        "cache_creation_input_tokens",
                    )

        signals["turns"] = turns if turns > 0 else None
        return signals

    # ── Private helpers ────────────────────────────────────────────

    @staticmethod
    def _build_prompt(task: dict) -> str:
        """Assemble prompt text from task data."""
        parts: list[str] = []
        title = task.get("title", "")
        if title:
            parts.append(f"# Task: {title}")
        desc = task.get("description", "")
        if desc:
            parts.append(desc)
        notes = task.get("notes", "")
        if notes:
            parts.append(f"\n## Notes\n{notes}")
        return "\n\n".join(parts) if parts else "Complete the assigned task."

    @staticmethod
    def _build_command(*, model: str,
                       resume_session_id: str | None = None,
                       profile: dict | None = None) -> list[str]:
        """Build the ``claude`` CLI command list.

        Never includes ``--dangerously-skip-permissions``.  That flag
        is deferred to PR-05 behind capability_profile + approval gate.
        """
        cli_parts = [CLAUDE_CLI_COMMAND]
        if profile and profile.get("command_template"):
            cli_parts = shlex.split(profile["command_template"])

        cmd = cli_parts + ["-p", "--output-format", "stream-json"]
        if model:
            cmd.extend(["--model", model])
        if resume_session_id:
            cmd.extend(["--resume", resume_session_id])
        return cmd

    @staticmethod
    def _resolve_cwd(task: dict, artifact_root: str | None) -> str:
        """Determine the working directory for the subprocess."""
        project_dir = task.get("project_directory")
        if project_dir and Path(project_dir).is_dir():
            return project_dir
        if artifact_root and Path(artifact_root).is_dir():
            return artifact_root
        return os.getcwd()

    @staticmethod
    def _classify_artifact_type(suffix: str) -> str:
        """Map a file extension to an artifact_type string."""
        _CODE = {
            '.py', '.js', '.ts', '.tsx', '.jsx', '.sh', '.rb', '.go',
            '.rs', '.java', '.c', '.cpp', '.h', '.css', '.sql',
        }
        _DOC = {'.md', '.txt', '.rst', '.html'}
        _DATA = {'.json', '.yaml', '.yml', '.toml', '.xml', '.csv'}
        _IMG = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp'}

        if suffix in _CODE:
            return "code"
        if suffix in _DOC:
            return "document"
        if suffix in _DATA:
            return "data"
        if suffix == '.log':
            return "log"
        if suffix in _IMG:
            return "image"
        return "file"

    @staticmethod
    def _classify_event(msg: dict) -> tuple[str | None, str | None, dict | None]:
        """Map a stream-json message to ``(event_type, message, payload)``."""
        msg_type = msg.get("type", "")

        if msg_type == "system":
            subtype = msg.get("subtype", "")
            return (
                f"system_{subtype}" if subtype else "system",
                msg.get("message", "System event"),
                msg,
            )

        if msg_type == "assistant":
            content_parts: list[str] = []
            message_data = msg.get("message") or {}
            for block in message_data.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    content_parts.append(block.get("text", ""))
            text = "\n".join(content_parts)
            return (
                "assistant_message",
                text[:2000] if text else "Assistant response",
                {"content": message_data.get("content")}
                if message_data.get("content") else None,
            )

        if msg_type == "tool_use":
            name = msg.get("name", msg.get("tool", "unknown"))
            return (
                "tool_use",
                f"Tool call: {name}",
                {"tool_name": name, "input": msg.get("input")},
            )

        if msg_type == "tool_result":
            return (
                "tool_result",
                str(msg.get("content", ""))[:2000],
                {"content": msg.get("content")}
                if msg.get("content") else None,
            )

        if msg_type == "result":
            return (
                "result",
                f"Execution completed (cost={msg.get('cost_usd', '?')})",
                msg,
            )

        if msg_type == "error":
            err = msg.get("error") or {}
            return (
                "error",
                err.get("message", str(msg))
                if isinstance(err, dict)
                else str(err),
                msg,
            )

        # Unknown type — still record it
        if msg_type:
            return (msg_type, json.dumps(msg)[:2000], msg)

        return (None, None, None)

    def _heartbeat_worker(self, run_id: str, proc: subprocess.Popen,
                          stop_event: threading.Event) -> None:
        """Daemon thread: update heartbeat_at every HEARTBEAT_INTERVAL_SECONDS.

        Runs independently of stdout activity.  Stops when *stop_event*
        is set or when the process exits (``proc.poll() is not None``).
        Exceptions are logged but never propagate.
        """
        import runs_service

        while not stop_event.wait(timeout=HEARTBEAT_INTERVAL_SECONDS):
            if proc.poll() is not None:
                break
            try:
                hb_conn = self._db_conn_factory()
                try:
                    runs_service.record_heartbeat(run_id, hb_conn)
                finally:
                    hb_conn.close()
            except Exception:
                logger.debug("heartbeat_worker: failed for run %s", run_id,
                             exc_info=True)

    def _execute(self, *, cmd: list[str], cwd: str, run: dict,
                 task: dict, prompt_text: str,
                 artifact_root: str | None) -> dict:
        """Core execution loop: spawn process, stream events, finish run.

        This method blocks until the Claude process exits.  The caller
        (PR-06 task-executor) is expected to call it from a worker thread.

        A daemon heartbeat thread runs independently, updating
        ``heartbeat_at`` every ``HEARTBEAT_INTERVAL_SECONDS`` regardless
        of stdout activity.
        """
        import runs_service

        run_id = run["id"]
        conn = self._db_conn_factory() if self._db_conn_factory else None
        heartbeat_stop = threading.Event()
        heartbeat_thread: threading.Thread | None = None

        try:
            # queued → starting
            if conn:
                runs_service.transition_run(run_id, "starting", conn)

            # Spawn the CLI process
            env = os.environ.copy()
            env["NO_COLOR"] = "1"

            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            with self._lock:
                self._processes[run_id] = proc

            # Send prompt via stdin and close
            if proc.stdin:
                try:
                    proc.stdin.write(prompt_text.encode("utf-8"))
                    proc.stdin.close()
                except BrokenPipeError:
                    pass

            # starting → running
            if conn:
                runs_service.transition_run(
                    run_id, "running", conn,
                    started_at=_now_iso(),
                )

            # Start heartbeat daemon thread
            heartbeat_thread = threading.Thread(
                target=self._heartbeat_worker,
                args=(run_id, proc, heartbeat_stop),
                daemon=True,
                name=f"heartbeat-{run_id[:8]}",
            )
            heartbeat_thread.start()

            # Stream stdout line by line
            session_handle = None
            raw_lines: list[str] = []

            for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                raw_lines.append(line)

                # Parse JSON
                try:
                    msg = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    if conn:
                        runs_service.record_event(
                            run_id, "raw_output", conn,
                            message=line[:2000],
                        )
                    continue

                # Classify and record event
                event_type, message, payload = self._classify_event(msg)
                if event_type and conn:
                    runs_service.record_event(
                        run_id, event_type, conn,
                        message=message,
                        payload_json=json.dumps(payload)
                        if payload else None,
                    )

                # Extract session_id from any message that carries it
                if not session_handle:
                    sid = msg.get("session_id")
                    if sid:
                        session_handle = sid
                        if conn:
                            runs_service.update_session_handle(
                                run_id, session_handle, conn,
                            )

            # Wait for process to finish
            proc.wait()
            exit_code = proc.returncode

            # Capture stderr for error reporting
            stderr_output = ""
            if proc.stderr:
                stderr_output = proc.stderr.read().decode(
                    "utf-8", errors="replace",
                )

            # Clean up process tracking
            with self._lock:
                self._processes.pop(run_id, None)

            # Parse usage signals from accumulated output
            raw_output = "\n".join(raw_lines)
            usage = self.parse_usage_signals(raw_output)

            # session_id may also appear in the result message
            if not session_handle and "session_id" in raw_output:
                for rl in reversed(raw_lines):
                    try:
                        m = json.loads(rl)
                        if m.get("session_id"):
                            session_handle = m["session_id"]
                            if conn:
                                runs_service.update_session_handle(
                                    run_id, session_handle, conn,
                                )
                            break
                    except (json.JSONDecodeError, ValueError):
                        continue

            usage_json = json.dumps(usage)

            # Determine outcome from exit code
            if exit_code == 0:
                outcome = "success"
            else:
                outcome = "failure"
                if conn and stderr_output:
                    runs_service.record_event(
                        run_id, "error", conn,
                        message=stderr_output[:2000],
                    )

            # Finish run
            if conn:
                runs_service.finish_run(
                    run_id, outcome, conn,
                    exit_code=exit_code,
                    observed_usage_signals_json=usage_json,
                )

            return {
                "status": "succeeded" if outcome == "success" else "failed",
                "outcome": outcome,
                "exit_code": exit_code,
                "session_handle": session_handle,
                "usage": usage,
            }

        except Exception as exc:
            logger.exception("Execution failed for run %s: %s", run_id, exc)

            # Clean up subprocess
            with self._lock:
                p = self._processes.pop(run_id, None)
            if p and p.poll() is None:
                try:
                    p.kill()
                    p.wait(timeout=5)
                except OSError:
                    pass

            if conn:
                runs_service.record_event(
                    run_id, "error", conn,
                    message=f"Adapter error: {exc}",
                )
                try:
                    runs_service.finish_run(
                        run_id, "failure", conn,
                        error_code="adapter_exception",
                    )
                except Exception:
                    pass  # run may already be in terminal state

            return {
                "status": "failed",
                "outcome": "failure",
                "error_code": "adapter_exception",
                "reason": str(exc),
            }

        finally:
            # Stop heartbeat thread
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=1)
            if conn:
                conn.close()
