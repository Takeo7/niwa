"""Verification result dataclass (PR-V1-11a)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VerificationResult:
    """Immutable outcome of ``verify_run``; ``evidence`` is JSON-serialisable.

    ``pending_question`` is populated only when ``outcome == "needs_input"``
    (PR-V1-19): the stream ended on an unanswered assistant question and
    the executor parks the task in ``waiting_input`` instead of failing it.
    Defaults to ``None`` so existing call sites stay source-compatible.
    """

    passed: bool
    outcome: str  # "verified" | "verification_failed" | "needs_input"
    error_code: str | None
    evidence: dict[str, Any]
    pending_question: str | None = None


__all__ = ["VerificationResult"]
