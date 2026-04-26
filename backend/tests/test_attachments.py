"""HTTP + executor tests for task attachments (PR-V1-33)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.api.deps import get_session
from app.executor.core import _build_prompt
from app.models import Attachment, Project, Task


@pytest.fixture()
def task_in_project(client, tmp_path: Path) -> dict[str, Any]:
    """Project rooted at ``tmp_path`` + one queued task ready for uploads."""

    client.post(
        "/api/projects",
        json={"slug": "demo", "name": "Demo", "kind": "library", "local_path": str(tmp_path)},
    ).raise_for_status()
    resp = client.post("/api/projects/demo/tasks", json={"title": "with files"})
    resp.raise_for_status()
    return resp.json()


def _upload(client, task_id: int, name: str, body: bytes, mime: str = "text/plain"):
    return client.post(
        f"/api/tasks/{task_id}/attachments",
        files={"file": (name, io.BytesIO(body), mime)},
    )


def _force_status(app, task_id: int, new_status: str) -> None:
    gen = app.dependency_overrides[get_session]()
    session = next(gen)
    try:
        session.execute(
            text("UPDATE tasks SET status = :s WHERE id = :tid"),
            {"s": new_status, "tid": task_id},
        )
        session.commit()
    finally:
        gen.close()


def test_post_attachment_writes_file_and_row(client, task_in_project, tmp_path: Path) -> None:
    task = task_in_project
    response = _upload(client, task["id"], "spec.md", b"# spec\nhello", "text/markdown")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["filename"] == "spec.md"
    assert body["content_type"] == "text/markdown"
    assert body["size_bytes"] == len(b"# spec\nhello")
    assert body["task_id"] == task["id"]

    expected = tmp_path / ".niwa" / "attachments" / f"task-{task['id']}" / "spec.md"
    assert expected.exists()
    assert expected.read_bytes() == b"# spec\nhello"

    listing = client.get(f"/api/tasks/{task['id']}/attachments")
    assert listing.status_code == 200
    assert len(listing.json()) == 1


@pytest.mark.parametrize(
    "filename",
    ["../escape.txt", "..\\escape.txt", "/etc/passwd", "sub/path.txt"],
)
def test_post_attachment_rejects_path_traversal(
    client, task_in_project, tmp_path: Path, filename: str,
) -> None:
    response = _upload(client, task_in_project["id"], filename, b"x")
    assert response.status_code == 400, response.text
    assert not (tmp_path / ".niwa").exists()


def test_post_attachment_409_when_task_running(client, app, task_in_project) -> None:
    _force_status(app, task_in_project["id"], "running")
    response = _upload(client, task_in_project["id"], "note.txt", b"x")
    assert response.status_code == 409


def test_executor_prompt_includes_attachments(tmp_path: Path) -> None:
    """``_build_prompt`` renders attachment paths relative to the cwd."""

    project = Project(slug="p", name="P", kind="library", local_path=str(tmp_path))
    task = Task(project_id=1, title="use the spec", description="ship it", status="queued")
    task.id = 7
    task.project = project

    storage = tmp_path / ".niwa" / "attachments" / "task-7"
    storage.mkdir(parents=True)
    (storage / "spec.md").write_bytes(b"x")
    (storage / "mockup.png").write_bytes(b"y")

    attachments = [
        Attachment(task_id=7, filename=n, content_type=None, size_bytes=1,
                   storage_path=str(storage / n))
        for n in ("spec.md", "mockup.png")
    ]

    prompt = _build_prompt(task, attachments)
    assert "use the spec" in prompt
    assert "ship it" in prompt
    assert "## Attached files" in prompt
    assert ".niwa/attachments/task-7/spec.md" in prompt
    assert ".niwa/attachments/task-7/mockup.png" in prompt
