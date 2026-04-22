"""Pure functions over ``Session`` for the ``Task`` resource.

The HTTP layer translates the domain-level exceptions raised here
(``TaskNotFound``, ``ProjectNotFound``, ``TaskNotDeletable``) into HTTP
statuses. ``task_events`` rows are written inside the same unit of work as
the task itself — the API should never see an event without its task.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Project, Task, TaskEvent
from ..schemas import TaskCreate
from .projects import ProjectNotFound, get_project


# Statuses that block ``DELETE`` — the executor still owns the lifecycle,
# so the user must cancel explicitly before removing an active task.
ACTIVE_STATUSES: frozenset[str] = frozenset({"running", "waiting_input"})


class TaskNotFound(Exception):
    """Raised when a task id lookup does not match any row."""


class TaskNotDeletable(Exception):
    """Raised when a task cannot be deleted because it is still active."""


class TaskNotWaitingInput(Exception):
    """Raised when ``respond`` targets a task whose status is not ``waiting_input``."""


def list_tasks_for_project(session: Session, slug: str) -> list[Task]:
    """Return every task for ``slug`` ordered by creation time.

    Raises ``ProjectNotFound`` when the slug does not exist so the API can
    respond ``404`` instead of falsely returning an empty list for a
    non-existent project.
    """

    project = get_project(session, slug)
    stmt = (
        select(Task)
        .where(Task.project_id == project.id)
        .order_by(Task.created_at.asc(), Task.id.asc())
    )
    return list(session.scalars(stmt).all())


def get_task(session: Session, task_id: int) -> Task:
    """Return the task with the given id or raise ``TaskNotFound``."""

    task = session.get(Task, task_id)
    if task is None:
        raise TaskNotFound(task_id)
    return task


def create_task(session: Session, slug: str, payload: TaskCreate) -> Task:
    """Insert a new task in ``queued`` state under the given project.

    Writes two ``task_events`` rows in the same commit: a ``created`` event
    carrying the task title and a ``status_changed`` event transitioning
    ``null → queued``. If the event writes fail the task must not exist,
    hence the single ``session.commit()`` at the end.
    """

    project = get_project(session, slug)

    # The DB column is NOT NULL (PR-V1-02 migration); store an empty string
    # when the caller omits the description. TaskRead exposes the field as
    # ``str | None`` per the brief, so clients still see text or empty.
    description = payload.description if payload.description is not None else ""

    task = Task(
        project_id=project.id,
        parent_task_id=None,
        title=payload.title,
        description=description,
        status="queued",
    )
    session.add(task)
    session.flush()  # obtain task.id without committing.

    session.add(
        TaskEvent(
            task_id=task.id,
            kind="created",
            message=payload.title,
            payload_json=None,
        )
    )
    session.add(
        TaskEvent(
            task_id=task.id,
            kind="status_changed",
            message=None,
            payload_json=json.dumps({"from": None, "to": "queued"}),
        )
    )

    session.commit()
    session.refresh(task)
    return task


def delete_task(session: Session, task_id: int) -> None:
    """Delete a task; reject the call if it is still active.

    Cascade on the FKs (see ``app/models/task.py`` and the initial migration)
    takes care of ``task_events``, ``runs`` and ``run_events``.
    """

    task = get_task(session, task_id)
    if task.status in ACTIVE_STATUSES:
        raise TaskNotDeletable(task.status)
    session.delete(task)
    session.commit()


def respond_to_task(session: Session, task_id: int, response: str) -> Task:
    """Deliver a user response to a task parked in ``waiting_input`` (PR-V1-19).

    Writes two ``task_events`` rows in the same commit — a ``message``
    event carrying the user text for audit, followed by a
    ``status_changed`` transition back to ``queued`` — clears
    ``pending_question`` and hands the task back to the executor queue.

    Sole owner of clearing ``pending_question`` on the resume path: by
    the time ``run_adapter`` picks the task up the field is already
    ``None``, so the executor's ``_finalize`` does not touch it.
    """

    task = get_task(session, task_id)
    if task.status != "waiting_input":
        raise TaskNotWaitingInput(task.status)

    from_status = task.status
    task.status = "queued"
    task.pending_question = None

    session.add(
        TaskEvent(
            task_id=task.id,
            kind="message",
            message=None,
            payload_json=json.dumps(
                {"event": "user_response", "text": response}
            ),
        )
    )
    session.add(
        TaskEvent(
            task_id=task.id,
            kind="status_changed",
            message=None,
            payload_json=json.dumps({"from": from_status, "to": "queued"}),
        )
    )
    session.commit()
    session.refresh(task)
    return task


__all__ = [
    "ACTIVE_STATUSES",
    "ProjectNotFound",
    "TaskNotDeletable",
    "TaskNotFound",
    "TaskNotWaitingInput",
    "create_task",
    "delete_task",
    "get_task",
    "list_tasks_for_project",
    "respond_to_task",
]
