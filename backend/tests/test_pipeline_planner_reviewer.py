"""Tests for configurable planner/reviewer pipeline services."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.pipeline import plan_task, review_task
from app.pipeline.reviewer import _review_prompt


FAKE_CLI = (Path(__file__).parent / "fixtures" / "fake_claude_cli.py").resolve()


@pytest.fixture(autouse=True)
def _fake_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    st = os.stat(FAKE_CLI)
    os.chmod(FAKE_CLI, st.st_mode | 0o111)
    monkeypatch.setenv("NIWA_CLAUDE_CLI", str(FAKE_CLI))


def _script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    event = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": payload}]},
    }
    path = tmp_path / "script.jsonl"
    path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_CLAUDE_SCRIPT", str(path))


def test_claude_planner_uses_valid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NIWA_PIPELINE_PLANNER_MODE", "claude-code")
    _script(
        tmp_path,
        monkeypatch,
        """```json
{"summary":"Plan it","steps":["Do it"],"risks":[],"acceptance_criteria":["Done"]}
```""",
    )

    result = plan_task(
        SimpleNamespace(title="Ship", description=""),
        SimpleNamespace(kind="script", local_path=str(tmp_path)),
    )

    assert result.planner == "claude-code"
    assert result.summary == "Plan it"
    assert result.steps == ["Do it"]


def test_claude_planner_invalid_json_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NIWA_PIPELINE_PLANNER_MODE", "claude-code")
    _script(tmp_path, monkeypatch, "not json")

    result = plan_task(
        SimpleNamespace(title="Fallback", description=""),
        SimpleNamespace(kind="script", local_path=str(tmp_path)),
    )

    assert result.planner == "fake-json"
    assert result.summary == "Execute task: Fallback"


def test_claude_reviewer_accepts_request_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NIWA_PIPELINE_REVIEWER_MODE", "claude-code")
    _script(
        tmp_path,
        monkeypatch,
        """```json
{"decision":"request_changes","summary":"Needs work","findings":["Missing test"]}
```""",
    )

    result = review_task(
        SimpleNamespace(title="Review me"),
        SimpleNamespace(id=7, artifact_root=str(tmp_path)),
        SimpleNamespace(passed=True, evidence={"e1": "ok"}),
        iteration=1,
    )

    assert result.reviewer == "claude-code"
    assert result.decision == "request_changes"
    assert result.findings == ["Missing test"]


def test_reviewer_prompt_includes_git_diff_context(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    path = tmp_path / "story.txt"
    path.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "story.txt"], cwd=tmp_path, check=True)
    path.write_text("after\n", encoding="utf-8")

    prompt = _review_prompt(
        SimpleNamespace(title="Review diff"),
        SimpleNamespace(id=11, artifact_root=str(tmp_path)),
        SimpleNamespace(passed=True, evidence={"e1": "ok"}),
    )

    assert "Git change context:" in prompt
    assert "git status --short" in prompt
    assert "story.txt" in prompt
    assert "+after" in prompt


def test_reviewer_prompt_handles_missing_git_repo(tmp_path: Path) -> None:
    prompt = _review_prompt(
        SimpleNamespace(title="No repo"),
        SimpleNamespace(id=12, artifact_root=str(tmp_path)),
        SimpleNamespace(passed=True, evidence={"e1": "ok"}),
    )

    assert "Git change context:" in prompt
    assert "unavailable:" in prompt


def test_claude_reviewer_invalid_json_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NIWA_PIPELINE_REVIEWER_MODE", "claude-code")
    _script(tmp_path, monkeypatch, "not json")

    result = review_task(
        SimpleNamespace(title="Fallback review"),
        SimpleNamespace(id=13, artifact_root=str(tmp_path)),
        SimpleNamespace(passed=True, evidence={"e1": "ok"}),
        iteration=1,
    )

    assert result.reviewer == "fake-json"
    assert result.decision == "approved"
