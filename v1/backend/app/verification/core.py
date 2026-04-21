"""Verification orchestrator (PR-V1-11a).

Runs SPEC §5 evidence checks in order, short-circuiting on the first
failure. **11a scope:** E1 (exit code) + E2 (stream) are real; E3/E4/E5
are stubs that pass vacuously — evidence carries placeholder slots so
11b/11c only need to add logic, not structure.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..models import Project, Run, RunEvent, Task
from .models import VerificationResult
from .stream import check_stream_termination


_LIFECYCLE = {"started", "completed", "failed", "error"}


def _load_stream_events(session: Session, run_id: int) -> list[dict[str, Any]]:
    rows = (
        session.query(RunEvent)
        .filter(RunEvent.run_id == run_id)
        .order_by(RunEvent.id.asc())
        .all()
    )
    events: list[dict[str, Any]] = []
    for row in rows:
        if row.payload_json is None:
            events.append({"type": row.event_type})
            continue
        try:
            payload = json.loads(row.payload_json)
        except ValueError:
            continue
        if isinstance(payload, dict):
            payload.setdefault("type", row.event_type)
            events.append(payload)
    return events


def _e1_exit_code(adapter_outcome: str, exit_code: int | None) -> str | None:
    if adapter_outcome == "cli_ok" and exit_code == 0:
        return None
    if adapter_outcome in ("cli_ok", "cli_nonzero_exit"):
        return "exit_nonzero"
    return "adapter_failure"


def verify_run(
    session: Session,
    run: Run,
    task: Task,
    project: Project | None,
    cwd: str,
    *,
    adapter_outcome: str,
    exit_code: int | None,
) -> VerificationResult:
    """Collect evidence, decide verified vs verification_failed.

    ``adapter_outcome`` + ``exit_code`` are not persisted on ``run`` yet
    (``_finalize`` writes them) so they come in as explicit kwargs.
    """

    # Stable evidence shape: E1+E2 are real; E3/E4/E5 slots are
    # placeholders that 11b/11c will populate with real values.
    evidence: dict[str, Any] = {
        "adapter_outcome": adapter_outcome,
        "exit_code": exit_code,
        "tests_ran": False,
        "git_available": None,
        "artifact_count": None,
        "tool_use_paths_outside": [],
    }

    e1 = _e1_exit_code(adapter_outcome, exit_code)
    evidence["exit_ok"] = e1 is None
    if e1 is not None:
        evidence["error_code"] = e1
        return VerificationResult(False, "verification_failed", e1, evidence)

    stream_events = _load_stream_events(session, run.id)
    evidence["significant_event_count"] = sum(
        1 for e in stream_events if e.get("type") not in _LIFECYCLE
    )
    e2 = check_stream_termination(stream_events)
    evidence["stream_terminated_cleanly"] = e2 is None
    if e2 is not None:
        evidence["error_code"] = e2
        return VerificationResult(False, "verification_failed", e2, evidence)

    # E3/E4/E5 — stubs pass vacuously for 11a.
    _ = project, task, cwd
    return VerificationResult(True, "verified", None, evidence)


__all__ = ["verify_run"]
