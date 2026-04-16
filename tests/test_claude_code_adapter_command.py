"""Tests for ClaudeCodeAdapter._build_command (PR-31).

Regression guard: ``claude -p --output-format stream-json`` requires
``--verbose`` or the CLI exits immediately with:

    Error: When using --print, --output-format=stream-json requires --verbose

This was the reason the first-ever v0.2 routing pipeline run failed
in production (``running → failed`` in ~2s, backend_run_events error
message exactly matches the CLI error). The tier-3 fallback rescued
the task, but the v0.2 adapter was dead on arrival.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "niwa-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class TestBuildCommandIncludesVerbose:
    """Pin that _build_command produces a CLI invocation the Claude
    CLI actually accepts."""

    def test_verbose_flag_present(self):
        from backend_adapters.claude_code import ClaudeCodeAdapter

        cmd = ClaudeCodeAdapter._build_command(model="claude-sonnet-4-6")
        assert "--verbose" in cmd, (
            "_build_command must include --verbose when using "
            "--output-format stream-json with -p. Without it, "
            "the Claude CLI refuses to run (exit immediately with "
            "'--output-format=stream-json requires --verbose')."
        )

    def test_stream_json_present(self):
        from backend_adapters.claude_code import ClaudeCodeAdapter

        cmd = ClaudeCodeAdapter._build_command(model="claude-sonnet-4-6")
        assert "stream-json" in cmd, (
            "_build_command must use --output-format stream-json "
            "for structured event streaming from the CLI."
        )

    def test_print_flag_present(self):
        from backend_adapters.claude_code import ClaudeCodeAdapter

        cmd = ClaudeCodeAdapter._build_command(model="claude-sonnet-4-6")
        assert "-p" in cmd, (
            "_build_command must include -p (--print) for "
            "non-interactive execution."
        )

    def test_no_dangerously_skip_permissions(self):
        """SPEC §8: never include --dangerously-skip-permissions."""
        from backend_adapters.claude_code import ClaudeCodeAdapter

        cmd = ClaudeCodeAdapter._build_command(model="claude-sonnet-4-6")
        assert "--dangerously-skip-permissions" not in cmd

    def test_model_included_when_specified(self):
        from backend_adapters.claude_code import ClaudeCodeAdapter

        cmd = ClaudeCodeAdapter._build_command(model="claude-opus-4-6")
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "claude-opus-4-6"

    def test_resume_session_id_included(self):
        from backend_adapters.claude_code import ClaudeCodeAdapter

        cmd = ClaudeCodeAdapter._build_command(
            model="claude-sonnet-4-6",
            resume_session_id="sess-abc123",
        )
        idx = cmd.index("--resume")
        assert cmd[idx + 1] == "sess-abc123"
