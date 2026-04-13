"""Claude Code backend adapter — PR-03 Niwa v0.2.

Declares the static capabilities of Claude Code.  All execution methods
(``start``, ``resume``, ``cancel``, ``heartbeat``, ``collect_artifacts``,
``parse_usage_signals``) are stubs that raise ``NotImplementedError`` —
the real implementation arrives in PR-04.

Resource-budget fields (``estimated_resource_cost``, ``cost_confidence``,
``quota_risk``, ``latency_tier``) default to unknowns here.  PR-06 will
populate them with deterministic routing logic.
"""

from typing import Any

from backend_adapters.base import BackendAdapter


class ClaudeCodeAdapter(BackendAdapter):
    """Adapter for the Claude Code CLI backend."""

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

    def start(self, task: dict, run: dict, profile: dict,
              capability_profile: dict) -> dict:
        raise NotImplementedError(
            "ClaudeCodeAdapter.start() implementation is in PR-04."
        )

    def resume(self, task: dict, prior_run: dict, new_run: dict,
               profile: dict, capability_profile: dict) -> dict:
        raise NotImplementedError(
            "ClaudeCodeAdapter.resume() implementation is in PR-04."
        )

    def cancel(self, run: dict) -> dict:
        raise NotImplementedError(
            "ClaudeCodeAdapter.cancel() implementation is in PR-04."
        )

    def heartbeat(self, run: dict) -> dict:
        raise NotImplementedError(
            "ClaudeCodeAdapter.heartbeat() implementation is in PR-04."
        )

    def collect_artifacts(self, run: dict) -> list[dict]:
        raise NotImplementedError(
            "ClaudeCodeAdapter.collect_artifacts() implementation is in PR-04."
        )

    def parse_usage_signals(self, raw_output: str) -> dict:
        raise NotImplementedError(
            "ClaudeCodeAdapter.parse_usage_signals() implementation is in PR-04."
        )
