"""HTTP + executor tests for task attachments (PR-V1-33).

Four cases (per brief §Tests):

* ``test_post_attachment_writes_file_and_row`` — multipart upload lands a
  row in ``attachments`` and a file under
  ``<local_path>/.niwa/attachments/task-<id>/<filename>``.
* ``test_post_attachment_rejects_path_traversal`` — server refuses
  ``..`` and absolute path attempts with ``400``.
* ``test_post_attachment_409_when_task_running`` — once the task left
  the inbox/queued buckets the upload is forbidden.
* ``test_executor_prompt_includes_attachments`` — ``_build_prompt``
  renders attachment paths relative to the project root so the adapter
  can ``Read`` them as context.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.api.deps import get_session
from app.executor.core import _build_prompt
from app.models import Attachment, Project, Task


def _make_project(client, local_path: str) -> dict[str, Any]:
    payload = {
        "slug": "demo",
        "name": "Demo",
        "kind": "library",
        "local_path": local_path,
    }
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _make_task(client, slug: str = "demo", title: str = "with files") -> dict[str, Any]:
    response = client.post(
        f"/api/projects/{slug}/tasks",
        json={"title": title},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _force_status(app, task_id: int, new_status: str) -> None:
    override = app.dependency_overrides[get_session]
    generator = override()
    session = next(generator)
    try:
        session.execute(
            text("UPDATE tasks SET status = :s WHERE id = :tid"),
            {"s": new_status, "tid": task_id},
        )
        session.commit()
    finally:
        generator.close()


def test_post_attachment_writes_file_and_row(
    client, app, tmp_path: Path
) -> None:
    _make_project(client, local_path=str(tmp_path))
    task = _make_task(client)

    files = {"file": ("spec.md", io.BytesIO(b"# spec\nhello"), "text/markdown")}
    response = client.post(
        f"/api/tasks/{task['id']}/attachments",
        files=files,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["filename"] == "spec.md"
    assert body["content_type"] == "text/markdown"
    assert body["size_bytes"] == len(b"# spec\nhello")
    assert body["task_id"] == task["id"]

    expected = (
        tmp_path / ".niwa" / "attachments" / f"task-{task['id']}" / "spec.md"
    )
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
    client, tmp_path: Path, filename: str
) -> None:
    _make_project(client, local_path=str(tmp_path))
    task = _make_task(client)

    files = {"file": (filename, io.BytesIO(b"x"), "text/plain")}
    response = client.post(
        f"/api/tasks/{task['id']}/attachments",
        files=files,
    )
    assert response.status_code == 400, response.text
    assert not (tmp_path / ".niwa").exists()


def test_post_attachment_409_when_task_running(
    client, app, tmp_path: Path
) -> None:
    _make_project(client, local_path=str(tmp_path))
    task = _make_task(client)
    _force_status(app, task["id"], "running")

    files = {"file": ("note.txt", io.BytesIO(b"x"), "text/plain")}
    response = client.post(
        f"/api/tasks/{task['id']}/attachments",
        files=files,
    )
    assert response.status_code == 409


def test_executor_prompt_includes_attachments(tmp_path: Path) -> None:
    """``_build_prompt`` must render attachment paths relative to the cwd."""

    project = Project(
        slug="p",
        name="P",
        kind="library",
        local_path=str(tmp_path),
    )
    task = Task(
        project_id=1,
        title="use the spec",
        description="ship it",
        status="queued",
    )
    task.id = 7
    task.project = project

    storage = tmp_path / ".niwa" / "attachments" / "task-7"
    storage.mkdir(parents=True)
    (storage / "spec.md").write_bytes(b"x")
    (storage / "mockup.png").write_bytes(b"y")

    attachments = [
        Attachment(
            task_id=7,
            filename="spec.md",
            content_type="text/markdown",
            size_bytes=1,
            storage_path=str(storage / "spec.md"),
        ),
        Attachment(
            task_id=7,
            filename="mockup.png",
            content_type="image/png",
            size_bytes=1,
            storage_path=str(storage / "mockup.png"),
        ),
    ]

    prompt = _build_prompt(task, attachments)
    assert "use the spec" in prompt
    assert "ship it" in prompt
    assert "## Attached files" in prompt
    assert ".niwa/attachments/task-7/spec.md" in prompt
    assert ".niwa/attachments/task-7/mockup.png" in prompt
