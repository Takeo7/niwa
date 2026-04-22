"""Unit tests for the Claude Code adapter + executor integration (PR-V1-07).

Most tests drive ``process_pending`` against a real subprocess — the fake
Claude CLI in ``tests/fixtures/fake_claude_cli.py`` emits the exact
stream-json lines the real ``claude`` CLI would emit, so nothing mocks
``subprocess`` itself. The four brief-declared outcomes (happy path,
non-zero exit, malformed JSON line, missing binary) are complemented by
two ``close()`` tests that guard the mid-stream cleanup path added as a
codex-review fix-up.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters import ClaudeCodeAdapter
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
    touch: Path | None = None,
) -> None:
    monkeypatch.setenv("NIWA_CLAUDE_CLI", cli)
    if script is not None:
        monkeypatch.setenv("FAKE_CLAUDE_SCRIPT", str(script))
    monkeypatch.setenv("FAKE_CLAUDE_EXIT", str(exit_code))
    if touch is not None:
        # PR-V1-11b: E3 requires ≥1 artifact inside the adapter cwd; tests
        # that expect ``verified`` pass a touch path inside ``git_project``.
        monkeypatch.setenv("FAKE_CLAUDE_TOUCH", str(touch))


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
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: 3 events + exit 0 → run completed, task done."""

    project = _make_project(session, str(git_project))
    task = _make_task(session, project, title="stream")

    script = _write_script(
        tmp_path / "script.jsonl",
        [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
            {"type": "tool_use", "name": "Write", "input": {"path": "x"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}},
            {"type": "result", "exit_code": 0, "cost_usd": 0.01},
        ],
    )
    _env(
        monkeypatch,
        cli=_fake_cli_cmd(),
        script=script,
        exit_code=0,
        touch=git_project / "touch-{pid}.txt",
    )

    assert process_pending(session) == 1

    session.expire_all()
    refreshed = session.get(Task, task.id)
    assert refreshed is not None
    assert refreshed.status == "done"

    run = session.query(Run).filter(Run.task_id == task.id).one()
    assert run.status == "completed"
    assert run.exit_code == 0
    # PR-V1-11a: post-verify the run-level outcome is ``verified``.
    assert run.outcome == "verified"

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
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _make_project(session, str(git_project))
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
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _make_project(session, str(git_project))
    task = _make_task(session, project, title="garbage")

    # Craft the script manually — _write_script would re-JSON the garbage.
    script = tmp_path / "script.jsonl"
    script.write_text(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "one"}]}}) + "\n"
        + "not json garbage\n"
        + json.dumps({"type": "result", "exit_code": 0}) + "\n"
    )
    _env(
        monkeypatch,
        cli=_fake_cli_cmd(),
        script=script,
        exit_code=0,
        touch=git_project / "touch-{pid}.txt",
    )

    assert process_pending(session) == 1

    run = session.query(Run).filter(Run.task_id == task.id).one()
    assert run.status == "completed"
    assert run.outcome == "verified"

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
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_triage_execute: None,
) -> None:
    project = _make_project(session, str(git_project))
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


def test_adapter_close_terminates_subprocess_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``close()`` must reap the Popen even if ``iter_events`` was abandoned.

    Simulates the blocker-2 path: the executor loop raised mid-stream (e.g.
    SQLite locked during a per-event commit) so ``wait()`` never ran. The
    ``finally: adapter.close()`` in ``run_adapter`` is the safety net.
    """

    # Script with a sleep between lines so the CLI is still running when we
    # break out of iter_events. 50 ms/line × 5 lines = 250 ms of runway.
    script = tmp_path / "script.jsonl"
    script.write_text(
        "\n".join(
            json.dumps({"type": "assistant", "message": {"content": f"x{i}"}})
            for i in range(5)
        )
        + "\n"
    )
    cli = _fake_cli_cmd()
    monkeypatch.setenv("NIWA_CLAUDE_CLI", cli)
    monkeypatch.setenv("FAKE_CLAUDE_SCRIPT", str(script))
    monkeypatch.setenv("FAKE_CLAUDE_EXIT", "0")
    monkeypatch.setenv("FAKE_CLAUDE_DELAY_MS", "50")

    adapter = ClaudeCodeAdapter(
        cli_path=cli,
        cwd=str(tmp_path),
        prompt="hi",
        timeout=30.0,
    )

    events = adapter.iter_events()
    # Pull one event, then walk away — mimics an exception mid-stream.
    first = next(events)
    assert first.kind == "assistant"

    proc = adapter._proc  # internal, but the whole point of the test
    assert proc is not None
    assert proc.poll() is None, "precondition: child still running"

    adapter.close()
    assert proc.poll() is not None, "close() must reap the subprocess"

    # Second call must not raise and must not block.
    adapter.close()


def test_adapter_close_is_safe_when_spawn_never_happened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``close()`` on an adapter whose CLI was missing must be a no-op."""

    monkeypatch.setenv("NIWA_CLAUDE_CLI", str(tmp_path / "nope"))
    adapter = ClaudeCodeAdapter(
        cli_path=str(tmp_path / "nope"),
        cwd=str(tmp_path),
        prompt="hi",
        timeout=5.0,
    )
    # Drain iter_events so the "cli_not_found" outcome is set without spawn.
    list(adapter.iter_events())
    assert adapter.outcome == "cli_not_found"

    # No Popen → close() must still be safe.
    adapter.close()
    adapter.close()


def test_default_args_include_dangerously_skip_permissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR-V1-20: the adapter must always pass --dangerously-skip-permissions.

    Without the flag, ``claude -p --output-format stream-json`` asks for
    interactive approval on every Write/Edit/Bash tool use; stream-json has
    no approval channel so the requests are auto-denied and the run ends
    with no artifacts. Guarded here as both a class-level contract on
    ``DEFAULT_ARGS`` and an end-to-end assertion that the spawned ``cmd``
    carries the flag.
    """

    assert "--dangerously-skip-permissions" in ClaudeCodeAdapter.DEFAULT_ARGS

    captured: dict[str, list[str]] = {}

    real_popen = subprocess.Popen

    def _capturing_popen(cmd, *args, **kwargs):
        captured["cmd"] = list(cmd)
        return real_popen(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _capturing_popen)

    cli = _fake_cli_cmd()
    script = _write_script(
        tmp_path / "script.jsonl",
        [{"type": "result", "exit_code": 0}],
    )
    monkeypatch.setenv("NIWA_CLAUDE_CLI", cli)
    monkeypatch.setenv("FAKE_CLAUDE_SCRIPT", str(script))
    monkeypatch.setenv("FAKE_CLAUDE_EXIT", "0")

    adapter = ClaudeCodeAdapter(
        cli_path=cli,
        cwd=str(tmp_path),
        prompt="hi",
        timeout=5.0,
    )
    try:
        list(adapter.iter_events())
        adapter.wait()
    finally:
        adapter.close()

    assert "cmd" in captured, "Popen was not invoked"
    assert "--dangerously-skip-permissions" in captured["cmd"]
