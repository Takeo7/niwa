"""Attachments storage helpers (PR-V1-33).

Files land at ``<project.local_path>/.niwa/attachments/task-<id>/``.
Filename sanitization rejects path traversal (``..``, ``/``, ``\\``,
NUL); collisions get a ``__N`` suffix before the extension.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Attachment
from .tasks import TaskNotFound, get_task


# Statuses where the user can still mutate the attachment set; once the
# executor took over, disk layout is frozen for the adapter cwd.
EDITABLE_STATUSES: frozenset[str] = frozenset({"inbox", "queued"})
_FORBIDDEN = ("..", "/", "\\", "\x00")


class AttachmentError(Exception):
    """Base class mapped to HTTP statuses by the API layer."""


class InvalidFilename(AttachmentError):
    """Sanitization rejected the upload filename."""


class TaskNotAcceptingAttachments(AttachmentError):
    """Task already left ``inbox``/``queued`` — uploads are frozen."""


class AttachmentNotFound(AttachmentError):
    """Lookup by attachment id missed."""


def sanitize_filename(name: str) -> str:
    """Reject traversal payloads and return the safe basename."""

    if not name:
        raise InvalidFilename("empty filename")
    if any(frag in name for frag in _FORBIDDEN):
        raise InvalidFilename(f"forbidden fragment in filename: {name!r}")
    safe = os.path.basename(name).strip()
    if not safe or safe in {".", ".."}:
        raise InvalidFilename("filename collapses to invalid basename")
    return safe


def list_attachments(session: Session, task_id: int) -> list[Attachment]:
    get_task(session, task_id)  # raises TaskNotFound
    stmt = select(Attachment).where(Attachment.task_id == task_id).order_by(
        Attachment.id.asc()
    )
    return list(session.scalars(stmt).all())


def _require_editable_task(session: Session, task_id: int):
    task = get_task(session, task_id)
    if task.status not in EDITABLE_STATUSES:
        raise TaskNotAcceptingAttachments(task.status)
    return task


def create_attachment(
    session: Session,
    task_id: int,
    *,
    filename: str,
    content_type: str | None,
    stream: BinaryIO,
) -> Attachment:
    task = _require_editable_task(session, task_id)
    safe_name = sanitize_filename(filename)
    local_path = task.project.local_path if task.project is not None else ""
    if not local_path:
        raise AttachmentError("project has no local_path")

    directory = Path(local_path) / ".niwa" / "attachments" / f"task-{task_id}"
    directory.mkdir(parents=True, exist_ok=True)

    # Dedup ``foo.tar.gz`` → ``foo.tar__1.gz`` (last-dot split is good
    # enough for listings without per-extension parsing).
    target = directory / safe_name
    if target.exists():
        stem, dot, ext = safe_name.rpartition(".")
        if not dot:
            stem, ext = safe_name, ""
        suffix = f".{ext}" if ext else ""
        n = 1
        while (target := directory / f"{stem}__{n}{suffix}").exists():
            n += 1

    size = 0
    with target.open("wb") as fh:
        while chunk := stream.read(64 * 1024):
            fh.write(chunk)
            size += len(chunk)

    row = Attachment(
        task_id=task_id,
        filename=target.name,
        content_type=content_type,
        size_bytes=size,
        storage_path=str(target.resolve()),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_attachment(session: Session, task_id: int, attachment_id: int) -> None:
    _require_editable_task(session, task_id)
    row = session.get(Attachment, attachment_id)
    if row is None or row.task_id != task_id:
        raise AttachmentNotFound(attachment_id)
    # Best-effort disk delete — drop the row regardless so the UI does
    # not show a phantom attachment.
    try:
        Path(row.storage_path).unlink(missing_ok=True)
    except OSError:
        pass
    session.delete(row)
    session.commit()


__all__ = [
    "AttachmentError",
    "AttachmentNotFound",
    "EDITABLE_STATUSES",
    "InvalidFilename",
    "TaskNotAcceptingAttachments",
    "TaskNotFound",
    "create_attachment",
    "delete_attachment",
    "list_attachments",
    "sanitize_filename",
]
