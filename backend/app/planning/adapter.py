"""Planner adapter — asks Claude to produce a structured plan JSON.

Uses the same ClaudeCodeAdapter as triage/execution.  The prompt asks for
JSON only; the adapter validates it strictly.  On parse failure the plan is
saved with ``status='planning_failed'`` and ``raw_response_json`` for debug.

Environment override: ``NIWA_FAKE_PLAN_JSON`` — when set the adapter returns
this JSON string without calling the real CLI (used in smoke/tests).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..adapters.claude_code import ClaudeCodeAdapter, resolve_cli_path, resolve_timeout
from ..models import Project, Task, TaskPlan


logger = logging.getLogger("niwa.planning")

_PLANNER_KEYWORD = "planning agent for Niwa"

_PLAN_PROMPT_TMPL = """You are a planning agent for Niwa.

Analyse the task below and produce a plan for implementing it.  Do NOT write
any code or modify any files.  Return ONLY the JSON block below.

# Task
Title: {title}
Description: {description}
Project kind: {kind}
Project path: {local_path}

# Response format (JSON only, in a ```json fence)
{{
  "summary": "one sentence describing what will be done",
  "steps": ["step 1", "step 2"],
  "files_likely_touched": ["path/to/file"],
  "risks": ["risk 1"],
  "acceptance_criteria": ["criterion 1"],
  "needs_user_approval": false
}}
"""


@dataclass
class PlanningResult:
    success: bool
    summary: str | None
    steps: list[str]
    risks: list[str]
    acceptance_criteria: list[str]
    files_likely_touched: list[str]
    needs_user_approval: bool
    raw: str
    error: str | None = None


def _extract_json(text: str) -> dict:
    """Extract JSON from a ```json ... ``` fence or bare JSON."""
    import re
    fence = re.search(r"```json\s*([\s\S]+?)```", text)
    if fence:
        return json.loads(fence.group(1).strip())
    # Try bare JSON
    return json.loads(text.strip())


def _fake_plan_result(raw_json: str) -> PlanningResult:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        return PlanningResult(
            success=False, summary=None, steps=[], risks=[],
            acceptance_criteria=[], files_likely_touched=[],
            needs_user_approval=False, raw=raw_json,
            error=f"invalid NIWA_FAKE_PLAN_JSON: {e}",
        )
    return PlanningResult(
        success=True,
        summary=data.get("summary", ""),
        steps=data.get("steps", []),
        risks=data.get("risks", []),
        acceptance_criteria=data.get("acceptance_criteria", []),
        files_likely_touched=data.get("files_likely_touched", []),
        needs_user_approval=bool(data.get("needs_user_approval", False)),
        raw=raw_json,
    )


class PlanningAdapter:
    """Generate a plan for a task using the Claude CLI."""

    def generate(self, project: Project, task: Task) -> PlanningResult:
        # Env override for smoke/tests
        fake_json = os.environ.get("NIWA_FAKE_PLAN_JSON")
        if fake_json:
            return _fake_plan_result(fake_json)

        prompt = _PLAN_PROMPT_TMPL.format(
            title=task.title or "",
            description=task.description or "",
            kind=project.kind,
            local_path=project.local_path,
        )
        cli = resolve_cli_path()
        if not cli:
            return PlanningResult(
                success=False, summary=None, steps=[], risks=[],
                acceptance_criteria=[], files_likely_touched=[],
                needs_user_approval=False, raw="",
                error="claude CLI not found",
            )

        adapter = ClaudeCodeAdapter(
            cli_path=cli,
            cwd=project.local_path,
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
        try:
            data = _extract_json(raw)
        except (json.JSONDecodeError, ValueError) as e:
            return PlanningResult(
                success=False, summary=None, steps=[], risks=[],
                acceptance_criteria=[], files_likely_touched=[],
                needs_user_approval=False, raw=raw,
                error=f"plan JSON parse failed: {e}",
            )

        return PlanningResult(
            success=True,
            summary=data.get("summary", ""),
            steps=data.get("steps", []) or [],
            risks=data.get("risks", []) or [],
            acceptance_criteria=data.get("acceptance_criteria", []) or [],
            files_likely_touched=data.get("files_likely_touched", []) or [],
            needs_user_approval=bool(data.get("needs_user_approval", False)),
            raw=raw,
        )


def save_plan(session: Session, task: Task, result: PlanningResult) -> TaskPlan:
    """Persist a PlanningResult as a TaskPlan row."""
    plan = TaskPlan(
        task_id=task.id,
        status="planning_failed" if not result.success else "pending",
        summary=result.summary,
        steps_json=json.dumps(result.steps),
        risks_json=json.dumps(result.risks),
        acceptance_criteria_json=json.dumps(result.acceptance_criteria),
        needs_user_approval=result.needs_user_approval,
        raw_response_json=json.dumps({"raw": result.raw, "error": result.error}),
    )
    session.add(plan)
    session.commit()
    return plan
