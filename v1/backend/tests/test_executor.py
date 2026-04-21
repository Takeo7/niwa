"""Unit tests for the adapter-driven executor (PR-V1-07, PR-V1-08).

PR-V1-07 replaced the echo with the real adapter path; PR-V1-08 layers
``prepare_task_branch`` on top so every task runs on a
``niwa/task-<id>-<slug>`` branch. The happy-path cases now use the
``git_project`` fixture (see ``conftest.py``) — a real git repo with one
seed commit — and assert ``task.branch_name`` is persisted before the
adapter spawns. The new ``test_runs_fail_on_git_setup_error`` pins the
failure path: a non-git ``local_path`` must terminate the task ``failed``
without the adapter ever running.

The race test still spins up two threads on the same DB; it does not
launch subprocesses (the contention happens inside
``claim_next_task`` before any adapter work).
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.executor.core import claim_next_task, process_pending
from app.executor.git_workspace import build_branch_name
from app.models import Base, Project, Run, RunEvent, Task, TaskEvent


FAKE_CLI_PATH = (
    Path(__file__).parent / "fixtures" / "fake_claude_cli.py"
).resolve()


@pytest.fixture(autouse=True)
def _fake_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every test at the fake CLI with a minimal one-event script.

    One ``result`` line + exit 0 is the bare minimum to flip a run to
    ``completed`` and a task to ``done`` through the real adapter path.
    Since PR-V1-11b, E3 requires ≥1 artifact inside the task cwd, so the
    default run also touches a pid-scoped file under ``tmp_path``; tests
    that wire their own ``git_project`` override ``FAKE_CLAUDE_TOUCH``
    below to land the artifact inside the repo instead.
    """

    st = os.stat(FAKE_CLI_PATH)
    os.chmod(FAKE_CLI_PATH, st.st_mode | 0o111)

    script = tmp_path / "default_script.jsonl"
    script.write_text(json.dumps({"type": "result", "exit_code": 0}) + "\n")

    monkeypatch.setenv("NIWA_CLAUDE_CLI", str(FAKE_CLI_PATH))
    monkeypatch.setenv("FAKE_CLAUDE_SCRIPT", str(script))
    monkeypatch.setenv("FAKE_CLAUDE_EXIT", "0")


@pytest.fixture()
def engine(tmp_path: Path):
    """A file-backed SQLite engine shared across sessions in the same test.

    The race test needs multiple threads to hit the same database from
    different sessions; a file-backed DB is the simplest way to achieve that
    without juggling ``StaticPool`` semantics across threads.
    """

    db_path = tmp_path / "executor.sqlite3"
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


def _make_project(session: Session, local_path: str | Path = "/tmp/demo", **overrides) -> Project:
    defaults = dict(
        slug="demo",
        name="Demo",
        kind="library",
        local_path=str(local_path),
    )
    defaults.update(overrides)
    project = Project(**defaults)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def _make_task(
    session: Session,
    project: Project,
    *,
    status: str = "queued",
    title: str = "t",
) -> Task:
    task = Task(
        project_id=project.id,
        title=title,
        description="",
        status=status,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


# ---------------------------------------------------------------------------
# process_pending
# ---------------------------------------------------------------------------


def test_process_pending_nothing_to_do(session: Session) -> None:
    assert process_pending(session) == 0


def test_process_pending_single_task(
    session: Session,
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # PR-V1-11b: E3 needs ≥1 artifact inside cwd, so the fake touches a
    # file in the repo before exit.
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", str(git_project / "touch-{pid}.txt"))
    project = _make_project(session, local_path=git_project)
    task = _make_task(session, project, title="only one")

    assert process_pending(session) == 1

    session.expire_all()
    refreshed = session.get(Task, task.id)
    assert refreshed is not None
    assert refreshed.status == "done"
    assert refreshed.completed_at is not None
    assert refreshed.completed_at.tzinfo is None or isinstance(
        refreshed.completed_at, datetime
    )
    # PR-V1-08: the branch name is persisted before the adapter spawns.
    assert refreshed.branch_name == build_branch_name(task)

    runs = session.query(Run).filter(Run.task_id == task.id).all()
    assert len(runs) == 1
    run = runs[0]
    assert run.status == "completed"
    assert run.exit_code == 0
    # PR-V1-11a: the run-level outcome is ``verified`` once the verifier
    # has passed; the adapter's own outcome (``cli_ok``) is consumed
    # internally by the verifier.
    assert run.outcome == "verified"
    assert run.model == "claude-code"
    assert run.finished_at is not None


def test_process_pending_multiple_tasks(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # PR-V1-11b finding #3: the default ``git_project`` is shared across
    # tasks; once task 1 dirties the tree (required for E3 to pass) task
    # 2's ``prepare_task_branch`` would trip on the dirty state. We seed
    # a dedicated repo per task and point both the project ``local_path``
    # and ``FAKE_CLAUDE_TOUCH`` at distinct dirs so every adapter run
    # writes its artifact into its own workspace.
    import subprocess as _sp

    repos: list[Path] = []
    for idx in range(3):
        d = tmp_path / f"repo-{idx}"
        d.mkdir()
        _sp.run(["git", "init", "-b", "main"], cwd=d, check=True, capture_output=True)
        _sp.run(["git", "config", "user.email", "niwa@test.local"], cwd=d, check=True)
        _sp.run(["git", "config", "user.name", "Niwa Test"], cwd=d, check=True)
        _sp.run(["git", "config", "commit.gpgsign", "false"], cwd=d, check=True)
        (d / "README.md").write_text("seed\n")
        _sp.run(["git", "add", "README.md"], cwd=d, check=True, capture_output=True)
        _sp.run(["git", "commit", "-m", "init"], cwd=d, check=True, capture_output=True)
        repos.append(d)

    # Every task uses its own project rooted on a dedicated repo.
    first_project = _make_project(session, local_path=repos[0], slug="repo-0")
    second_project = _make_project(session, local_path=repos[1], slug="repo-1")
    third_project = _make_project(session, local_path=repos[2], slug="repo-2")
    first = _make_task(session, first_project, title="first")
    second = _make_task(session, second_project, title="second")
    third = _make_task(session, third_project, title="third")

    # The touch path is resolved relative to each run's cwd, so a single
    # ``touch-<pid>.txt`` placed via the adapter cwd lands inside each
    # repo in turn.
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", "touch-{pid}.txt")

    assert process_pending(session) == 3

    session.expire_all()
    for t_id in (first.id, second.id, third.id):
        t = session.get(Task, t_id)
        assert t is not None
        assert t.status == "done"

    # Creation order is preserved when draining — first created, first done.
    runs = (
        session.query(Run)
        .order_by(Run.id.asc())
        .all()
    )
    assert [r.task_id for r in runs] == [first.id, second.id, third.id]


def test_process_pending_skips_non_queued(session: Session) -> None:
    project = _make_project(session)
    inbox = _make_task(session, project, status="inbox", title="idle")
    running = _make_task(session, project, status="running", title="busy")
    done = _make_task(session, project, status="done", title="old")

    assert process_pending(session) == 0

    session.expire_all()
    for t_id, expected in (
        (inbox.id, "inbox"),
        (running.id, "running"),
        (done.id, "done"),
    ):
        t = session.get(Task, t_id)
        assert t is not None
        assert t.status == expected

    # No runs should have been created either.
    assert session.query(Run).count() == 0


# ---------------------------------------------------------------------------
# Event writes
# ---------------------------------------------------------------------------


def test_run_writes_expected_events(
    session: Session,
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", str(git_project / "touch-{pid}.txt"))
    project = _make_project(session, local_path=git_project)
    task = _make_task(session, project, title="events")

    assert process_pending(session) == 1

    run = session.query(Run).filter(Run.task_id == task.id).one()
    events = (
        session.query(RunEvent)
        .filter(RunEvent.run_id == run.id)
        .order_by(RunEvent.id.asc())
        .all()
    )
    # The adapter pipeline writes: started, <stream events...>, completed.
    types = [e.event_type for e in events]
    assert types[0] == "started"
    assert types[-1] == "completed"
    # The default fake script emits exactly one ``result`` line between
    # the synthetic bookends.
    assert "result" in types


def test_task_writes_status_transitions(
    session: Session,
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", str(git_project / "touch-{pid}.txt"))
    project = _make_project(session, local_path=git_project)
    task = _make_task(session, project, title="transitions")

    assert process_pending(session) == 1

    events = (
        session.query(TaskEvent)
        .filter(TaskEvent.task_id == task.id)
        .order_by(TaskEvent.id.asc())
        .all()
    )
    # Two status_changed events written by the executor:
    #   queued → running, running → done.
    status_events = [e for e in events if e.kind == "status_changed"]
    assert len(status_events) == 2
    payloads = [e.payload_json for e in status_events]
    assert '"from": "queued"' in payloads[0]
    assert '"to": "running"' in payloads[0]
    assert '"from": "running"' in payloads[1]
    assert '"to": "done"' in payloads[1]


# ---------------------------------------------------------------------------
# Race condition — two threads calling claim_next_task on the same task.
# ---------------------------------------------------------------------------


def test_claim_is_atomic_under_race(engine, Session_) -> None:
    # Seed one queued task. Each thread gets its own session on the same DB.
    with Session_() as seed:
        project = _make_project(seed)
        task = _make_task(seed, project, title="contended")
        task_id = task.id

    results: list[Task | None] = [None, None]
    errors: list[BaseException | None] = [None, None]
    barrier = threading.Barrier(2)

    def worker(index: int) -> None:
        try:
            with Session_() as s:
                barrier.wait(timeout=5)
                results[index] = claim_next_task(s)
        except BaseException as exc:  # noqa: BLE001 - re-raised via assert
            errors[index] = exc

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    # SQLite may raise ``OperationalError: database is locked`` on the loser
    # when two BEGIN IMMEDIATE collide; we treat that as "lost the race".
    # The invariant is: no more than one winner, and the task ends in
    # ``running``.
    winners = [r for r in results if r is not None]
    assert len(winners) <= 1, "two threads claimed the same task"

    # At least one side must have either won (returned the task) or recognised
    # the contention (returned None / raised OperationalError). We never
    # silently lose the task.
    from sqlalchemy.exc import OperationalError

    for err in errors:
        if err is not None:
            assert isinstance(err, OperationalError), err

    # Final state: the task is ``running`` (one of the threads did claim it).
    with Session_() as s:
        final = s.get(Task, task_id)
        assert final is not None
        assert final.status == "running"


# ---------------------------------------------------------------------------
# Git workspace failure — non-git local_path (PR-V1-08)
# ---------------------------------------------------------------------------


def test_runs_fail_on_git_setup_error(
    session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-git ``local_path`` must fail the task before the adapter spawns."""

    # If the executor ever reached the adapter this would surface as
    # ``cli_not_found``, not the expected ``git_setup_failed``.
    monkeypatch.setenv("NIWA_CLAUDE_CLI", str(tmp_path / "does-not-exist"))
    plain = tmp_path / "no-git-here"
    plain.mkdir()
    project = _make_project(session, local_path=plain)
    task = _make_task(session, project, title="needs git")

    assert process_pending(session) == 1

    session.expire_all()
    refreshed = session.get(Task, task.id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    assert refreshed.branch_name is None

    run = session.query(Run).filter(Run.task_id == task.id).one()
    assert run.status == "failed"
    assert run.outcome == "git_setup_failed"
    assert run.exit_code is None  # adapter never spawned

    events = session.query(RunEvent).filter(RunEvent.run_id == run.id).all()
    types = [e.event_type for e in events]
    assert "result" not in types  # no CLI stream reached the DB
    error_events = [e for e in events if e.event_type == "error"]
    assert error_events, "expected an error event on git_setup_failed"
    payload = json.loads(error_events[0].payload_json or "{}")
    assert "git_setup_failed" in payload.get("reason", "")


# ---------------------------------------------------------------------------
# Triage integration (PR-V1-12)
# ---------------------------------------------------------------------------


def test_process_pending_executes_when_triage_says_execute(
    session: Session,
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With triage emitting ``execute``, the normal run pipeline proceeds."""

    from app.triage import TriageDecision

    # Keep the normal fake CLI path for the real adapter run.
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", str(git_project / "touch-{pid}.txt"))

    def fake_triage(project, task):
        return TriageDecision(
            kind="execute", subtasks=[], rationale="direct", raw_output=""
        )

    monkeypatch.setattr("app.executor.core.triage_task", fake_triage)

    project = _make_project(session, local_path=git_project)
    task = _make_task(session, project, title="execute me")

    assert process_pending(session) == 1

    session.expire_all()
    refreshed = session.get(Task, task.id)
    assert refreshed is not None
    assert refreshed.status == "done"
    runs = session.query(Run).filter(Run.task_id == task.id).all()
    assert len(runs) == 1
    assert runs[0].status == "completed"


def test_process_pending_splits_when_triage_says_split(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Triage ``split`` closes the parent without a Run and queues subtasks."""

    from app.triage import TriageDecision

    def fake_triage(project, task):
        return TriageDecision(
            kind="split",
            subtasks=["alpha", "beta"],
            rationale="two areas",
            raw_output="",
        )

    monkeypatch.setattr("app.executor.core.triage_task", fake_triage)
    # Make sure the CLI is never spawned: point at a missing binary.
    monkeypatch.setenv("NIWA_CLAUDE_CLI", str(tmp_path / "does-not-exist"))

    project = _make_project(session, local_path=tmp_path)
    parent = _make_task(session, project, title="parent")

    assert process_pending(session) == 1

    session.expire_all()
    refreshed = session.get(Task, parent.id)
    assert refreshed is not None
    assert refreshed.status == "done"
    assert refreshed.completed_at is not None

    # No Run recorded — the adapter was bypassed entirely.
    assert session.query(Run).filter(Run.task_id == parent.id).count() == 0

    subtasks = (
        session.query(Task)
        .filter(Task.parent_task_id == parent.id)
        .order_by(Task.id.asc())
        .all()
    )
    assert [t.title for t in subtasks] == ["alpha", "beta"]
    assert all(t.status == "queued" for t in subtasks)
    assert all(t.project_id == project.id for t in subtasks)

    # The split marker is a ``message`` kind with ``event=triage_split``
    # in the JSON payload (SPEC §3 fixes the enum; the marker lives in
    # the payload). A status_changed event also flips running→done.
    events = (
        session.query(TaskEvent)
        .filter(TaskEvent.task_id == parent.id)
        .order_by(TaskEvent.id.asc())
        .all()
    )
    split_events = [
        e for e in events
        if e.kind == "message" and e.payload_json and "triage_split" in e.payload_json
    ]
    assert len(split_events) == 1
    payload = json.loads(split_events[0].payload_json)
    assert payload.get("event") == "triage_split"
    assert payload.get("rationale") == "two areas"
    assert payload.get("subtask_ids") == [t.id for t in subtasks]

    status_events = [e for e in events if e.kind == "status_changed"]
    payloads = [json.loads(e.payload_json or "{}") for e in status_events]
    assert {"from": "running", "to": "done"} in payloads


def test_process_pending_marks_failed_on_triage_error(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``TriageError`` ends the task ``failed`` with ``triage_failed``."""

    from app.triage import TriageError

    def boom(project, task):
        raise TriageError("bad json")

    monkeypatch.setattr("app.executor.core.triage_task", boom)
    monkeypatch.setenv("NIWA_CLAUDE_CLI", str(tmp_path / "does-not-exist"))

    project = _make_project(session, local_path=tmp_path)
    task = _make_task(session, project, title="triage will die")

    assert process_pending(session) == 1

    session.expire_all()
    refreshed = session.get(Task, task.id)
    assert refreshed is not None
    assert refreshed.status == "failed"

    run = session.query(Run).filter(Run.task_id == task.id).one()
    assert run.status == "failed"
    assert run.outcome == "triage_failed"

    events = session.query(TaskEvent).filter(TaskEvent.task_id == task.id).all()
    verif = [e for e in events if e.kind == "verification"]
    assert verif, "expected verification TaskEvent on triage_failed"
    payload = json.loads(verif[0].payload_json or "{}")
    assert payload.get("error_code") == "triage_failed"
