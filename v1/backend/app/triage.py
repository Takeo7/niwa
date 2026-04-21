"""Triage module — one LLM call to decide execute vs split (PR-V1-12a).

Public surface: ``TriageDecision`` (frozen dataclass) and
``TriageError``. The ``triage_task`` function and its private helpers
are added in the next commit so this file compiles incrementally.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TriageDecision:
    """Parsed verdict. ``kind`` in {"execute","split"}; ``subtasks`` is
    empty iff ``kind=="execute"``. ``raw_output`` is the last event text,
    kept for debug logs only."""

    kind: str
    subtasks: list[str]
    rationale: str
    raw_output: str


class TriageError(Exception):
    """Raised when triage cannot produce a valid decision."""


__all__ = ["TriageDecision", "TriageError"]
