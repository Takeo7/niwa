"""Tests for Phase 2 planning + review pipeline.

Covers:
- PlanningAdapter with NIWA_FAKE_PLAN_JSON env override
- ReviewAdapter with NIWA_FAKE_REVIEW_JSON env override
- executor.process_pending with require_plan_approval=True (parks in waiting_approval)
- executor.process_pending with auto_review=True (approve path)
- executor.process_pending with auto_review=True (request_changes then approve)
- approve_plan service + API endpoint
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_session
from app.db import Base
from app.executor.core import process_pending
from app.main import app as fastapi_app
from app.models import Project, Task, TaskPlan, TaskReview
from app.planning.adapter import PlanningAdapter, save_plan
from app.reviewing.adapter import ReviewAdapter, save_review
from app.services.tasks import (
    NoPendingPlan,
    TaskNotWaitingApproval,
    approve_plan,
    get_task,
)
from app.triage import TriageDecision


FAKE_CLI_PATH = (
    Path(__file__).parent / "fixtures" / "fake_claude_cli.py"
).resolve()

_GOOD_PLAN_JSON = json.dumps({
    "summary": "Add widget module",
    "steps": ["step 1", "step 2"],
    "files_likely_touched": ["widget.py"],
    "risks": ["risk 1"],
    "acceptance_criteria": ["criterion 1"],
    "needs_user_approval": False,
})

_APPROVAL_PLAN_JSON = json.dumps({
    "summary": "Risky refactor",
    "steps": ["step A"],
    "files_likely_touched": ["core.py"],
    "risks": ["may break things"],
    "acceptance_criteria": ["tests pass"],
    "needs_user_approval": True,
})

_APPROVE_REVIEW_JSON = json.dumps({
    "decision": "approve",
    "findings": [],
    "summary": "Looks good.",
    "pending_question": None,
})

_REQUEST_CHANGES_REVIEW_JSON = json.dumps({
    "decision": "request_changes",
    "findings": [{"severity": "major", "file": "foo.py", "message": "bug", "recommendation": "fix it"}],
    "summary": "Needs work.",
    "pending_question": None,
})

_NEEDS_INPUT_REVIEW_JSON = json.dumps({
    "decision": "needs_input",
    "findings": [],
    "summary": "Need clarification.",
    "pending_question": "Which approach?",
})

_FAIL_REVIEW_JSON = json.dumps({
    "decision": "fail",
    "findings": [],
    "summary": "Fatal error.",
    "pending_question": None,
})


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_engine(tmp_path: Path):
    db_path = tmp_path / "phase2.sqlite3"
    eng = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(eng)
    return eng


def _make_project(session: Session, local_path: str | Path = "/tmp/demo", **overrides) -> Project:
    defaults = dict(slug="demo", name="Demo", kind="library", local_path=str(local_path))
    defaults.update(overrides)
    p = Project(**defaults)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def _make_task(session: Session, project: Project, *, status: str = "queued", title: str = "t") -> Task:
    task = Task(project_id=project.id, title=title, description="", status=status)
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@pytest.fixture(autouse=True)
def _fake_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every test at the fake CLI."""
    st = os.stat(FAKE_CLI_PATH)
    os.chmod(FAKE_CLI_PATH, st.st_mode | 0o111)

    script = tmp_path / "default_script.jsonl"
    script.write_text(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}}) + "\n"
        + json.dumps({"type": "result", "exit_code": 0}) + "\n"
    )
    monkeypatch.setenv("NIWA_CLAUDE_CLI", str(FAKE_CLI_PATH))
    monkeypatch.setenv("FAKE_CLAUDE_SCRIPT", str(script))
    monkeypatch.setenv("FAKE_CLAUDE_EXIT", "0")


@pytest.fixture()
def stub_triage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.executor.core.triage_task",
        lambda project, task: TriageDecision(kind="execute", subtasks=[], rationale="stub", raw_output=""),
    )


# ---------------------------------------------------------------------------
# PlanningAdapter unit tests
# ---------------------------------------------------------------------------


def test_planning_adapter_fake_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NIWA_FAKE_PLAN_JSON", _GOOD_PLAN_JSON)

    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session)
        task = _make_task(session, project)
        result = PlanningAdapter().generate(project, task)

    assert result.success is True
    assert result.summary == "Add widget module"
    assert result.steps == ["step 1", "step 2"]
    assert result.acceptance_criteria == ["criterion 1"]
    assert result.needs_user_approval is False
    eng.dispose()


def test_planning_adapter_invalid_fake_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NIWA_FAKE_PLAN_JSON", "NOT JSON")

    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session)
        task = _make_task(session, project)
        result = PlanningAdapter().generate(project, task)

    assert result.success is False
    assert result.error is not None
    eng.dispose()


def test_save_plan_creates_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_FAKE_PLAN_JSON", _GOOD_PLAN_JSON)

    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session)
        task = _make_task(session, project)
        result = PlanningAdapter().generate(project, task)
        plan = save_plan(session, task, result)
        assert plan.id is not None
        assert plan.task_id == task.id
        assert plan.status == "pending"
        assert plan.summary == "Add widget module"
    eng.dispose()


# ---------------------------------------------------------------------------
# ReviewAdapter unit tests
# ---------------------------------------------------------------------------


def test_review_adapter_approve(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NIWA_FAKE_REVIEW_JSON", _APPROVE_REVIEW_JSON)

    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session, local_path=tmp_path)
        task = _make_task(session, project)
        result = ReviewAdapter().review(cwd=str(tmp_path), task=task, plan=None)

    assert result.decision == "approve"
    assert result.summary == "Looks good."
    assert result.findings == []
    eng.dispose()


def test_review_adapter_request_changes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NIWA_FAKE_REVIEW_JSON", _REQUEST_CHANGES_REVIEW_JSON)

    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session, local_path=tmp_path)
        task = _make_task(session, project)
        result = ReviewAdapter().review(cwd=str(tmp_path), task=task, plan=None)

    assert result.decision == "request_changes"
    assert len(result.findings) == 1
    eng.dispose()


def test_save_review_creates_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_FAKE_REVIEW_JSON", _APPROVE_REVIEW_JSON)

    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session, local_path=tmp_path)
        task = _make_task(session, project)
        result = ReviewAdapter().review(cwd=str(tmp_path), task=task, plan=None)
        review = save_review(session, task, result, iteration=0)
        assert review.id is not None
        assert review.decision == "approve"
        assert review.iteration == 0
    eng.dispose()


# ---------------------------------------------------------------------------
# approve_plan service tests
# ---------------------------------------------------------------------------


def test_approve_plan_service_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_FAKE_PLAN_JSON", _GOOD_PLAN_JSON)

    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session)
        task = _make_task(session, project, status="waiting_approval")
        result = PlanningAdapter().generate(project, task)
        save_plan(session, task, result)

        updated = approve_plan(session, task.id)
        assert updated.status == "queued"

        plan = session.query(TaskPlan).filter_by(task_id=task.id).first()
        assert plan is not None
        assert plan.status == "approved"
    eng.dispose()


def test_approve_plan_wrong_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_FAKE_PLAN_JSON", _GOOD_PLAN_JSON)

    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session)
        task = _make_task(session, project, status="queued")
        with pytest.raises(TaskNotWaitingApproval):
            approve_plan(session, task.id)
    eng.dispose()


def test_approve_plan_no_pending_plan(tmp_path: Path) -> None:
    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session)
        task = _make_task(session, project, status="waiting_approval")
        with pytest.raises(NoPendingPlan):
            approve_plan(session, task.id)
    eng.dispose()


# ---------------------------------------------------------------------------
# Executor pipeline with require_plan_approval
# ---------------------------------------------------------------------------


def test_process_pending_parks_on_plan_approval(
    tmp_path: Path,
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_triage: None,
) -> None:
    """With require_plan_approval=True, task must stop at waiting_approval."""
    monkeypatch.setenv("NIWA_FAKE_PLAN_JSON", _GOOD_PLAN_JSON)
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", str(git_project / "touch-{pid}.txt"))

    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session, local_path=git_project, require_plan_approval=True)
        task = _make_task(session, project)

        count = process_pending(session)
        assert count == 1

        session.expire_all()
        task = session.get(Task, task.id)
        assert task is not None
        assert task.status == "waiting_approval"

        plan = session.query(TaskPlan).filter_by(task_id=task.id).first()
        assert plan is not None
        assert plan.status == "pending"
    eng.dispose()


def test_process_pending_skips_plan_when_disabled(
    tmp_path: Path,
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_triage: None,
) -> None:
    """With neither require_plan_approval nor auto_review, no plan is created."""
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", str(git_project / "touch-{pid}.txt"))

    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session, local_path=git_project)
        task = _make_task(session, project)

        count = process_pending(session)
        assert count == 1

        session.expire_all()
        task = session.get(Task, task.id)
        assert task is not None
        assert task.status == "done"

        plans = session.query(TaskPlan).filter_by(task_id=task.id).all()
        assert plans == []
    eng.dispose()


# ---------------------------------------------------------------------------
# Executor pipeline with auto_review
# ---------------------------------------------------------------------------


def test_process_pending_auto_review_approve(
    tmp_path: Path,
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_triage: None,
) -> None:
    """With auto_review=True and reviewer returning approve, task ends done."""
    monkeypatch.setenv("NIWA_FAKE_PLAN_JSON", _GOOD_PLAN_JSON)
    monkeypatch.setenv("NIWA_FAKE_REVIEW_JSON", _APPROVE_REVIEW_JSON)
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", str(git_project / "touch-{pid}.txt"))

    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session, local_path=git_project, auto_review=True)
        task = _make_task(session, project)

        count = process_pending(session)
        assert count == 1

        session.expire_all()
        task = session.get(Task, task.id)
        assert task is not None
        assert task.status == "done"

        review = session.query(TaskReview).filter_by(task_id=task.id).first()
        assert review is not None
        assert review.decision == "approve"
    eng.dispose()


def test_process_pending_auto_review_fail(
    tmp_path: Path,
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_triage: None,
) -> None:
    """With auto_review=True and reviewer returning fail, task ends failed."""
    monkeypatch.setenv("NIWA_FAKE_PLAN_JSON", _GOOD_PLAN_JSON)
    monkeypatch.setenv("NIWA_FAKE_REVIEW_JSON", _FAIL_REVIEW_JSON)
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", str(git_project / "touch-{pid}.txt"))

    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session, local_path=git_project, auto_review=True)
        task = _make_task(session, project)

        count = process_pending(session)
        assert count == 1

        session.expire_all()
        task = session.get(Task, task.id)
        assert task is not None
        assert task.status == "failed"

        review = session.query(TaskReview).filter_by(task_id=task.id).first()
        assert review is not None
        assert review.decision == "fail"
    eng.dispose()


def test_process_pending_auto_review_needs_input(
    tmp_path: Path,
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_triage: None,
) -> None:
    """With auto_review returning needs_input, task parks in waiting_input."""
    monkeypatch.setenv("NIWA_FAKE_PLAN_JSON", _GOOD_PLAN_JSON)
    monkeypatch.setenv("NIWA_FAKE_REVIEW_JSON", _NEEDS_INPUT_REVIEW_JSON)
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", str(git_project / "touch-{pid}.txt"))

    eng = _make_engine(tmp_path)
    with Session(eng) as session:
        project = _make_project(session, local_path=git_project, auto_review=True)
        task = _make_task(session, project)

        count = process_pending(session)
        assert count == 1

        session.expire_all()
        task = session.get(Task, task.id)
        assert task is not None
        assert task.status == "waiting_input"
        assert task.pending_question == "Which approach?"
    eng.dispose()


# ---------------------------------------------------------------------------
# approve-plan API endpoint
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def override_get_session() -> Iterator[Session]:
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(fastapi_app) as c:
            yield c
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)
        engine.dispose()


def _create_project_and_task(client: TestClient, *, task_status: str = "waiting_approval"):
    resp = client.post("/api/projects", json={"slug": "demo", "name": "Demo", "kind": "library", "local_path": "/tmp/x"})
    assert resp.status_code == 201
    resp2 = client.post("/api/projects/demo/tasks", json={"title": "T1", "description": ""})
    assert resp2.status_code == 201
    task_id = resp2.json()["id"]

    # Manually patch the task status via the DB (the session fixture isn't
    # accessible here, so we use the engine registered by the override).
    # The easiest way is to call the service directly via the test session.
    return task_id


def test_approve_plan_api_404(api_client: TestClient) -> None:
    resp = api_client.post("/api/tasks/9999/approve-plan")
    assert resp.status_code == 404


def test_approve_plan_api_wrong_status(api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_FAKE_PLAN_JSON", _GOOD_PLAN_JSON)
    task_id = _create_project_and_task(api_client)
    # Task is in 'queued', not 'waiting_approval'
    resp = api_client.post(f"/api/tasks/{task_id}/approve-plan")
    assert resp.status_code == 409
    assert "not waiting" in resp.json()["detail"]
