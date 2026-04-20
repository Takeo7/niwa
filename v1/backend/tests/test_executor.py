"""Unit tests for the echo executor (PR-V1-05).

The tests drive ``process_pending`` directly — the polling loop and the CLI
entrypoint are thin wrappers around it and are covered by manual smoke runs
(see the brief). The race test is the only one that spins up threads.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.executor.core import claim_next_task, process_pending
from app.models import Base, Project, Run, RunEvent, Task, TaskEvent


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


def _make_project(session: Session, **overrides) -> Project:
    defaults = dict(
        slug="demo",
        name="Demo",
        kind="library",
        local_path="/tmp/demo",
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


def test_process_pending_single_task(session: Session) -> None:
    project = _make_project(session)
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

    runs = session.query(Run).filter(Run.task_id == task.id).all()
    assert len(runs) == 1
    run = runs[0]
    assert run.status == "completed"
    assert run.exit_code == 0
    assert run.outcome == "echo"
    assert run.model == "echo"
    assert run.finished_at is not None


def test_process_pending_multiple_tasks(session: Session) -> None:
    project = _make_project(session)
    first = _make_task(session, project, title="first")
    second = _make_task(session, project, title="second")
    third = _make_task(session, project, title="third")

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


def test_run_writes_expected_events(session: Session) -> None:
    project = _make_project(session)
    task = _make_task(session, project, title="events")

    assert process_pending(session) == 1

    run = session.query(Run).filter(Run.task_id == task.id).one()
    events = (
        session.query(RunEvent)
        .filter(RunEvent.run_id == run.id)
        .order_by(RunEvent.id.asc())
        .all()
    )
    assert [e.event_type for e in events] == ["started", "completed"]


def test_task_writes_status_transitions(session: Session) -> None:
    project = _make_project(session)
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
