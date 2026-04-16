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

    def test_install_does_not_hardcode_flag_in_unit_template(self):
        """The systemd unit template must NOT bake the
        --dangerously-skip-permissions flag into ExecStart.
        The flag is added by the adapter at runtime (PR-34),
        not by the installer."""
        body = self._systemd_unit_body()
        # Check unit templates (the f-string blocks).
        import re
        unit_blocks = re.findall(
            r'unit\s*=\s*f"""\[Unit\].*?"""', body, flags=re.DOTALL,
        )
        for block in unit_blocks:
            assert "--dangerously-skip-permissions" not in block, (
                "unit template must not hardcode the flag — "
                "the adapter adds it at runtime"
            )


# ── Fix 2: --dangerously-skip-permissions always on (PR-34) ──────

class TestDangerousPermissionsAlwaysOn:
    """PR-34: the flag is always present. The niwa user is the
    OS-level sandbox. Claude Code's scoped settings.json proved
    unreliable in non-interactive -p mode."""

    def test_flag_always_in_command(self):
        from backend_adapters.claude_code import ClaudeCodeAdapter

        cmd = ClaudeCodeAdapter._build_command(model="claude-sonnet-4-6")
        assert "--dangerously-skip-permissions" in cmd, (
            "_build_command must always include "
            "--dangerously-skip-permissions (PR-34). The niwa user "
            "is the OS sandbox; Claude Code's scoped settings.json "
            "was unreliable in non-interactive mode."
        )

    def test_flag_present_even_without_profile(self):
        from backend_adapters.claude_code import ClaudeCodeAdapter

        cmd = ClaudeCodeAdapter._build_command(
            model="claude-sonnet-4-6", profile=None,
        )
        assert "--dangerously-skip-permissions" in cmd


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


# ── Fix 4 (PR-34): failed adapter → task NOT hecha ──────────────

class TestFailedAdapterDoesNotMarkTaskDone:
    """PR-34 fix: if the adapter returns status=failed, the
    executor must return False (not True) so the task is NOT
    marked as hecha. Before PR-34, _execute_task_v02 returned
    True unconditionally after the adapter finished, regardless
    of the adapter's outcome — so tasks with permission denials
    ended as 'hecha' with no real work done."""

    def test_executor_checks_adapter_status_failed(self):
        src = (REPO_ROOT / "bin" / "task-executor.py").read_text()
        assert 'adapter_status == "failed"' in src, (
            "_execute_task_v02 must check adapter result status. "
            "If failed, return False so the task is not marked hecha."
        )

    def test_executor_returns_false_on_adapter_failure(self):
        import re
        src = (REPO_ROOT / "bin" / "task-executor.py").read_text()
        # PR-38 moved the actual body to ``_execute_task_v02_body``
        # (the outer wrapper wraps it in a try/finally for the
        # auto-project hook). The assertion still holds — look for
        # the body.
        start = src.index("def _execute_task_v02_body(")
        tail = src[start:]
        end = re.search(r"\ndef [a-zA-Z_]", tail)
        body = tail[: end.start()] if end else tail

        # After checking adapter_status == "failed", the function
        # must return False (not True).
        failed_block = body[body.index('adapter_status == "failed"'):]
        # Find the next return statement
        return_match = re.search(r"return (True|False)", failed_block)
        assert return_match, (
            "no return statement found after adapter_status check"
        )
        assert return_match.group(1) == "False", (
            "executor must return False when adapter reports failed, "
            "not True. Returning True marks the task as hecha even "
            "though the backend failed (the bug this fixes)."
        )
