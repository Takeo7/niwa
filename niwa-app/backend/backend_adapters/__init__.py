"""Backend adapters package — PR-03 Niwa v0.2.

Each adapter wraps a specific backend (Claude Code, Codex, etc.) behind
the common ``BackendAdapter`` interface defined in ``base.py``.
"""

from backend_adapters.base import BackendAdapter
from backend_adapters.claude_code import ClaudeCodeAdapter
from backend_adapters.codex import CodexAdapter

__all__ = ['BackendAdapter', 'ClaudeCodeAdapter', 'CodexAdapter']
