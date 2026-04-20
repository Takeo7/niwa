"""Unit tests for the Claude Code adapter + executor integration (PR-V1-07).

Every test drives ``process_pending`` against a real subprocess — the fake
Claude CLI in ``tests/fixtures/fake_claude_cli.py`` emits the exact
stream-json lines the real ``claude`` CLI would emit, so nothing mocks
``subprocess`` itself. The four cases track the outcomes declared in the
brief: happy path, non-zero exit, malformed JSON line, and missing binary.
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
from app.models import Base, Project, Run, RunEvent, Task


FAKE_CLI_PATH = (
    Path(__file__).parent / "fixtures" / "fake_claude_cli.py"
).resolve()


@pytest.fixture()
def engine(tmp_path: Path):
    db_path = tmp_path / "adapter.sqlite3"
    eng = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def Session_(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture()
def session(Session_) -> Iterator[Session]:
    with Session_() as s:
        yield s


def _make_project(session: Session, local_path: str) -> Project:
    project = Project(
        slug="demo",
        name="Demo",
        kind="library",
        local_path=local_path,
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def _make_task(session: Session, project: Project, title: str = "t") -> Task:
    task = Task(
        project_id=project.id,
        title=title,
        description="",
        status="queued",
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def _write_script(path: Path, events: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return path


def _env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cli: str,
    script: Path | None = None,
    exit_code: int = 0,
) -> None:
    monkeypatch.setenv("NIWA_CLAUDE_CLI", cli)
    if script is not None:
        monkeypatch.setenv("FAKE_CLAUDE_SCRIPT", str(script))
    monkeypatch.setenv("FAKE_CLAUDE_EXIT", str(exit_code))


def _fake_cli_cmd() -> str:
    """Return a shell-ready invocation of the fake CLI via the current Python."""

    # ``NIWA_CLAUDE_CLI`` is interpreted by the adapter as a single executable
    # path. To invoke a Python script we rely on the shebang; mark the file
    # executable once at import time so each test can just point at the path.
    st = os.stat(FAKE_CLI_PATH)
    os.chmod(FAKE_CLI_PATH, st.st_mode | 0o111)
    return str(FAKE_CLI_PATH)


def test_adapter_parses_stream_and_writes_run_events(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: 3 events + exit 0 → run completed, task done."""

    project = _make_project(session, str(tmp_path))
    task = _make_task(session, project, title="stream")

    script = _write_script(
        tmp_path / "script.jsonl",
        [
            {"type": "assistant", "message": {"content": "hi"}},
            {"type": "tool_use", "name": "Write", "input": {"path": "x"}},
            {"type": "result", "exit_code": 0, "cost_usd": 0.01},
        ],
    )
    _env(monkeypatch, cli=_fake_cli_cmd(), script=script, exit_code=0)

    assert process_pending(session) == 1

    session.expire_all()
    refreshed = session.get(Task, task.id)
    assert refreshed is not None
    assert refreshed.status == "done"

    run = session.query(Run).filter(Run.task_id == task.id).one()
    assert run.status == "completed"
    assert run.exit_code == 0
    assert run.outcome == "cli_ok"

    events = (
        session.query(RunEvent)
        .filter(RunEvent.run_id == run.id)
        .order_by(RunEvent.id.asc())
        .all()
    )
    types = [e.event_type for e in events]
    # started, assistant, tool_use, result, completed
    assert types[0] == "started"
    assert types[-1] == "completed"
    assert "assistant" in types
    assert "tool_use" in types
    assert "result" in types


def test_adapter_nonzero_exit_marks_run_failed(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _make_project(session, str(tmp_path))
    task = _make_task(session, project, title="boom")

    script = _write_script(
        tmp_path / "script.jsonl",
        [{"type": "assistant", "message": {"content": "partial"}}],
    )
    _env(monkeypatch, cli=_fake_cli_cmd(), script=script, exit_code=1)

    assert process_pending(session) == 1

    session.expire_all()
    refreshed = session.get(Task, task.id)
    assert refreshed is not None
    assert refreshed.status == "failed"

    run = session.query(Run).filter(Run.task_id == task.id).one()
    assert run.status == "failed"
    assert run.exit_code == 1
    assert run.outcome == "cli_nonzero_exit"


def test_adapter_skips_malformed_json_lines(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _make_project(session, str(tmp_path))
    task = _make_task(session, project, title="garbage")

    # Craft the script manually — _write_script would re-JSON the garbage.
    script = tmp_path / "script.jsonl"
    script.write_text(
        json.dumps({"type": "assistant", "message": {"content": "one"}}) + "\n"
        + "not json garbage\n"
        + json.dumps({"type": "result", "exit_code": 0}) + "\n"
    )
    _env(monkeypatch, cli=_fake_cli_cmd(), script=script, exit_code=0)

    assert process_pending(session) == 1

    run = session.query(Run).filter(Run.task_id == task.id).one()
    assert run.status == "completed"
    assert run.outcome == "cli_ok"

    stream_events = (
        session.query(RunEvent)
        .filter(
            RunEvent.run_id == run.id,
            RunEvent.event_type.notin_(["started", "completed"]),
        )
        .all()
    )
    # Only the two valid JSON lines make it to run_events.
    assert len(stream_events) == 2
    types = sorted(e.event_type for e in stream_events)
    assert types == ["assistant", "result"]


def test_adapter_binary_missing_fails_fast(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _make_project(session, str(tmp_path))
    task = _make_task(session, project, title="ghost")

    monkeypatch.setenv("NIWA_CLAUDE_CLI", str(tmp_path / "does-not-exist"))

    assert process_pending(session) == 1

    session.expire_all()
    refreshed = session.get(Task, task.id)
    assert refreshed is not None
    assert refreshed.status == "failed"

    run = session.query(Run).filter(Run.task_id == task.id).one()
    assert run.status == "failed"
    assert run.outcome == "cli_not_found"
