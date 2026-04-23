"""Backend adapters for Niwa v1.

Only the Claude Code CLI adapter lives here — the SPEC rules out
multi-provider. Exposing ``AdapterEvent`` + ``ClaudeCodeAdapter`` plus the
two env-var helpers keeps the executor's imports flat.
"""

from __future__ import annotations

from .claude_code import (
    AdapterEvent,
    ClaudeCodeAdapter,
    resolve_cli_path,
    resolve_timeout,
)

__all__ = [
    "AdapterEvent",
    "ClaudeCodeAdapter",
    "resolve_cli_path",
    "resolve_timeout",
]
