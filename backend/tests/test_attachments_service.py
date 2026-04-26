"""Unit tests for ``app.services.attachments`` (PR-V1-33a-i).

These exercise the data-layer service directly — no HTTP, no executor.
The API + executor wiring lands in PR-V1-33a-ii where the
``test_attachments.py`` filename is reserved for HTTP-level cases.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Attachment, Base, Project, Task
from app.services.attachments import (
    InvalidFilename,
    create_attachment,
    delete_attachment,
    sanitize_filename,
)


@pytest.fixture()
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'niwa.sqlite3'}", future=True)
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine, future=True, autoflush=False, autocommit=False)
    with Session_() as s:
        yield s
    engine.dispose()


@pytest.fixture()
def task(session: Session, tmp_path: Path) -> Task:
    project = Project(
        slug="demo",
        name="Demo",
        kind="library",
        local_path=str(tmp_path / "repo"),
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    task = Task(project_id=project.id, title="t", description="d")
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def test_sanitize_filename_returns_clean_for_safe_input() -> None:
    assert sanitize_filename("mockup.png") == "mockup.png"
    assert sanitize_filename("notes.tar.gz") == "notes.tar.gz"


@pytest.mark.parametrize(
    "name",
    ["..", "../etc", "foo/bar", "foo\\bar", "with\x00nul", "subdir/foo.txt"],
)
def test_sanitize_filename_rejects_traversal(name: str) -> None:
    with pytest.raises(InvalidFilename):
        sanitize_filename(name)


def test_create_attachment_writes_file_and_row(
    session: Session, task: Task
) -> None:
    payload = b"hello niwa"
    row = create_attachment(
        session,
        task.id,
        filename="hello.txt",
        content_type="text/plain",
        stream=io.BytesIO(payload),
    )

    expected_dir = (
        Path(task.project.local_path) / ".niwa" / "attachments" / f"task-{task.id}"
    )
    assert row.filename == "hello.txt"
    assert row.size_bytes == len(payload)
    assert row.content_type == "text/plain"
    assert Path(row.storage_path).read_bytes() == payload
    assert Path(row.storage_path).parent == expected_dir.resolve()
    assert session.get(Attachment, row.id) is not None


def test_delete_attachment_removes_file_and_row(
    session: Session, task: Task
) -> None:
    row = create_attachment(
        session,
        task.id,
        filename="bye.txt",
        content_type=None,
        stream=io.BytesIO(b"x"),
    )
    storage = Path(row.storage_path)
    assert storage.exists()

    delete_attachment(session, task.id, row.id)

    assert not storage.exists()
    assert session.get(Attachment, row.id) is None
