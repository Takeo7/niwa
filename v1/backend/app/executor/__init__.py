"""Niwa v1 executor package.

The executor is the process that drains the ``tasks`` table: it picks up
``queued`` rows, transitions them to ``running``, spawns the Claude Code
CLI via the adapter, streams events into ``run_events``, and finally marks
the task ``done`` or ``failed``.

PR-V1-07 replaces the echo implementation from PR-V1-05 with the real
adapter. The pipeline shape (``claim_next_task`` → ``run_*`` → event
writes) is unchanged; only the innards of the per-task function differ.

This package exposes two surfaces:

* ``core`` — pure-function pipeline usable from tests and from one-shot CLI
  runs (``python -m app.executor --once``).
* ``runner`` — the polling loop entrypoint with structured logging and a
  per-iteration ``session_scope``.
"""

from __future__ import annotations

from .core import claim_next_task, process_pending, run_adapter
from .runner import run_forever

__all__ = [
    "claim_next_task",
    "process_pending",
    "run_adapter",
    "run_forever",
]
