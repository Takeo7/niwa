"""Codex (OpenAI) backend adapter — PR-07 Niwa v0.2.

Real implementation of the Codex CLI backend.  Uses
``codex exec --json`` for execution with the prompt sent via stdin.

Codex CLI is assumed to emit JSON lines to stdout.  The adapter
parses these events, records them to ``backend_run_events`` in real
time, and manages the subprocess lifecycle identically to
``ClaudeCodeAdapter``.

Resume is NOT supported — Codex has no ``--resume`` flag.  The
adapter declares ``resume_modes=[]`` so the router skips it in the
resume-aware step (step 3 of ``decide()``).

Credentials: the adapter assumes the caller (task-executor) has
already configured ``CODEX_HOME`` and ``OPENAI_ACCESS_TOKEN`` in
the subprocess environment.  See ``_get_openai_oauth_token()`` in
``bin/task-executor.py``.

CLI invocation format is pending validation with the real Codex CLI
before PR-08.  See DECISIONS-LOG for details.
"""

import hashlib
import json
import logging
import os
import shlex
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backend_adapters.base import BackendAdapter

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────

HEARTBEAT_INTERVAL_SECONDS = 5
CANCEL_SIGTERM_WAIT_SECONDS = 5
CODEX_CLI_COMMAND = "codex"

# Usage signals schema — Codex exposes prompt_tokens / completion_tokens
# rather than Claude's input/output_tokens split.
USAGE_SIGNAL_FIELDS = (
    "input_tokens", "output_tokens", "total_tokens",
    "model", "cost_usd", "duration_ms", "turns",
)


# ── Approval gate (reuses PR-05 capability_service) ──────────────

def check_approval_gate(task: dict, run: dict, profile: dict,
                        capability_profile: dict) -> dict:
    """Pre-execution evaluation — delegates to capability_service.evaluate()."""
    import capability_service
    return capability_service.evaluate(task, run, profile, capability_profile)


# ── Helpers ────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class CodexAdapter(BackendAdapter):
    """Adapter for the Codex CLI backend.

    Constructor accepts an optional ``db_conn_factory`` callable that
    returns a ``sqlite3.Connection``.  When provided, the adapter
    writes streaming events, heartbeats, and usage signals to the
    database in real time.  When ``None`` (tests that only call
    ``capabilities()``), no DB interaction occurs.
    """

    def __init__(self, *, db_conn_factory: Callable | None = None):
        self._db_conn_factory = db_conn_factory
        self._processes: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    # ── Interface implementation ───────────────────────────────────

    def capabilities(self) -> dict[str, Any]:
        return {
            "resume_modes": [],
            "fs_modes": ["repo_only", "readonly"],
            "shell_modes": ["sandboxed"],
            "network_modes": ["off"],
            "approval_modes": ["always", "never"],
            "secrets_modes": ["env_inject", "none"],
            "estimated_resource_cost": None,
            "cost_confidence": "unknown",
            "quota_risk": "unknown",
            "latency_tier": "unknown",
        }

    def _require_db(self) -> None:
        if self._db_conn_factory is None:
            raise RuntimeError(
                "CodexAdapter requires db_conn_factory for execution. "
                "Use backend_registry.get_execution_registry() with a factory."
            )

    def start(self, task: dict, run: dict, profile: dict,
              capability_profile: dict) -> dict:
        """Start a new Codex execution for *task*."""
        self._require_db()

        eval_result = check_approval_gate(task, run, profile,
                                          capability_profile)
        if not eval_result["allowed"]:
            return self._handle_pre_execution_denial(
                task, run, eval_result,
            )

        artifact_root = run.get("artifact_root")
        if artifact_root:
            Path(artifact_root).mkdir(parents=True, exist_ok=True)

        prompt = self._build_prompt(task)
        model = profile.get("default_model")
        cmd = self._build_command(model=model, profile=profile)
        cwd = self._resolve_cwd(task, artifact_root)

        return self._execute(
            cmd=cmd, cwd=cwd, run=run, task=task,
            prompt_text=prompt, artifact_root=artifact_root,
            capability_profile=capability_profile,
        )

    def resume(self, task: dict, prior_run: dict, new_run: dict,
               profile: dict, capability_profile: dict) -> dict:
        """Resume is NOT supported by Codex — fail explicitly.

        The router already skips Codex in the resume-aware step
        because ``resume_modes`` is empty.  This method only fires
        if someone calls it directly.
        """
        self._require_db()

        import runs_service

        run_id = new_run["id"]
        conn = self._db_conn_factory()
        try:
            runs_service.transition_run(run_id, "starting", conn)
            runs_service.record_event(
                run_id, "resume_not_supported", conn,
                message="Codex does not support session resume.",
            )
            runs_service.finish_run(
                run_id, "failure", conn,
                error_code="resume_not_supported",
            )
        finally:
            conn.close()

        return {
            "status": "failed",
            "outcome": "failure",
            "error_code": "resume_not_supported",
            "reason": "Codex does not support session resume. "
                      "resume_modes is empty.",
        }

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

        try:
            proc.terminate()
            logger.info("cancel: SIGTERM run %s pid %d", run_id, proc.pid)
        except OSError:
            pass

        try:
            proc.wait(timeout=CANCEL_SIGTERM_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=5)
                logger.warning("cancel: SIGKILL run %s pid %d",
                               run_id, proc.pid)
            except OSError:
                pass

        with self._lock:
            self._processes.pop(run_id, None)

        if self._db_conn_factory:
            import runs_service
            conn = self._db_conn_factory()
            try:
                runs_service.record_event(
                    run_id, "cancelled", conn,
                    message="Execution cancelled by user request.",
                )
                current = conn.execute(
                    "SELECT status FROM backend_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
                if current and current["status"] not in (
                    "succeeded", "failed", "cancelled",
                    "timed_out", "rejected",
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
            return {"alive": False,
                    "details": "No active process tracked."}

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
        """Scan ``artifact_root`` and register files."""
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
        """Extract usage signals from accumulated Codex JSON output.

        Scans all JSON lines for ``result`` type messages to extract
        token counts, cost, and model info.
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

            if msg_type == "message" and msg.get("role") == "assistant":
                turns += 1

            if msg_type == "result":
                signals["cost_usd"] = msg.get("cost_usd")
                signals["duration_ms"] = msg.get("duration_ms")
                signals["model"] = msg.get("model")
                usage = msg.get("usage") or {}
                if usage:
                    signals["input_tokens"] = usage.get("prompt_tokens")
                    signals["output_tokens"] = usage.get(
                        "completion_tokens",
                    )
                    signals["total_tokens"] = usage.get("total_tokens")

        signals["turns"] = turns if turns > 0 else None
        return signals

    # ── Approval gate helpers ─────────────────────────────────────

    def _handle_pre_execution_denial(self, task: dict, run: dict,
                                     eval_result: dict) -> dict:
        """Handle a pre-execution denial from the approval gate.

        Same logic as ClaudeCodeAdapter: if approval_required, creates
        an approval and transitions run to ``waiting_approval``.
        Otherwise transitions to ``failed`` with ``capability_denied``.
        """
        import approval_service
        import runs_service

        run_id = run["id"]
        conn = self._db_conn_factory()

        try:
            runs_service.transition_run(run_id, "starting", conn)

            if eval_result.get("approval_required"):
                runs_service.record_event(
                    run_id, "approval_gate_triggered", conn,
                    message=eval_result["reason"],
                    payload_json=json.dumps(eval_result),
                )
                runs_service.transition_run(
                    run_id, "waiting_approval", conn,
                )
                trigger_type = (
                    eval_result["triggers"][0]["type"]
                    if eval_result.get("triggers")
                    else "pre_execution_denied"
                )
                approval_service.request_approval(
                    task["id"], run_id,
                    trigger_type,
                    eval_result["reason"],
                    "medium",
                    conn,
                )
                return {
                    "status": "waiting_approval",
                    "reason": eval_result["reason"],
                    "triggers": eval_result.get("triggers", []),
                }
            else:
                runs_service.finish_run(
                    run_id, "failure", conn,
                    error_code="capability_denied",
                )
                return {
                    "status": "failed",
                    "outcome": "failure",
                    "error_code": "capability_denied",
                    "reason": eval_result["reason"],
                }
        finally:
            conn.close()

    def _terminate_process(self, run_id: str) -> None:
        """Kill the process for *run_id*.

        SIGTERM → wait ``CANCEL_SIGTERM_WAIT_SECONDS`` → SIGKILL.
        """
        with self._lock:
            proc = self._processes.pop(run_id, None)

        if proc is None:
            return

        try:
            proc.terminate()
            logger.info("terminate: SIGTERM run %s pid %d",
                        run_id, proc.pid)
        except OSError:
            pass

        try:
            proc.wait(timeout=CANCEL_SIGTERM_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=5)
                logger.warning("terminate: SIGKILL run %s pid %d",
                               run_id, proc.pid)
            except OSError:
                pass

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
    def _build_command(*, model: str | None = None,
                       profile: dict | None = None) -> list[str]:
        """Build the ``codex`` CLI command list.

        Default: ``codex exec --json``.  Uses ``command_template``
        from the backend profile if provided.
        """
        cli_parts = [CODEX_CLI_COMMAND]
        if profile and profile.get("command_template"):
            cli_parts = shlex.split(profile["command_template"])
        else:
            cli_parts = [CODEX_CLI_COMMAND, "exec", "--json"]

        if model:
            cli_parts.extend(["--model", model])
        return cli_parts

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
        _PATCH = {'.diff', '.patch'}

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
        if suffix in _PATCH:
            return "patch"
        return "file"

    @staticmethod
    def _classify_event(msg: dict) -> tuple[str | None, str | None,
                                            dict | None]:
        """Map a Codex JSON-line message to (event_type, message, payload).

        Codex events use a different schema from Claude's stream-json.
        """
        msg_type = msg.get("type", "")

        if msg_type == "status":
            return (
                "system_init",
                msg.get("status", "Status event"),
                msg,
            )

        if msg_type == "message":
            content = msg.get("content", "")
            return (
                "assistant_message",
                content[:2000] if content else "Message",
                {"content": content} if content else None,
            )

        if msg_type == "command":
            name = msg.get("name", "shell")
            cmd_str = msg.get("command", "")
            return (
                "tool_use",
                f"Command: {name} — {cmd_str}"[:2000],
                {"tool_name": name, "command": cmd_str},
            )

        if msg_type == "command_output":
            return (
                "tool_result",
                str(msg.get("output", ""))[:2000],
                {"output": msg.get("output"),
                 "exit_code": msg.get("exit_code")},
            )

        if msg_type == "result":
            return (
                "result",
                f"Execution completed (cost={msg.get('cost_usd', '?')})",
                msg,
            )

        if msg_type == "error":
            return (
                "error",
                str(msg.get("message", msg))[:2000],
                msg,
            )

        if msg_type:
            return (msg_type, json.dumps(msg)[:2000], msg)

        return (None, None, None)

    @staticmethod
    def _normalize_for_runtime_check(msg: dict) -> dict | None:
        """Normalize a Codex ``command`` event to the ``tool_use`` format
        expected by ``capability_service.evaluate_runtime_event()``.

        Returns ``None`` for events that don't need runtime checking.
        """
        if msg.get("type") != "command":
            return None
        return {
            "type": "tool_use",
            "name": "Bash",
            "input": {"command": msg.get("command", "")},
        }

    def _heartbeat_worker(self, run_id: str, proc: subprocess.Popen,
                          stop_event: threading.Event) -> None:
        """Daemon thread: update heartbeat_at periodically."""
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
                logger.debug("heartbeat_worker: failed for run %s",
                             run_id, exc_info=True)

    def _execute(self, *, cmd: list[str], cwd: str, run: dict,
                 task: dict, prompt_text: str,
                 artifact_root: str | None,
                 capability_profile: dict | None = None) -> dict:
        """Core execution loop: spawn process, stream events, finish run.

        Blocks until the Codex process exits.  A daemon heartbeat
        thread updates ``heartbeat_at`` independently of stdout.
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
                name=f"heartbeat-codex-{run_id[:8]}",
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

                # Extract session_id
                if not session_handle:
                    sid = msg.get("session_id")
                    if sid:
                        session_handle = sid
                        if conn:
                            runs_service.update_session_handle(
                                run_id, session_handle, conn,
                            )

                # ── Runtime capability check ───────────────────
                if capability_profile:
                    normalized = self._normalize_for_runtime_check(msg)
                    if normalized is not None:
                        import capability_service
                        rt_check = (
                            capability_service.evaluate_runtime_event(
                                normalized, capability_profile,
                                workspace_path=cwd,
                            )
                        )
                        if not rt_check["allowed"]:
                            if conn:
                                import approval_service
                                runs_service.record_event(
                                    run_id,
                                    "approval_gate_triggered",
                                    conn,
                                    message=rt_check["reason"],
                                    payload_json=json.dumps(rt_check),
                                )
                                trigger_type = (
                                    rt_check["triggers"][0]["type"]
                                    if rt_check.get("triggers")
                                    else "runtime_violation"
                                )
                                approval_service.request_approval(
                                    task["id"], run_id,
                                    trigger_type,
                                    rt_check["reason"],
                                    "medium",
                                    conn,
                                )
                                runs_service.transition_run(
                                    run_id, "waiting_approval", conn,
                                )
                            self._terminate_process(run_id)
                            return {
                                "status": "waiting_approval",
                                "reason": rt_check["reason"],
                                "triggers": rt_check.get("triggers", []),
                            }

            # Wait for process to finish
            proc.wait()
            exit_code = proc.returncode

            stderr_output = ""
            if proc.stderr:
                stderr_output = proc.stderr.read().decode(
                    "utf-8", errors="replace",
                )

            with self._lock:
                self._processes.pop(run_id, None)

            # Parse usage signals
            raw_output = "\n".join(raw_lines)
            usage = self.parse_usage_signals(raw_output)

            # session_id may appear in later messages
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

            if exit_code == 0:
                outcome = "success"
            else:
                outcome = "failure"
                if conn and stderr_output:
                    runs_service.record_event(
                        run_id, "error", conn,
                        message=stderr_output[:2000],
                    )

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
            logger.exception("Execution failed for run %s: %s",
                             run_id, exc)

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
                    pass

            return {
                "status": "failed",
                "outcome": "failure",
                "error_code": "adapter_exception",
                "reason": str(exc),
            }

        finally:
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=1)
            if conn:
                conn.close()
