"""Tasks CRUD endpoints (SPEC §3, brief PR-V1-04).

Four routes, split across two routers because the list/create endpoints
are project-scoped while detail/delete address tasks by their global id:

* ``GET  /api/projects/{slug}/tasks``  → list; ``404`` when the slug is unknown.
* ``POST /api/projects/{slug}/tasks``  → create in ``queued``; ``404`` on slug.
* ``GET  /api/tasks/{task_id}``        → fetch by id; ``404`` when missing.
* ``DELETE /api/tasks/{task_id}``      → remove; ``409`` when the task is
  running/waiting_input, ``204`` otherwise.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..schemas import RunRead, TaskCreate, TaskRead
from ..services import runs as runs_service
from ..services import tasks as service
from .deps import get_session


# Nested router mounted under ``/projects/{slug}/tasks`` for list/create.
project_tasks_router = APIRouter(
    prefix="/projects/{slug}/tasks",
    tags=["tasks"],
)

# Flat router mounted at ``/tasks`` for get/delete by id.
tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])


@project_tasks_router.get("", response_model=list[TaskRead])
def list_tasks(
    slug: str,
    session: Session = Depends(get_session),
) -> list[TaskRead]:
    try:
        rows = service.list_tasks_for_project(session, slug)
    except service.ProjectNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found",
        )
    return [TaskRead.model_validate(row) for row in rows]


@project_tasks_router.post(
    "",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
)
def create_task(
    slug: str,
    payload: TaskCreate,
    session: Session = Depends(get_session),
) -> TaskRead:
    try:
        task = service.create_task(session, slug, payload)
    except service.ProjectNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found",
        )
    return TaskRead.model_validate(task)


@tasks_router.get("/{task_id}", response_model=TaskRead)
def get_task(
    task_id: int,
    session: Session = Depends(get_session),
) -> TaskRead:
    try:
        task = service.get_task(session, task_id)
    except service.TaskNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="task not found",
        )
    return TaskRead.model_validate(task)


@tasks_router.get("/{task_id}/runs", response_model=list[RunRead])
def list_runs_for_task(
    task_id: int,
    session: Session = Depends(get_session),
) -> list[RunRead]:
    """Return every run associated with ``task_id``.

    ``404`` when the task id does not exist. Empty list (``200``) when the
    task exists but has not been picked up by the executor yet.
    """

    try:
        rows = runs_service.list_runs_for_task(session, task_id)
    except service.TaskNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="task not found",
        )
    return [RunRead.model_validate(row) for row in rows]


@tasks_router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: int,
    session: Session = Depends(get_session),
) -> Response:
    try:
        service.delete_task(session, task_id)
    except service.TaskNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="task not found",
        )
    except service.TaskNotDeletable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="task is active; cancel first",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
