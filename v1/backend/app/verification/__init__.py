"""Public surface of the verification package (PR-V1-11a)."""

from __future__ import annotations

from .core import verify_run
from .models import VerificationResult

__all__ = ["VerificationResult", "verify_run"]
