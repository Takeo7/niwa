"""Integrity tests for the Niwa v1 data models.

These tests exercise the schema declared in ``app.models``:

* default values for ``Project.autonomy_mode`` and ``Run.status``;
* CASCADE behaviour on the project → task and task self-FK relations;
* CHECK constraints on ``Task.status``;
* foreign-key enforcement for ``task_events`` and ``run_events``;
* that ``alembic upgrade head`` materialises the five SPEC §3 tables.

Every test uses an isolated SQLite file (via ``tempfile``) and a fresh
engine built on top of ``Base.metadata``. We do *not* touch the module-level
engine in ``app.db`` — those tests would otherwise clash with the dev DB.
"""

from __future__ import annotations

import os
import subprocess
import sys
import sqlite3
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Project, Run, RunEvent, Task, TaskEvent


@event.listens_for(Engine, "connect")
def _enable_fk_on_test_engines(dbapi_connection, connection_record) -> None:
    """Mirror the production PRAGMA so tests see CASCADE/RESTRICT behaviour."""

    # The app.db module already wires this listener; registering again is a
    # no-op when the engine is the production one and necessary when a test
    # builds its own engine before importing app.db.
    if "sqlite" not in (type(dbapi_connection).__module__ or ""):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Iterator[Path]:
    """Yield a path to an empty SQLite file, cleaned up on teardown."""

    db_path = tmp_path / "niwa-test.sqlite3"
    yield db_path


@pytest.fixture()
def session(tmp_db: Path) -> Iterator[Session]:
    """A SQLAlchemy session bound to a freshly created schema."""

    engine = create_engine(f"sqlite:///{tmp_db}", future=True)
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine, future=True, autoflush=False, autocommit=False)
    with Session_() as s:
        yield s
    engine.dispose()


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


def _make_task(session: Session, project: Project, **overrides) -> Task:
    defaults = dict(
        project_id=project.id,
        title="t",
        description="d",
    )
    defaults.update(overrides)
    task = Task(**defaults)
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def test_project_defaults(session: Session) -> None:
    project = _make_project(session)
    assert project.autonomy_mode == "safe"
    assert project.created_at is not None
    assert project.updated_at is not None


def test_task_fk_project(session: Session) -> None:
    project = _make_project(session)
    task = _make_task(session, project)
    task_id = task.id

    session.delete(project)
    session.commit()

    # With ondelete=CASCADE enabled, the child task must be gone too.
    assert session.get(Task, task_id) is None


def test_task_self_fk(session: Session) -> None:
    project = _make_project(session)
    parent = _make_task(session, project, title="parent")
    child = _make_task(session, project, title="child", parent_task_id=parent.id)
    assert child.parent_task_id == parent.id

    # Pointing at a non-existent task id must be rejected by the FK.
    orphan = Task(
        project_id=project.id,
        parent_task_id=999_999,
        title="orphan",
        description="d",
    )
    session.add(orphan)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_task_status_check(session: Session) -> None:
    project = _make_project(session)
    bad = Task(
        project_id=project.id,
        title="bad",
        description="d",
        status="not-a-real-status",
    )
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_task_event_fk(session: Session) -> None:
    project = _make_project(session)
    task = _make_task(session, project)

    ok = TaskEvent(task_id=task.id, kind="created", message="hello")
    session.add(ok)
    session.commit()
    assert ok.id is not None

    bad = TaskEvent(task_id=999_999, kind="created", message="nope")
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_run_status_default(session: Session) -> None:
    project = _make_project(session)
    task = _make_task(session, project)

    run = Run(task_id=task.id, model="sonnet", artifact_root="/tmp/run")
    session.add(run)
    session.commit()
    session.refresh(run)
    assert run.status == "queued"


def test_run_event_fk(session: Session) -> None:
    project = _make_project(session)
    task = _make_task(session, project)
    run = Run(task_id=task.id, model="sonnet", artifact_root="/tmp/run")
    session.add(run)
    session.commit()
    session.refresh(run)

    ok = RunEvent(run_id=run.id, event_type="stdout", payload_json="{}")
    session.add(ok)
    session.commit()
    assert ok.id is not None

    bad = RunEvent(run_id=999_999, event_type="stdout", payload_json="{}")
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


EXPECTED_TABLES = {"projects", "tasks", "task_events", "runs", "run_events"}
INITIAL_REVISION = "9d205b6968c1"


def _run_alembic_upgrade(tmp_path: Path, db_path: Path) -> subprocess.CompletedProcess:
    """Invoke ``alembic upgrade head`` against ``db_path`` in a subprocess.

    Uses ``-x db_url=...`` so ``env.py`` ignores the dev DB and writes the
    schema to the temp file. ``NIWA_CONFIG`` is pointed at a non-existent path
    so ``load_settings`` still falls back to defaults if the override ever
    regresses — the subprocess must never touch ``data/niwa-v1.sqlite3``.
    """

    backend_dir = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["NIWA_CONFIG"] = str(tmp_path / "no-config.toml")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-x",
            f"db_url=sqlite:///{db_path}",
            "upgrade",
            "head",
        ],
        cwd=backend_dir,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_alembic_upgrade_creates_tables(tmp_path: Path) -> None:
    """Run ``alembic upgrade head`` against a temp DB and inspect the output."""

    db_path = tmp_path / "alembic-smoke.sqlite3"
    result = _run_alembic_upgrade(tmp_path, db_path)
    assert result.returncode == 0, result.stderr
    assert db_path.is_file(), "alembic did not create the target DB file"

    # Verify the migration artefact itself — do NOT fall back to create_all,
    # otherwise a broken migration would still appear green.
    with sqlite3.connect(db_path) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert EXPECTED_TABLES.issubset(names), (
        f"migration did not create expected tables; got {names}"
    )


def test_alembic_upgrade_records_expected_revision(tmp_path: Path) -> None:
    """After ``upgrade head``, ``alembic_version`` must pin the initial rev.

    This is the negative-case partner to ``test_alembic_upgrade_creates_tables``:
    if the migration ever stops applying cleanly or the revision id drifts,
    the check below must fail — guarding against false-green regressions.
    """

    db_path = tmp_path / "alembic-revision.sqlite3"
    result = _run_alembic_upgrade(tmp_path, db_path)
    assert result.returncode == 0, result.stderr

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()
    assert rows == [(INITIAL_REVISION,)], rows


# Each entry is (table_name, index_name, indexed_column).
EXPECTED_FK_INDEXES = [
    ("tasks", "ix_tasks_project_id", "project_id"),
    ("tasks", "ix_tasks_parent_task_id", "parent_task_id"),
    ("runs", "ix_runs_task_id", "task_id"),
    ("task_events", "ix_task_events_task_id", "task_id"),
    ("run_events", "ix_run_events_run_id", "run_id"),
]


def test_alembic_upgrade_creates_fk_indexes(tmp_path: Path) -> None:
    """Every FK column listed in ``EXPECTED_FK_INDEXES`` must be indexed.

    Missing any of these indexes would make cascade deletes and child lookups
    O(n) on every parent row, so we assert directly against the migration
    output via ``sa.inspect``.
    """

    db_path = tmp_path / "alembic-indexes.sqlite3"
    result = _run_alembic_upgrade(tmp_path, db_path)
    assert result.returncode == 0, result.stderr

    engine = create_engine(f"sqlite:///{db_path}", future=True)
    try:
        insp = inspect(engine)
        for table, index_name, column in EXPECTED_FK_INDEXES:
            indexes = {ix["name"]: ix for ix in insp.get_indexes(table)}
            assert index_name in indexes, (
                f"expected index {index_name} on {table}; got {sorted(indexes)}"
            )
            assert indexes[index_name]["column_names"] == [column], (
                f"index {index_name} covers {indexes[index_name]['column_names']}, "
                f"expected [{column!r}]"
            )
    finally:
        engine.dispose()
