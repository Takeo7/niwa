"""Review adapter — LLM reviews the diff after execution (Phase 2).

Environment override: ``NIWA_FAKE_REVIEW_JSON`` — when set, the adapter
returns this JSON without calling Claude (used in smoke/tests).

Diff is collected from ``git diff HEAD`` in the project cwd.  If the diff
exceeds ``_MAX_DIFF_CHARS`` it is truncated and ``truncated=True`` is noted.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..adapters.claude_code import ClaudeCodeAdapter, resolve_cli_path, resolve_timeout
from ..models import Task, TaskPlan, TaskReview


logger = logging.getLogger("niwa.reviewing")

_MAX_DIFF_CHARS = 20_000

_REVIEW_PROMPT_TMPL = """You are a code reviewer for Niwa.

Review the diff below against the plan and acceptance criteria.  Return ONLY
the JSON block below — no code, no prose outside the fence.

# Plan
Summary: {summary}
Acceptance criteria:
{criteria}

# Diff (may be truncated={truncated})
{diff}

# Response format (JSON only, in a ```json fence)
{{
  "decision": "approve" | "request_changes" | "needs_input" | "fail",
  "findings": [
    {{"severity": "blocker|major|minor", "file": "path", "message": "...", "recommendation": "..."}}
  ],
  "summary": "one sentence",
  "pending_question": null
}}
"""


@dataclass
class ReviewResult:
    decision: str  # approve | request_changes | needs_input | fail
    summary: str
    findings: list[dict] = field(default_factory=list)
    pending_question: str | None = None
    diff_summary: str = ""
    raw: str = ""
    error: str | None = None


def _collect_diff(cwd: str) -> tuple[str, bool]:
    """Return (diff_text, truncated).  Empty string if git unavailable."""
    try:
        stat = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=15,
        )
        diff = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=30,
        )
        stat_text = stat.stdout.strip()
        diff_text = diff.stdout
    except (subprocess.SubprocessError, OSError):
        return "", False

    combined = f"{stat_text}\n\n{diff_text}" if stat_text else diff_text
    if len(combined) > _MAX_DIFF_CHARS:
        return combined[:_MAX_DIFF_CHARS] + "\n... [truncated]", True
    return combined, False


def _extract_json(text: str) -> dict:
    import re
    fence = re.search(r"```json\s*([\s\S]+?)```", text)
    if fence:
        return json.loads(fence.group(1).strip())
    return json.loads(text.strip())


def _parse_result(raw: str) -> ReviewResult:
    try:
        data = _extract_json(raw)
    except (json.JSONDecodeError, ValueError) as e:
        return ReviewResult(
            decision="fail",
            summary=f"review JSON parse failed: {e}",
            raw=raw,
            error=str(e),
        )
    decision = data.get("decision", "fail")
    if decision not in ("approve", "request_changes", "needs_input", "fail"):
        decision = "fail"
    return ReviewResult(
        decision=decision,
        summary=data.get("summary", ""),
        findings=data.get("findings", []) or [],
        pending_question=data.get("pending_question"),
        raw=raw,
    )


class ReviewAdapter:
    """Generate a code review for a task's diff using Claude."""

    def review(
        self,
        cwd: str,
        task: Task,
        plan: TaskPlan | None,
    ) -> ReviewResult:
        # Env override for smoke/tests
        fake_json = os.environ.get("NIWA_FAKE_REVIEW_JSON")
        if fake_json:
            result = _parse_result(fake_json)
            diff, _ = _collect_diff(cwd)
            result.diff_summary = diff[:500]
            return result

        diff, truncated = _collect_diff(cwd)
        if not diff:
            return ReviewResult(
                decision="approve",
                summary="no diff to review; auto-approved",
                diff_summary="",
            )

        summary = (plan.summary or "") if plan else ""
        criteria_lines = []
        if plan and plan.acceptance_criteria_json:
            try:
                criteria_lines = json.loads(plan.acceptance_criteria_json)
            except (json.JSONDecodeError, ValueError):
                pass
        criteria = "\n".join(f"- {c}" for c in criteria_lines) or "(none)"

        prompt = _REVIEW_PROMPT_TMPL.format(
            summary=summary,
            criteria=criteria,
            diff=diff,
            truncated=truncated,
        )

        cli = resolve_cli_path()
        if not cli:
            return ReviewResult(
                decision="approve",
                summary="claude CLI not found; auto-approved",
                diff_summary=diff[:500],
            )

        adapter = ClaudeCodeAdapter(
            cli_path=cli,
            cwd=cwd,
            prompt=prompt,
            timeout=resolve_timeout(),
        )
        raw_parts: list[str] = []
        try:
            for event in adapter.iter_events():
                if event.kind == "assistant":
                    content = (event.payload.get("message") or {}).get("content", [])
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            raw_parts.append(block.get("text", ""))
            adapter.wait()
        finally:
            adapter.close()

        raw = "\n".join(raw_parts)
        result = _parse_result(raw)
        result.diff_summary = diff[:500]
        return result


def save_review(
    session: Session,
    task: Task,
    result: ReviewResult,
    *,
    iteration: int = 0,
) -> TaskReview:
    """Persist a ReviewResult as a TaskReview row."""
    review = TaskReview(
        task_id=task.id,
        iteration=iteration,
        diff_summary=result.diff_summary,
        findings_json=json.dumps(result.findings),
        decision=result.decision,
        pending_question=result.pending_question,
        raw_response_json=json.dumps({"raw": result.raw, "error": result.error}),
    )
    session.add(review)
    session.commit()
    return review
