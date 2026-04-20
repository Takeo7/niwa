"""Claude Code CLI adapter — subprocess + stream-json parser.

Spawns ``claude -p --output-format stream-json`` and yields one
``AdapterEvent`` per stdout line. DB-agnostic: the executor writes rows.

Only stdlib. ``selectors`` makes the stdout read non-blocking so the
global timeout can actually fire. stderr drains in a daemon thread into
a bounded buffer (64 KB) to avoid a pipe-full deadlock.

Outcomes: ``cli_ok``, ``cli_nonzero_exit``, ``cli_not_found``, ``timeout``.
"""

from __future__ import annotations

import json
import logging
import os
import selectors
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger("niwa.adapter.claude")

_POLL_TIMEOUT = 0.5
_SIGTERM_GRACE = 5.0
_STDERR_LIMIT = 64 * 1024
_DEFAULT_TIMEOUT = 1800.0


@dataclass(frozen=True)
class AdapterEvent:
    """One parsed event from the stream. ``kind`` is the raw ``type``."""

    kind: str
    payload: dict[str, Any]
    raw_line: str


class ClaudeCodeAdapter:
    """Run the Claude CLI and stream parsed events."""

    # ``-p``              : headless (non-interactive) mode.
    # ``--output-format`` : stream-json, one JSON event per stdout line.
    # ``--verbose``       : without it, stream-json emits only the final
    #                       result message — we need the intermediate
    #                       assistant/tool_use events too. This matches
    #                       v0.2's ``niwa-app/backend/backend_adapters/
    #                       claude_code.py`` command construction.
    DEFAULT_ARGS: tuple[str, ...] = ("-p", "--output-format", "stream-json", "--verbose")

    def __init__(
        self,
        cli_path: str | None,
        *,
        cwd: str,
        prompt: str,
        timeout: float = _DEFAULT_TIMEOUT,
        extra_args: list[str] | None = None,
    ) -> None:
        self._cli_path = cli_path
        self._cwd = cwd
        self._prompt = prompt
        self._timeout = timeout
        self._extra_args = list(extra_args or [])
        self._proc: subprocess.Popen[bytes] | None = None
        self._stderr_buf = bytearray()
        self._stderr_thread: threading.Thread | None = None
        self._outcome: str | None = None
        self._exit_code: int | None = None

    @property
    def outcome(self) -> str | None:
        return self._outcome

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

    def iter_events(self) -> Iterator[AdapterEvent]:
        """Spawn the CLI; yield one event per JSON line of stdout.

        Sets ``outcome`` to ``cli_not_found`` when the binary is missing
        and to ``timeout`` when the global deadline trips. Final
        success/failure (``cli_ok``/``cli_nonzero_exit``) is set in
        ``wait()`` from the exit code.
        """

        if not self._cli_path or not os.path.exists(self._cli_path):
            logger.warning("claude CLI not found at %r", self._cli_path)
            self._outcome = "cli_not_found"
            return

        cmd = [self._cli_path, *self.DEFAULT_ARGS, *self._extra_args]
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self._cwd,
                env={**os.environ, "NO_COLOR": "1"},
            )
        except FileNotFoundError:
            logger.warning("spawn failed: %r not found", self._cli_path)
            self._outcome = "cli_not_found"
            return

        self._proc = proc
        self._start_stderr_drain(proc)
        if proc.stdin is not None:
            try:
                proc.stdin.write(self._prompt.encode("utf-8"))
                proc.stdin.close()
            except BrokenPipeError:
                pass

        assert proc.stdout is not None
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + self._timeout
        buf = bytearray()
        deadline_hit = False

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    deadline_hit = True
                    break
                ready = sel.select(timeout=min(_POLL_TIMEOUT, remaining))
                if ready:
                    chunk = proc.stdout.read1(4096)
                    if not chunk:
                        break
                    buf.extend(chunk)
                    while True:
                        nl = buf.find(b"\n")
                        if nl < 0:
                            break
                        event = _parse_line(bytes(buf[:nl]))
                        del buf[: nl + 1]
                        if event is not None:
                            yield event
                elif proc.poll() is not None:
                    rest = proc.stdout.read()
                    if rest:
                        buf.extend(rest)
                    break
        finally:
            sel.close()

        if buf:
            event = _parse_line(bytes(buf))
            if event is not None:
                yield event

        if deadline_hit:
            self._terminate()
            self._outcome = "timeout"

    def wait(self) -> int | None:
        """Reap the process and finalize ``outcome``. Safe if not spawned."""

        if self._proc is None:
            return None
        try:
            self._exit_code = self._proc.wait(timeout=_SIGTERM_GRACE)
        except subprocess.TimeoutExpired:
            self._terminate()
            self._exit_code = self._proc.returncode
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=1.0)
        if self._outcome is None:
            self._outcome = "cli_ok" if self._exit_code == 0 else "cli_nonzero_exit"
        return self._exit_code

    def _start_stderr_drain(self, proc: subprocess.Popen[bytes]) -> None:
        if proc.stderr is None:
            return

        def drain() -> None:
            assert proc.stderr is not None
            try:
                for chunk in iter(lambda: proc.stderr.read(4096), b""):
                    if not chunk:
                        break
                    self._stderr_buf.extend(chunk)
                    overflow = len(self._stderr_buf) - _STDERR_LIMIT
                    if overflow > 0:
                        del self._stderr_buf[:overflow]
            except Exception:
                logger.debug("stderr drain crashed", exc_info=True)

        t = threading.Thread(target=drain, name="claude-stderr", daemon=True)
        t.start()
        self._stderr_thread = t

    def _terminate(self) -> None:
        """SIGTERM, wait 5 s, SIGKILL if still alive."""

        if self._proc is None or self._proc.poll() is not None:
            return
        try:
            self._proc.send_signal(signal.SIGTERM)
        except OSError:
            pass
        try:
            self._proc.wait(timeout=_SIGTERM_GRACE)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            self._proc.kill()
            self._proc.wait(timeout=_SIGTERM_GRACE)
        except OSError:
            pass


def resolve_cli_path() -> str | None:
    """``NIWA_CLAUDE_CLI`` if set, else ``shutil.which('claude')``."""

    return os.environ.get("NIWA_CLAUDE_CLI") or shutil.which("claude")


def resolve_timeout() -> float:
    """Parse ``NIWA_CLAUDE_TIMEOUT`` seconds or fall back to 1800."""

    raw = os.environ.get("NIWA_CLAUDE_TIMEOUT")
    if raw is None:
        return _DEFAULT_TIMEOUT
    try:
        return float(raw)
    except ValueError:
        logger.warning("invalid NIWA_CLAUDE_TIMEOUT=%r, using default", raw)
        return _DEFAULT_TIMEOUT


def _parse_line(raw: bytes) -> AdapterEvent | None:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
    except ValueError:
        logger.warning("skipping non-JSON stream line: %r", text[:120])
        return None
    if not isinstance(obj, dict):
        return None
    return AdapterEvent(kind=str(obj.get("type") or "unknown"), payload=obj, raw_line=text)


__all__ = ["AdapterEvent", "ClaudeCodeAdapter", "resolve_cli_path", "resolve_timeout"]
