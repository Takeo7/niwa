"""End-to-end verification integration (PR-V1-11a).

Happy: fake CLI emits clean terminator + touches file → ``verified``.
Sad: fake ends on an unanswered question → ``verification_failed`` +
``TaskEvent(kind='verification')``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.executor.core import process_pending
from app.models import Base, Project, Run, Task, TaskEvent


FAKE_CLI = (Path(__file__).parent / "fixtures" / "fake_claude_cli.py").resolve()


@pytest.fixture()
def session(tmp_path: Path) -> Iterator[Session]:
    eng = create_engine(f"sqlite:///{tmp_path / 'verif.sqlite3'}", future=True)
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng, autoflush=False, autocommit=False, future=True)() as s:
        yield s
    eng.dispose()


def _prime(tmp_path: Path, mp: pytest.MonkeyPatch, *, lines: list[dict], touch: Path | None = None) -> None:
    os.chmod(FAKE_CLI, os.stat(FAKE_CLI).st_mode | 0o111)
    script = tmp_path / "script.jsonl"
    script.write_text("\n".join(json.dumps(e) for e in lines) + "\n")
    mp.setenv("NIWA_CLAUDE_CLI", str(FAKE_CLI))
    mp.setenv("FAKE_CLAUDE_SCRIPT", str(script))
    mp.setenv("FAKE_CLAUDE_EXIT", "0")
    if touch is not None:
        mp.setenv("FAKE_CLAUDE_TOUCH", str(touch))


def _seed(session: Session, git_project: Path) -> Task:
    project = Project(slug="demo", name="D", kind="library", local_path=str(git_project))
    session.add(project)
    session.commit()
    task = Task(project_id=project.id, title="t", description="", status="queued")
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def _assistant(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def test_happy_path_run_verified(
    session: Session, git_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _seed(session, git_project)
    _prime(
        tmp_path, monkeypatch,
        lines=[_assistant("done"), {"type": "result", "subtype": "success"}],
        touch=git_project / "new.py",
    )

    assert process_pending(session) == 1

    session.expire_all()
    assert session.get(Task, task.id).status == "done"
    run = session.query(Run).one()
    assert run.status == "completed" and run.outcome == "verified"
    evidence = json.loads(run.verification_json or "{}")
    assert evidence.get("exit_ok") is True
    assert evidence.get("stream_terminated_cleanly") is True


def test_sad_path_question_unanswered(
    session: Session, git_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _seed(session, git_project)
    _prime(tmp_path, monkeypatch, lines=[_assistant("should I continue?")])

    assert process_pending(session) == 1

    session.expire_all()
    run = session.query(Run).one()
    assert run.status == "failed" and run.outcome == "verification_failed"
    evidence = json.loads(run.verification_json or "{}")
    assert evidence.get("error_code") == "question_unanswered"
    assert session.get(Task, task.id).status == "failed"
    events = (
        session.query(TaskEvent)
        .filter(TaskEvent.task_id == task.id, TaskEvent.kind == "verification")
        .all()
    )
    assert len(events) == 1
    payload = json.loads(events[0].payload_json or "{}")
    assert payload == {"error_code": "question_unanswered", "outcome": "verification_failed"}
