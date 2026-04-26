"""Attachments storage helpers (PR-V1-33).

Storage layout: ``<project.local_path>/.niwa/attachments/task-<id>/``.
Filename sanitization is intentionally narrow — reject path traversal
(``..``, ``/``, ``\\``, NUL) and obvious abuse, then keep the original
name. Unicode niceties are left to the OS per brief §Riesgos.

Collisions get a ``__N`` suffix before the extension; the table stores
the resolved on-disk name + absolute path.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Attachment, Task
from .tasks import TaskNotFound, get_task


# Statuses where the user is still allowed to mutate the attachment set.
# Once the executor took over the task, the disk layout is frozen so the
# adapter sees a stable cwd.
EDITABLE_STATUSES: frozenset[str] = frozenset({"inbox", "queued"})


class AttachmentError(Exception):
    """Base class for attachment-domain errors mapped to HTTP statuses."""


class InvalidFilename(AttachmentError):
    """Sanitization rejected the upload filename (path traversal, NUL, …)."""


class TaskNotAcceptingAttachments(AttachmentError):
    """Task already left ``inbox``/``queued`` — uploads are frozen."""


class AttachmentNotFound(AttachmentError):
    """Lookup by attachment id missed."""


# Forbidden filename payloads — any match → 400. Brief §Sanitización.
_FORBIDDEN_FRAGMENTS = ("..", "/", "\\", "\x00")


def sanitize_filename(name: str) -> str:
    """Strip directories + reject traversal. Returns the safe basename.

    Raises ``InvalidFilename`` when the input contains forbidden
    fragments or collapses to an empty string. The function is pure.
    """

    if not name:
        raise InvalidFilename("empty filename")
    for frag in _FORBIDDEN_FRAGMENTS:
        if frag in name:
            raise InvalidFilename(f"filename contains forbidden fragment: {frag!r}")
    # Defensive: even though we rejected separators above, run basename
    # in case a future relaxation of the rules forgets to.
    safe = os.path.basename(name).strip()
    if not safe or safe in {".", ".."}:
        raise InvalidFilename("filename collapses to invalid basename")
    return safe


def _attachment_dir(local_path: str, task_id: int) -> Path:
    return Path(local_path) / ".niwa" / "attachments" / f"task-{task_id}"


def _resolve_unique_path(directory: Path, filename: str) -> Path:
    """Append ``__N`` to ``filename`` until the resulting path is free.

    Splits on the *last* dot so ``foo.tar.gz`` becomes ``foo.tar__1.gz``
    — close enough for human-friendly listings without parsing every
    multi-extension special case.
    """

    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, dot, ext = filename.rpartition(".")
    if not dot:
        stem, ext = filename, ""
    suffix = f".{ext}" if ext else ""
    n = 1
    while True:
        candidate = directory / f"{stem}__{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def list_attachments(session: Session, task_id: int) -> list[Attachment]:
    """Return every attachment for ``task_id`` in insertion order."""

    get_task(session, task_id)  # raises TaskNotFound
    stmt = (
        select(Attachment)
        .where(Attachment.task_id == task_id)
        .order_by(Attachment.id.asc())
    )
    return list(session.scalars(stmt).all())


def create_attachment(
    session: Session,
    task_id: int,
    *,
    filename: str,
    content_type: str | None,
    stream: BinaryIO,
) -> Attachment:
    """Persist ``stream`` to disk + insert the metadata row.

    Raises:
      ``TaskNotFound``                  → 404.
      ``InvalidFilename``               → 400 (path traversal etc.).
      ``TaskNotAcceptingAttachments``   → 409 (task already started).
    """

    task = get_task(session, task_id)
    if task.status not in EDITABLE_STATUSES:
        raise TaskNotAcceptingAttachments(task.status)

    safe_name = sanitize_filename(filename)
    project = task.project
    local_path = project.local_path if project is not None else ""
    if not local_path:
        raise AttachmentError("project has no local_path")

    directory = _attachment_dir(local_path, task_id)
    directory.mkdir(parents=True, exist_ok=True)
    target = _resolve_unique_path(directory, safe_name)

    size = 0
    with target.open("wb") as fh:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            size += len(chunk)

    attachment = Attachment(
        task_id=task_id,
        filename=target.name,
        content_type=content_type,
        size_bytes=size,
        storage_path=str(target.resolve()),
    )
    session.add(attachment)
    session.commit()
    session.refresh(attachment)
    return attachment


def delete_attachment(session: Session, task_id: int, attachment_id: int) -> None:
    """Remove the row + the file. 409 once the task left editable states."""

    task = get_task(session, task_id)
    if task.status not in EDITABLE_STATUSES:
        raise TaskNotAcceptingAttachments(task.status)

    row = session.get(Attachment, attachment_id)
    if row is None or row.task_id != task_id:
        raise AttachmentNotFound(attachment_id)

    try:
        Path(row.storage_path).unlink(missing_ok=True)
    except OSError:
        # Best-effort: even if disk delete fails we still want the row
        # gone so the UI does not show a phantom attachment.
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
