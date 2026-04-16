"""Tests for executor permissions configuration (PR-33).

Three fixes:

1. ``setup.py`` creates scoped Claude Code ``settings.json`` for the
   niwa user during install — so ``claude -p`` in non-interactive
   mode has enough permissions to write files without requiring
   interactive approval.

2. ``executor.dangerous_mode`` DB setting — when enabled, the adapter
   adds ``--dangerously-skip-permissions`` to bypass all permission
   checks. Opt-in, off by default.

3. The adapter inspects the stream-json ``result`` event for
   ``is_error`` and ``permission_denials`` — so tasks that "succeed"
   (exit code 0) but actually failed due to permission blocks are
   correctly marked as ``failed``, not ``succeeded``.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "niwa-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ── Fix 1: scoped settings.json created during install ───────────

class TestSetupCreatesClaudeSettings:
    """Pin that ``_install_systemd_unit`` creates a scoped
    ``settings.json`` for the niwa user."""

    def _systemd_unit_body(self) -> str:
        src = (REPO_ROOT / "setup.py").read_text()
        start = src.index("def _install_systemd_unit(")
        tail = src[start:]
        end = re.search(r"\n(?=def [a-zA-Z_])", tail)
        return tail[: end.start() + 1] if end else tail

    def test_settings_json_created(self):
        body = self._systemd_unit_body()
        assert "settings.json" in body, (
            "_install_systemd_unit must create a Claude Code "
            "settings.json for the niwa user"
        )
        assert '"permissions"' in body, (
            "settings.json must contain a 'permissions' key with "
            "scoped allow-lists"
        )

    def test_bash_allowed(self):
        body = self._systemd_unit_body()
        assert 'Bash(command:*)' in body, (
            "scoped permissions must allow Bash commands "
            "(most tasks need shell execution)"
        )

    def test_read_allowed_all_paths(self):
        body = self._systemd_unit_body()
        assert 'Read(file_path:*)' in body, (
            "scoped permissions must allow Read on all paths "
            "(tasks need to inspect files)"
        )

    def test_write_scoped_to_project_dirs(self):
        body = self._systemd_unit_body()
        assert 'Write(file_path:{shared_dir}' in body or \
               'Write(file_path:/home/niwa' in body, (
            "Write must be scoped to project directories, "
            "not wildcard all paths"
        )

    def test_chown_niwa_on_settings(self):
        body = self._systemd_unit_body()
        assert 'chown' in body and 'claude' in body.lower(), (
            "settings.json must be chowned to niwa:niwa so the "
            "executor can read it"
        )

    def test_no_dangerously_skip_permissions_in_install_code(self):
        """The install must NOT add --dangerously-skip-permissions
        in generated commands or unit files. Mentions in docstrings
        or comments are OK (they document why it's avoided)."""
        body = self._systemd_unit_body()
        # Strip comments and docstrings, then check executable code.
        code_lines = [
            ln for ln in body.splitlines()
            if ln.strip()
            and not ln.strip().startswith("#")
            and not ln.strip().startswith('"""')
            and not ln.strip().startswith("'''")
            and "dedicated 'niwa' user" not in ln  # docstring ref
        ]
        code_only = "\n".join(code_lines)
        assert "--dangerously-skip-permissions" not in code_only, (
            "install must not add --dangerously-skip-permissions "
            "by default. Use scoped settings.json instead. "
            "Dangerous mode is an opt-in via DB setting."
        )


# ── Fix 2: dangerous mode toggle ────────────────────────────────

class TestDangerousModeToggle:
    """Pin that the adapter conditionally adds the flag and that
    the executor reads the DB setting."""

    def test_adapter_checks_dangerous_mode_flag(self):
        src = (BACKEND_DIR / "backend_adapters" / "claude_code.py").read_text()
        assert "_dangerous_mode" in src, (
            "ClaudeCodeAdapter._build_command must check "
            "profile['_dangerous_mode'] to conditionally add "
            "--dangerously-skip-permissions"
        )
        assert "--dangerously-skip-permissions" in src, (
            "The flag must appear in the adapter source (added "
            "conditionally, not always)"
        )

    def test_executor_reads_dangerous_mode_from_db(self):
        src = (REPO_ROOT / "bin" / "task-executor.py").read_text()
        assert "executor.dangerous_mode" in src, (
            "executor must read 'executor.dangerous_mode' from "
            "the settings table to pass to the adapter"
        )

    def test_adapter_does_not_add_flag_by_default(self):
        """When _dangerous_mode is not set or False, the flag
        must NOT appear in the command."""
        from backend_adapters.claude_code import ClaudeCodeAdapter

        cmd = ClaudeCodeAdapter._build_command(model="claude-sonnet-4-6")
        assert "--dangerously-skip-permissions" not in cmd, (
            "without _dangerous_mode=True, the flag must not appear"
        )

    def test_adapter_adds_flag_when_dangerous_mode_set(self):
        from backend_adapters.claude_code import ClaudeCodeAdapter

        cmd = ClaudeCodeAdapter._build_command(
            model="claude-sonnet-4-6",
            profile={"_dangerous_mode": True},
        )
        assert "--dangerously-skip-permissions" in cmd, (
            "with _dangerous_mode=True, the flag must appear"
        )


# ── Fix 3: permission denial detection ──────────────────────────

class TestPermissionDenialDetection:
    """Pin that the adapter source inspects the stream-json result
    for is_error and permission_denials."""

    def test_adapter_checks_permission_denials(self):
        src = (BACKEND_DIR / "backend_adapters" / "claude_code.py").read_text()
        assert "permission_denials" in src, (
            "adapter must inspect the stream-json result event's "
            "'permission_denials' field to detect false-succeeded"
        )

    def test_adapter_checks_is_error(self):
        src = (BACKEND_DIR / "backend_adapters" / "claude_code.py").read_text()
        assert "is_error" in src, (
            "adapter must inspect the stream-json result event's "
            "'is_error' field to detect execution errors"
        )

    def test_adapter_sets_error_code_permission_denied(self):
        src = (BACKEND_DIR / "backend_adapters" / "claude_code.py").read_text()
        assert '"permission_denied"' in src, (
            "when permission denials are detected, error_code "
            "must be set to 'permission_denied'"
        )

    def test_adapter_records_error_event_on_denial(self):
        src = (BACKEND_DIR / "backend_adapters" / "claude_code.py").read_text()
        assert "permission denial(s)" in src, (
            "the error event message must mention 'permission "
            "denial(s)' so the operator knows what happened"
        )

    def test_error_code_passed_to_finish_run(self):
        src = (BACKEND_DIR / "backend_adapters" / "claude_code.py").read_text()
        assert "error_code=error_code" in src, (
            "finish_run must receive error_code so the DB "
            "records why the run failed"
        )
