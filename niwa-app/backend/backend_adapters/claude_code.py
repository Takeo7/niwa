"""Claude Code backend adapter — PR-04/PR-05 Niwa v0.2.

Real implementation of the Claude Code CLI backend.  Uses
``claude -p --output-format stream-json`` for execution and
``--resume <session_id>`` for resume.

Streaming events from the CLI are written to ``backend_run_events``
in real time.  Session handles, usage signals, and artifacts are
persisted at the appropriate lifecycle points.

Resource-budget fields (``estimated_resource_cost``, ``cost_confidence``,
``quota_risk``, ``latency_tier``) default to unknowns here.  PR-06 will
populate them with deterministic routing logic.

PR-05 adds:
  - Real approval gate replacing the PR-04 stub.  Pre-execution
    evaluation via ``capability_service.evaluate()``.
  - Runtime monitoring of ``tool_use`` events via
    ``capability_service.evaluate_runtime_event()`` — when a policy
    violation is detected the adapter creates an approval, transitions
    the run to ``waiting_approval``, and kills the Claude process.
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


# ── Approval gate (PR-05) ────────────────────────────────────────

def check_approval_gate(task: dict, run: dict, profile: dict,
                        capability_profile: dict) -> dict:
    """Pre-execution evaluation of the task against the capability profile.

    Delegates to ``capability_service.evaluate()`` which returns::

        {
            "allowed": bool,
            "reason": str,
            "approval_required": bool,
            "triggers": [{"type": str, "detail": str}, ...],
        }

    If ``allowed`` is True, execution proceeds.  Otherwise the caller
    handles denial (approval creation or capability_denied failure).
    """
    import capability_service
    return capability_service.evaluate(task, run, profile, capability_profile)


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

        eval_result = check_approval_gate(task, run, profile, capability_profile)
        if not eval_result["allowed"]:
            return self._handle_pre_execution_denial(
                task, run, eval_result,
            )

        artifact_root = run.get("artifact_root")
        mkdir_err = self._ensure_artifact_root(run)
        if mkdir_err is not None:
            return mkdir_err

        prompt = self._build_prompt(task)
        model = profile.get("default_model") or "claude-sonnet-4-6"
        cmd = self._build_command(model=model, profile=profile)
        cwd = self._resolve_cwd(task, artifact_root)

        return self._execute(
            cmd=cmd, cwd=cwd, run=run, task=task,
            prompt_text=prompt, artifact_root=artifact_root,
            capability_profile=capability_profile,
            extra_env=profile.get("_extra_env"),
        )

    def resume(self, task: dict, prior_run: dict, new_run: dict,
               profile: dict, capability_profile: dict) -> dict:
        """Resume execution from *prior_run*'s Claude session."""
        self._require_db()

        eval_result = check_approval_gate(task, new_run, profile, capability_profile)
        if not eval_result["allowed"]:
            return self._handle_pre_execution_denial(
                task, new_run, eval_result,
            )

        session_id = prior_run.get("session_handle")
        if not session_id:
            return {
                "status": "failed", "outcome": "failure",
                "error_code": "no_session_handle",
                "reason": "Prior run has no session_handle to resume from.",
            }

        artifact_root = new_run.get("artifact_root")
        mkdir_err = self._ensure_artifact_root(new_run)
        if mkdir_err is not None:
            return mkdir_err

        prompt = self._build_prompt(task)
        model = profile.get("default_model") or "claude-sonnet-4-6"
        cmd = self._build_command(
            model=model, resume_session_id=session_id, profile=profile,
        )
        cwd = self._resolve_cwd(task, artifact_root)

        return self._execute(
            cmd=cmd, cwd=cwd, run=new_run, task=task,
            prompt_text=prompt, artifact_root=artifact_root,
            capability_profile=capability_profile,
            extra_env=profile.get("_extra_env"),
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

    # ── Approval gate helpers (PR-05) ─────────────────────────────

    def _handle_pre_execution_denial(self, task: dict, run: dict,
                                     eval_result: dict) -> dict:
        """Handle a pre-execution denial from the approval gate.

        If ``eval_result["approval_required"]`` is True, creates an
        approval and transitions the run to ``waiting_approval``.
        Otherwise transitions to ``failed`` with ``capability_denied``.

        Uses ``starting → waiting_approval`` or ``starting → failed``
        (added to the state machine in PR-05).  The run never reaches
        ``running`` state when denied pre-execution.
        """
        import approval_service
        import runs_service

        run_id = run["id"]
        conn = self._db_conn_factory()

        try:
            # queued → starting
            runs_service.transition_run(run_id, "starting", conn)

            if eval_result.get("approval_required"):
                runs_service.record_event(
                    run_id, "approval_gate_triggered", conn,
                    message=eval_result["reason"],
                    payload_json=json.dumps(eval_result),
                )
                # starting → waiting_approval (no running state)
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
                # starting → failed (no running state)
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
        Removes the process from the internal tracking dict.
        """
        with self._lock:
            proc = self._processes.pop(run_id, None)

        if proc is None:
            return

        try:
            proc.terminate()
            logger.info("terminate: SIGTERM run %s pid %d", run_id, proc.pid)
        except OSError:
            pass

        try:
            proc.wait(timeout=CANCEL_SIGTERM_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=5)
                logger.warning(
                    "terminate: SIGKILL run %s pid %d", run_id, proc.pid,
                )
            except OSError:
                pass

    # ── Private helpers ────────────────────────────────────────────

    def _ensure_artifact_root(self, run: dict) -> dict | None:
        """Create ``run['artifact_root']`` on disk if set.

        Bug 24 (docs/BUGS-FOUND.md): a raw ``Path.mkdir(...)`` here
        could raise ``PermissionError`` / ``OSError`` (e.g. the dir
        lives under a project owned by another user). The executor's
        generic ``except Exception`` catches it and marks the run
        ``failed`` with ``error_code='adapter_exception'`` — technically
        correct, but the operator gets no hint it was specifically a
        filesystem/permissions issue.

        This helper transitions the run explicitly with
        ``error_code='artifact_root_mkdir_failed'`` and returns a
        failed-status dict so the caller gets the same shape as other
        pre-execution denials (non-transient — no point escalating to
        a fallback that would hit the same path).

        Returns ``None`` on success; the dict to return on failure.
        """
        artifact_root = run.get("artifact_root")
        if not artifact_root:
            return None
        try:
            Path(artifact_root).mkdir(parents=True, exist_ok=True)
            return None
        except OSError as e:
            self._finish_run_failed(
                run_id=run["id"],
                error_code="artifact_root_mkdir_failed",
                exit_code=1,
                event_message=(
                    f"Could not create artifact_root "
                    f"{artifact_root!r}: {e}. Check that the path "
                    "is writable by the niwa user."
                ),
            )
            return {
                "status": "failed",
                "outcome": "failure",
                "error_code": "artifact_root_mkdir_failed",
                "reason": (
                    f"Could not create artifact_root "
                    f"{artifact_root!r}: {e}."
                ),
            }

    def _finish_run_failed(
        self, *, run_id: str, error_code: str,
        exit_code: int, event_message: str,
    ) -> None:
        """Transition a run to failed state from inside the adapter,
        best-effort. Used by ``_ensure_artifact_root`` and any other
        early-abort path that needs to leave the run in a terminal
        state (not ``starting``) before returning to the caller."""
        if not self._db_conn_factory:
            return
        import runs_service
        conn = self._db_conn_factory()
        try:
            try:
                runs_service.record_event(
                    run_id, "error", conn, message=event_message,
                )
            except Exception:
                pass
            try:
                runs_service.finish_run(
                    run_id, "failure", conn,
                    error_code=error_code, exit_code=exit_code,
                )
            except Exception:
                pass
        finally:
            conn.close()

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

        # PR-38 / PR-42 / PR-43: if the executor pre-created a
        # project directory for this task (no project_id yet),
        # force Claude to write there.
        #
        # Evolution: PR-38 wording was too soft ("if this involves
        # creating artifacts…") and Claude defaulted to /tmp/.
        # PR-42 added imperative language + a blacklist of common
        # paths (/tmp/, /home/, /root/…). That broke in prod because
        # ``_auto_projects_root = <NIWA_HOME>/data/projects/`` — when
        # the installer ran as root, ``NIWA_HOME=/root/.niwa`` and
        # every project_directory STARTS WITH /root/. The blacklist
        # then contradicted the main rule ("write under /root/.niwa/
        # …" + "never write under /root/…"). Claude resolved the
        # ambiguity by writing to /tmp/ which at least violated only
        # one of the conflicting rules.
        #
        # PR-43: drop the fixed blacklist. State the rule positively
        # ("paths must start with <pdir>") and mention /tmp/ only as
        # a common habit to avoid — not as a blanket ban that can
        # collide with the project_directory itself.
        pdir = task.get("project_directory")
        if pdir and not task.get("project_id"):
            parts.append(
                "\n## WORKING DIRECTORY — STRICT RULE\n"
                f"A fresh directory has been prepared for this task:\n\n"
                f"    {pdir}\n\n"
                "Your shell is already `cd`'d there — "
                "**relative paths just work**. Prefer them.\n\n"
                "**THE RULE:** every absolute path you write to MUST "
                f"start with `{pdir}`. Anything else is out of scope "
                "for this task and will be lost — the post-hook that "
                "registers your work as a Niwa project only looks "
                "inside that directory.\n\n"
                "Common mistake to avoid: defaulting to `/tmp/<name>/`. "
                "If you catch yourself about to call "
                "`Write(/tmp/...)` or `Bash(mkdir /tmp/...)`, stop "
                "and use the working directory instead.\n\n"
                "## REGISTER THE PROJECT\n"
                "Before writing any file, call the `project_create` "
                "MCP tool so it shows up in the Niwa UI. Exact "
                "arguments:\n\n"
                "```json\n"
                "{\n"
                f'  "name": {title!r},\n'
                '  "area": "proyecto",\n'
                f'  "directory": {pdir!r},\n'
                '  "description": "<one sentence of what you\'re building>"\n'
                "}\n"
                "```\n\n"
                "If this task is purely conversational (a question, a "
                "review, a summary) and you will NOT create files, "
                "you may skip `project_create` entirely. But if you "
                "create even one file, both rules above apply: "
                "register the project AND write inside the working "
                "directory."
            )

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

        cmd = cli_parts + ["-p", "--output-format", "stream-json", "--verbose",
                           "--dangerously-skip-permissions"]
        if model:
            cmd.extend(["--model", model])
        if resume_session_id:
            cmd.extend(["--resume", resume_session_id])
        # PR-33 introduced a _dangerous_mode toggle to conditionally
        # add the flag. PR-34 makes it the default: the niwa user is
        # a dedicated service account (not root), OS permissions ARE
        # the sandbox, and Claude Code's scoped settings.json format
        # proved unreliable in non-interactive mode (permissions were
        # blocked even for allowed paths). The flag is always on now.
        # If a future Claude Code release supports reliable scoped
        # permissions in -p mode, revisit and gate behind the toggle.
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
                 artifact_root: str | None,
                 capability_profile: dict | None = None,
                 extra_env: dict | None = None) -> dict:
        """Core execution loop: spawn process, stream events, finish run.

        This method blocks until the Claude process exits.  The caller
        (PR-06 task-executor) is expected to call it from a worker thread.

        A daemon heartbeat thread runs independently, updating
        ``heartbeat_at`` every ``HEARTBEAT_INTERVAL_SECONDS`` regardless
        of stdout activity.

        *extra_env*, when provided, is merged into the subprocess
        environment.  Used by the executor to inject credentials
        (``ANTHROPIC_API_KEY``, ``OPENAI_ACCESS_TOKEN``, etc.)
        without polluting ``os.environ``.
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
            if extra_env:
                env.update(extra_env)

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

                # ── Runtime capability check (PR-05) ─────────────
                if event_type == "tool_use" and capability_profile:
                    import capability_service
                    rt_check = capability_service.evaluate_runtime_event(
                        msg, capability_profile, workspace_path=cwd,
                    )
                    if not rt_check["allowed"]:
                        if conn:
                            import approval_service
                            runs_service.record_event(
                                run_id, "approval_gate_triggered", conn,
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

            # Determine outcome from exit code + stream-json result.
            #
            # PR-33: exit code 0 does NOT guarantee the task actually
            # succeeded. Claude CLI exits 0 even when every write was
            # blocked by permission denials. We inspect the final
            # ``result`` event in the stream for ``is_error`` and
            # ``permission_denials`` to catch "false succeeded" cases.
            # The operator then sees the task as FAILED with a clear
            # reason instead of a misleading "hecha" with no output.
            error_code = None
            result_text = ""  # Human-readable output from Claude
            if exit_code == 0:
                outcome = "success"
                # Check stream-json result event for is_error or
                # permission denials — override to failure if found.
                # Also extract result_text for the task output.
                for rl in reversed(raw_lines):
                    try:
                        m = json.loads(rl)
                        if m.get("type") != "result":
                            continue
                        # PR-35: extract the human-readable result
                        # text so the executor can store it as the
                        # task output (visible in the UI). Without
                        # this the task shows "[v02] Backend
                        # claude_code completed: {...}" — useless.
                        result_text = m.get("result", "") or ""
                        perm_denials = m.get("permission_denials") or []
                        if perm_denials:
                            outcome = "failure"
                            error_code = "permission_denied"
                            if conn:
                                runs_service.record_event(
                                    run_id, "error", conn,
                                    message=(
                                        f"Task failed: {len(perm_denials)} "
                                        f"permission denial(s). Claude Code "
                                        f"could not write files. Configure "
                                        f"permissions in System → Agents or "
                                        f"enable dangerous mode."
                                    ),
                                )
                        elif m.get("is_error"):
                            outcome = "failure"
                            error_code = "execution_error"
                            result_text = m.get("result", "")
                            if conn and result_text:
                                runs_service.record_event(
                                    run_id, "error", conn,
                                    message=str(result_text)[:2000],
                                )
                        break
                    except (json.JSONDecodeError, ValueError):
                        continue
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
                    error_code=error_code,
                    observed_usage_signals_json=usage_json,
                )

            return {
                "status": "succeeded" if outcome == "success" else "failed",
                "outcome": outcome,
                "exit_code": exit_code,
                "error_code": error_code,
                "session_handle": session_handle,
                "usage": usage,
                "result_text": result_text,
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
