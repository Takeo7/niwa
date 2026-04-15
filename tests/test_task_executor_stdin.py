"""Tests for ``bin/task-executor.py::_run_llm``.

Regression guard for the "todas las tareas devuelven I need permission
to read that file" bug observed in production post-install:

Previously ``_run_llm`` wrote the prompt to a tempfile and appended
the path as a positional argument to ``claude -p``:

    cmd = shlex.split(command) + [prompt_file.name]

Claude Code does NOT parse that positional as a file reference — it
treats it as *prompt text*. The model then sees "please process this
path" and tries to open the file via its Read tool. The Read tool's
permission check fails (or is not pre-approved) and Claude's whole
output becomes a polite refusal:

    "I need permission to read that file."

Verified empirically in the VPS:

    $ claude -p /tmp/niwa-prompt-test.md
    I need permission to read that file.

    $ cat /tmp/niwa-prompt-test.md | claude -p
    SMOKE-OK 2026-04-15

Every task the executor processed since the install got that refusal
as its output. Severity: critical. The fix pipes the prompt to the
child's stdin instead of passing a path.

These tests mock ``pty.openpty`` and ``subprocess.Popen`` and assert:

  1. The argv does NOT contain a path argument (specifically, no
     tempfile path appended after ``shlex.split(command)``).
  2. ``Popen`` is called with ``stdin=subprocess.PIPE``, not
     ``stdin=<slave_fd>``.
  3. The prompt text is written to ``proc.stdin`` and ``close()`` is
     called (otherwise ``claude -p`` would hang waiting for EOF).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))


@pytest.fixture()
def executor_module(monkeypatch, tmp_path):
    """Import task-executor with minimal env so it doesn't try to
    touch real settings / log files / DB."""
    # The executor's ``_resolve_install_dir`` requires
    # ``<NIWA_HOME>/secrets/mcp.env`` to exist, so fake the skeleton.
    (tmp_path / "secrets").mkdir(parents=True, exist_ok=True)
    (tmp_path / "secrets" / "mcp.env").write_text("NIWA_DB_PATH=/tmp/x\n")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "data").mkdir(exist_ok=True)
    # Pre-create the log file to avoid permission issues on the
    # RotatingFileHandler in the imported module.
    (tmp_path / "logs" / "executor.log").touch()
    monkeypatch.setenv("NIWA_HOME", str(tmp_path))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_task_executor_under_test",
        str(BIN_DIR / "task-executor.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        pytest.skip(f"task-executor imports failed in this env: {e}")
    # Stub the LLM command so _run_llm doesn't short-circuit.
    mod.LLM_COMMAND = "claude -p --max-turns 1"
    yield mod


class _FakePopen:
    """A Popen stand-in that records how it was called and behaves
    like a child that produces one line of output then exits."""

    instances: list["_FakePopen"] = []

    def __init__(self, cmd, cwd=None, env=None, stdin=None,
                 stdout=None, stderr=None, close_fds=True):
        self.cmd = cmd
        self.cwd = cwd
        self.env = env
        self.stdin_arg = stdin
        self.stdout_arg = stdout
        self.stderr_arg = stderr
        # Record if stdin was requested as a pipe; if so, expose a
        # writable buffer so the caller can write the prompt to it.
        import io
        self._stdin_buf = io.BytesIO() if stdin is not None else None
        self.stdin_written: bytes = b""
        self.stdin_closed = False
        self.returncode = 0
        _FakePopen.instances.append(self)

    @property
    def stdin(self):
        if self._stdin_buf is None:
            return None
        return self

    def write(self, data: bytes) -> None:
        self.stdin_written += data

    def close(self) -> None:
        self.stdin_closed = True

    def poll(self):
        return 0

    def wait(self):
        return 0

    def kill(self):
        pass


@pytest.fixture()
def fake_popen(monkeypatch):
    _FakePopen.instances = []
    monkeypatch.setattr("subprocess.Popen", _FakePopen)
    yield _FakePopen


@pytest.fixture()
def fake_pty(monkeypatch):
    """Replace pty.openpty with a pair of open os pipes so the module's
    select/read loop doesn't block. We feed a short fake output and
    signal EOF by closing the write side immediately."""
    import os as _os
    import pty as _pty
    r, w = _os.pipe()
    _os.write(w, b"SMOKE-OK 2026-04-15\n")
    _os.close(w)
    monkeypatch.setattr(_pty, "openpty", lambda: (r, r))
    yield r


class TestRunLlmStdinContract:
    """Pin down the stdin-pipe contract of the LLM runner."""

    def test_cmd_argv_does_not_contain_prompt_file_path(
        self, executor_module, fake_popen, fake_pty,
    ):
        """The pre-fix bug: the argv ended with the path to a tempfile
        written with the prompt text. The fix drops that positional."""
        ok, _ = executor_module._run_llm(
            prompt="please respond with SMOKE-OK",
            cwd=REPO_ROOT,
            timeout=5,
        )
        assert fake_popen.instances, "Popen was never called"
        argv = fake_popen.instances[0].cmd
        # No path-ish trailing argument. The old bug ended the argv
        # with something like "/tmp/niwa-prompt-abc123.md".
        assert not any(
            str(a).startswith("/tmp/") and str(a).endswith(".md")
            for a in argv
        ), f"argv leaked a tempfile path: {argv}"

    def test_popen_is_called_with_stdin_pipe(
        self, executor_module, fake_popen, fake_pty,
    ):
        """Stdin must be a pipe (subprocess.PIPE), not the PTY slave
        fd. A PIPE lets us write the prompt bytes and close cleanly
        for EOF; the slave fd would require PTY-level EOF handling
        which is finicky with claude-code."""
        import subprocess
        executor_module._run_llm(
            prompt="please respond with SMOKE-OK",
            cwd=REPO_ROOT,
            timeout=5,
        )
        assert fake_popen.instances
        call = fake_popen.instances[0]
        assert call.stdin_arg == subprocess.PIPE, (
            f"stdin must be subprocess.PIPE, got {call.stdin_arg}"
        )

    def test_prompt_is_written_to_child_stdin_and_closed(
        self, executor_module, fake_popen, fake_pty,
    ):
        """The prompt content must reach the child's stdin; otherwise
        ``claude -p`` has no input to respond to."""
        prompt = "please respond with SMOKE-OK and nothing else"
        executor_module._run_llm(
            prompt=prompt,
            cwd=REPO_ROOT,
            timeout=5,
        )
        assert fake_popen.instances
        call = fake_popen.instances[0]
        assert prompt.encode("utf-8") in call.stdin_written, (
            f"prompt not written to stdin; got {call.stdin_written!r}"
        )
        assert call.stdin_closed, (
            "stdin must be close()d after writing — otherwise claude "
            "hangs forever waiting for more input (no EOF signal)"
        )


class TestRunLlmStaticSource:
    """Complement the mocked tests with a static regex over the
    executor source, so the contract is robust to future mocks that
    might accidentally accept the buggy shape."""

    def test_no_tempfile_prompt_path_appended_to_argv(self):
        src = (BIN_DIR / "task-executor.py").read_text()
        # The old buggy line:
        #   cmd = shlex.split(command) + [prompt_file.name]
        assert "prompt_file.name" not in src, (
            "task-executor.py must not append a tempfile path to the "
            "LLM command argv — Claude Code interprets the path as "
            "prompt text and emits 'I need permission to read that "
            "file.' as the whole answer. Pipe via stdin instead."
        )

    def test_stdin_pipe_and_prompt_write_present(self):
        src = (BIN_DIR / "task-executor.py").read_text()
        assert "stdin=subprocess.PIPE" in src, (
            "task-executor.py::_run_llm must invoke subprocess.Popen "
            "with stdin=subprocess.PIPE so the prompt can be piped in"
        )
        assert "proc.stdin.write" in src, (
            "task-executor.py must write the prompt to the child's "
            "stdin; otherwise claude -p has nothing to respond to"
        )
        assert "proc.stdin.close" in src, (
            "task-executor.py must close the child's stdin to signal "
            "EOF, otherwise claude -p hangs waiting for more input"
        )
