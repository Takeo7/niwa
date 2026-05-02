"""Post-verification review service with deterministic and Claude Code modes."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from app.config import load_settings
from app.pipeline.planner import _call_claude_json, _required_str, _str_list


@dataclass(frozen=True)
class ReviewResult:
    decision: str
    summary: str
    findings: list[str]
    reviewer: str
    raw_json: str


def review_task(task: Any, run: Any, verification: Any, *, iteration: int) -> ReviewResult:
    mode = load_settings().pipeline_reviewer_mode
    if mode == "claude-code":
        try:
            return _claude_review(task, run, verification)
        except Exception:
            return _fake_review(verification, iteration=iteration)
    return _fake_review(verification, iteration=iteration)


def _fake_review(verification: Any, *, iteration: int) -> ReviewResult:
    decision = _forced_decision(iteration)
    if decision is None:
        decision = "approved" if verification.passed else "request_changes"
    findings = [] if verification.passed else [
        f"Verification did not pass: {verification.error_code or verification.outcome}"
    ]
    payload = {
        "decision": decision,
        "summary": (
            "Review requested changes before finalize."
            if decision == "request_changes" and verification.passed
            else
            "Verification passed; finalize is allowed."
            if verification.passed
            else "Verification failed; changes are required before finalize."
        ),
        "findings": findings,
    }
    return ReviewResult(
        decision=decision,
        summary=payload["summary"],
        findings=findings,
        reviewer="fake-json",
        raw_json=json.dumps(payload, sort_keys=True),
    )


def _claude_review(task: Any, run: Any, verification: Any) -> ReviewResult:
    parsed = _call_claude_json(_review_prompt(task, run, verification), run.artifact_root)
    decision = parsed.get("decision")
    if decision not in {"approved", "request_changes"}:
        raise ValueError("decision must be approved or request_changes")
    findings = _str_list(parsed, "findings")
    return ReviewResult(
        decision=decision,
        summary=_required_str(parsed, "summary"),
        findings=findings,
        reviewer="claude-code",
        raw_json=json.dumps(parsed, sort_keys=True),
    )


def _forced_decision(iteration: int) -> str | None:
    raw = os.environ.get("NIWA_FAKE_REVIEW_DECISIONS", "").strip()
    decisions = [item.strip() for item in raw.split(",") if item.strip()]
    if iteration > len(decisions):
        return None
    decision = decisions[iteration - 1]
    return decision if decision in {"approved", "request_changes"} else None


def _review_prompt(task: Any, run: Any, verification: Any) -> str:
    evidence = json.dumps(verification.evidence, sort_keys=True)
    return f"""You are Niwa's reviewer. Return JSON only in a ```json fence`.
Task: {task.title}
Run id: {run.id}
Verification passed: {verification.passed}
Evidence: {evidence}

Schema:
{{"decision":"approved|request_changes", "summary":"...", "findings":["..."]}}
"""
