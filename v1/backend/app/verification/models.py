"""Verification result dataclass (PR-V1-11a)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VerificationResult:
    """Immutable outcome of ``verify_run``; ``evidence`` is JSON-serialisable."""

    passed: bool
    outcome: str  # "verified" | "verification_failed"
    error_code: str | None
    evidence: dict[str, Any]


__all__ = ["VerificationResult"]
