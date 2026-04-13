"""Codex (OpenAI) backend adapter — PR-03 Niwa v0.2.

Declares the static capabilities of the Codex CLI.  All execution
methods are stubs that raise ``NotImplementedError`` — the real
implementation arrives in PR-07.

Codex operates in a sandboxed environment: no network access, restricted
filesystem, and a single sandbox shell mode.

Resource-budget fields default to unknowns here.  PR-06 will populate
them with deterministic routing logic.
"""

from typing import Any

from backend_adapters.base import BackendAdapter


class CodexAdapter(BackendAdapter):
    """Adapter for the Codex CLI backend."""

    def capabilities(self) -> dict[str, Any]:
        return {
            "resume_modes": ["new_session"],
            "fs_modes": ["repo_only", "readonly"],
            "shell_modes": ["sandboxed"],
            "network_modes": ["off"],
            "approval_modes": ["always", "never"],
            "secrets_modes": ["env_inject", "none"],
            # Resource-budget defaults — PR-06 fills with real logic.
            "estimated_resource_cost": None,
            "cost_confidence": "unknown",
            "quota_risk": "unknown",
            "latency_tier": "unknown",
        }

    def start(self, task: dict, run: dict, profile: dict,
              capability_profile: dict) -> dict:
        raise NotImplementedError(
            "CodexAdapter.start() implementation is in PR-07."
        )

    def resume(self, task: dict, prior_run: dict, new_run: dict,
               profile: dict, capability_profile: dict) -> dict:
        raise NotImplementedError(
            "CodexAdapter.resume() implementation is in PR-07."
        )

    def cancel(self, run: dict) -> dict:
        raise NotImplementedError(
            "CodexAdapter.cancel() implementation is in PR-07."
        )

    def heartbeat(self, run: dict) -> dict:
        raise NotImplementedError(
            "CodexAdapter.heartbeat() implementation is in PR-07."
        )

    def collect_artifacts(self, run: dict) -> list[dict]:
        raise NotImplementedError(
            "CodexAdapter.collect_artifacts() implementation is in PR-07."
        )

    def parse_usage_signals(self, raw_output: str) -> dict:
        raise NotImplementedError(
            "CodexAdapter.parse_usage_signals() implementation is in PR-07."
        )
