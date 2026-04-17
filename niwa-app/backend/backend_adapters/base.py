"""Abstract base class for backend adapters — PR-03 Niwa v0.2.

Every backend (Claude Code, Codex, future additions) must subclass
``BackendAdapter`` and implement all abstract methods.

PR-03 defines the interface and static capabilities.  Concrete
implementations of ``start``, ``resume``, ``cancel``, ``heartbeat``,
``collect_artifacts``, and ``parse_usage_signals`` arrive in later PRs
(PR-04 for Claude Code, PR-07 for Codex).
"""

from abc import ABC, abstractmethod
from typing import Any


class BackendAdapter(ABC):
    """Common interface that every execution backend must implement."""

    @abstractmethod
    def capabilities(self) -> dict[str, Any]:
        """Return the static capability declaration for this backend.

        Must include at least:
          - resume_modes:  list[str]
          - fs_modes:      list[str]
          - shell_modes:   list[str]
          - network_modes: list[str]
          - approval_modes: list[str]
          - secrets_modes: list[str]

        And the following resource-budget defaults (PR-06 fills with
        real logic):
          - estimated_resource_cost: str | None
          - cost_confidence:         str   ("unknown" until PR-06)
          - quota_risk:              str   ("unknown" until PR-06)
          - latency_tier:            str   ("unknown" until PR-06)
        """

    @abstractmethod
    def start(self, task: dict, run: dict, profile: dict,
              capability_profile: dict) -> dict:
        """Start a new execution run for *task* using *profile*.

        Returns a dict with at least ``session_handle`` and initial
        ``status``.
        """

    @abstractmethod
    def resume(self, task: dict, prior_run: dict, new_run: dict,
               profile: dict, capability_profile: dict) -> dict:
        """Resume execution from a previous run.

        *prior_run* is the run being resumed; *new_run* is the freshly
        created run record (``relation_type='resume'``).
        """

    @abstractmethod
    def cancel(self, run: dict) -> dict:
        """Cancel a running execution.

        Returns a dict with the final ``status`` and ``outcome``.
        """

    @abstractmethod
    def heartbeat(self, run: dict) -> dict:
        """Check liveness of a running execution.

        Returns a dict with ``alive`` (bool) and optional ``details``.
        """

    @abstractmethod
    def collect_artifacts(self, run: dict) -> list[dict]:
        """Collect output artifacts produced by a completed run.

        Returns a list of artifact dicts (``artifact_type``, ``path``,
        ``size_bytes``, ``sha256``).
        """

    @abstractmethod
    def parse_usage_signals(self, raw_output: str) -> dict:
        """Extract usage/cost signals from raw backend output.

        Returns a dict suitable for ``backend_runs.observed_usage_signals_json``.
        """


# ── Secret scrubbing (shared across adapters, PR-50) ──────────────────

import re as _re

# GitHub PAT formats that may appear in subprocess output after PR-50
# started injecting ``GITHUB_TOKEN`` into the env:
#
#   - classic PATs:       ``ghp_`` + 36 alphanumerics
#   - fine-grained PATs:  ``github_pat_`` + (22-char + ``_`` + 59-char block)
#   - legacy OAuth grants: ``gho_``, ``ghu_``, ``ghs_``, ``ghr_`` + 36 chars
#
# If a subprocess ever echoes one (a git error, a URL with embedded
# credentials, a ``curl -v`` log) it would otherwise land in
# ``backend_run_events.message`` and surface in the UI / DB dump.
_SECRET_PATTERNS = [
    _re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    _re.compile(r"github_pat_[A-Za-z0-9_]{40,}"),
    _re.compile(r"gh[osur]_[A-Za-z0-9]{20,}"),
]


def scrub_secrets(text: str) -> str:
    """Replace known-secret patterns with ``<redacted>``.

    Conservative: only matches well-defined GitHub PAT prefixes. Not a
    DLP tool — its job is to prevent our own injected credentials from
    leaking back through event logs, not to catch every possible
    secret.
    """
    if not text:
        return text
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub("<redacted>", out)
    return out
