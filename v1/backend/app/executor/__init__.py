"""Niwa v1 executor package.

The executor is the process that drains the ``tasks`` table: it picks up
``queued`` rows, transitions them to ``running``, creates the associated
``Run``, streams events, and finally marks the task ``done`` (or ``failed``).

PR-V1-05 lands only the skeleton plus an *echo* implementation — no Claude
CLI adapter, no git branch, no verification. The real adapter replaces
``run_echo`` in Semana 2.

This package exposes two surfaces:

* ``core`` — pure-function pipeline usable from tests and from one-shot CLI
  runs (``python -m app.executor --once``).
* ``runner`` — the polling loop entrypoint with structured logging and a
  per-iteration ``session_scope``.
"""

from __future__ import annotations

from .core import claim_next_task, process_pending, run_echo
from .runner import run_forever

__all__ = [
    "claim_next_task",
    "process_pending",
    "run_echo",
    "run_forever",
]
