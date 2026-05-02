"""Post-verification review service with deterministic and Claude Code modes."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import load_settings
from app.pipeline.planner import _call_claude_json, _required_str, _str_list

_DIFF_CONTEXT_LIMIT = 20_000
_GIT_TIMEOUT_SECONDS = 5


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
    diff_context = _diff_context(getattr(run, "artifact_root", None))
    return f"""You are Niwa's reviewer. Return JSON only in a ```json fence`.
Task: {task.title}
Run id: {run.id}
Verification passed: {verification.passed}
Evidence: {evidence}
Git change context:
{diff_context}

Schema:
{{"decision":"approved|request_changes", "summary":"...", "findings":["..."]}}
"""


def _diff_context(artifact_root: str | None) -> str:
    if not artifact_root:
        return "unavailable: run has no artifact_root"
    root = Path(artifact_root)
    if not root.exists():
        return f"unavailable: artifact_root does not exist: {root}"

    sections = [
        ("git status --short", _git_output(root, ["status", "--short"])),
        ("git diff --stat", _git_output(root, ["diff", "--stat"])),
        (
            "git diff --patch --no-color --no-ext-diff",
            _git_output(root, ["diff", "--patch", "--no-color", "--no-ext-diff"]),
        ),
    ]
    text = "\n\n".join(f"{title}:\n{body or '(none)'}" for title, body in sections)
    if len(text) <= _DIFF_CONTEXT_LIMIT:
        return text
    return (
        text[:_DIFF_CONTEXT_LIMIT]
        + f"\n\n[diff context truncated at {_DIFF_CONTEXT_LIMIT} characters]"
    )


def _git_output(root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return "unavailable: git binary not found"
    except subprocess.TimeoutExpired:
        return f"unavailable: git command timed out after {_GIT_TIMEOUT_SECONDS}s"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        message = detail[0] if detail else f"exit {result.returncode}"
        return f"unavailable: {message}"
    return result.stdout.strip()
