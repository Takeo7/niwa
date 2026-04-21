"""Verification orchestrator (PR-V1-11a → PR-V1-11c).

Runs SPEC §5 evidence checks in order, short-circuiting on the first
failure. E1 (exit code) + E2 (stream) + E3 (artifact presence in cwd) +
E4 (no writes outside cwd) + E5 (project tests) are all real now.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..models import Project, Run, RunEvent, Task
from .artifacts import check_artifacts_in_cwd, check_no_artifacts_outside_cwd
from .models import VerificationResult
from .stream import check_stream_termination
from .tests_runner import detect_test_runner, run_project_tests


# Hard-coded for MVP; ``NIWA_VERIFY_TESTS_TIMEOUT`` env override is a
# follow-up per the 11c brief.
_TESTS_TIMEOUT_S = 300


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

    # Stable evidence shape: E1+E2+E3+E4 are real; only E5 is a stub.
    evidence: dict[str, Any] = {
        "adapter_outcome": adapter_outcome,
        "exit_code": exit_code,
        "tests_ran": False,
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

    cwd_path = Path(cwd)
    if not check_artifacts_in_cwd(cwd_path, evidence):
        code = evidence.get("error_code", "no_artifacts")
        return VerificationResult(False, "verification_failed", code, evidence)

    if not check_no_artifacts_outside_cwd(session, run, cwd_path, evidence):
        code = evidence.get("error_code", "artifacts_outside_cwd")
        return VerificationResult(False, "verification_failed", code, evidence)

    # E5 — project tests. Detection returns None either because the
    # project is ad-hoc ``kind=script`` (skip by design) or no runner
    # matched in cwd. Both are legitimate passes; the reason-code lets
    # the operator tell them apart in ``verification_json``.
    _ = task
    choice = detect_test_runner(cwd_path, project)
    if choice is None:
        evidence["tests_ran"] = False
        project_kind = getattr(project, "kind", None)
        evidence["test_reason"] = (
            "kind_script" if project_kind == "script" else "no_test_script_detected"
        )
        return VerificationResult(True, "verified", None, evidence)

    result = run_project_tests(choice, timeout=_TESTS_TIMEOUT_S)
    evidence["tests_ran"] = True
    evidence["test_tool"] = choice.tool
    evidence["test_exit_code"] = result.exit_code
    evidence["test_duration_s"] = result.duration_s
    evidence["test_output_tail"] = result.output_tail
    if result.timed_out:
        evidence["error_code"] = "tests_timeout"
        return VerificationResult(
            False, "verification_failed", "tests_timeout", evidence
        )
    # ``exit_code is None`` with ``timed_out=False`` means the runner
    # binary itself was missing/unlaunchable (FileNotFoundError et al.
    # swallowed by ``run_project_tests``). Report it distinctly so the
    # operator knows to install the toolchain, not to fix the tests.
    if result.exit_code is None and not result.timed_out:
        evidence["error_code"] = "tests_runner_missing"
        return VerificationResult(
            False, "verification_failed", "tests_runner_missing", evidence
        )
    if not result.passed:
        evidence["error_code"] = "tests_failed"
        return VerificationResult(
            False, "verification_failed", "tests_failed", evidence
        )
    return VerificationResult(True, "verified", None, evidence)


__all__ = ["verify_run"]
