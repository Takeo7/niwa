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

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from ..schemas import AttachmentRead, RunRead, TaskCreate, TaskRead, TaskRespondPayload
from ..services import attachments as attachments_service
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


@tasks_router.post("/{task_id}/respond", response_model=TaskRead)
def respond_to_task(
    task_id: int,
    payload: TaskRespondPayload,
    session: Session = Depends(get_session),
) -> TaskRead:
    """Deliver a user response to a task parked in ``waiting_input``.

    PR-V1-19 closes the clarification round-trip: the endpoint moves the
    task back to ``queued`` and logs the user text as a ``message``
    event. Known limitation: the next adapter run does **not** receive
    this response — composite prompt is deferred to a follow-up, the
    event is stored for audit only.
    """

    try:
        task = service.respond_to_task(session, task_id, payload.response)
    except service.TaskNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="task not found",
        )
    except service.TaskNotWaitingInput:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task is not waiting for input",
        )
    return TaskRead.model_validate(task)


# ---- Attachments (PR-V1-33) -------------------------------------------------


@tasks_router.get(
    "/{task_id}/attachments",
    response_model=list[AttachmentRead],
)
def list_attachments(
    task_id: int,
    session: Session = Depends(get_session),
) -> list[AttachmentRead]:
    try:
        rows = attachments_service.list_attachments(session, task_id)
    except service.TaskNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="task not found",
        )
    return [AttachmentRead.model_validate(row) for row in rows]


@tasks_router.post(
    "/{task_id}/attachments",
    response_model=AttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_attachment(
    task_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> AttachmentRead:
    try:
        row = attachments_service.create_attachment(
            session,
            task_id,
            filename=file.filename or "",
            content_type=file.content_type,
            stream=file.file,
        )
    except service.TaskNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="task not found",
        )
    except attachments_service.InvalidFilename as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except attachments_service.TaskNotAcceptingAttachments:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="task already started; attachments are frozen",
        )
    return AttachmentRead.model_validate(row)


@tasks_router.delete(
    "/{task_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_attachment(
    task_id: int,
    attachment_id: int,
    session: Session = Depends(get_session),
) -> Response:
    try:
        attachments_service.delete_attachment(session, task_id, attachment_id)
    except service.TaskNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="task not found",
        )
    except attachments_service.AttachmentNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="attachment not found",
        )
    except attachments_service.TaskNotAcceptingAttachments:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="task already started; attachments are frozen",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
