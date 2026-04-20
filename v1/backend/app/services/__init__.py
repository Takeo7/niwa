"""Service layer — pure functions over a SQLAlchemy ``Session``.

Grouped by resource. Each function commits its own unit of work so the API
layer can stay dependency-light. Raising ``DuplicateSlug`` / ``ProjectNotFound``
here keeps HTTP concerns out of the services themselves.
"""

from __future__ import annotations

from . import projects, run_events, runs, tasks

__all__ = ["projects", "run_events", "runs", "tasks"]
