"""MCP task tools — task_list, task_create, task_status, task_respond, cancel, retry."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ...schemas.task import TaskCreate
from ...services import tasks as service


def _task_dict(task: Any) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "branch_name": task.branch_name,
        "pr_url": task.pr_url,
        "pending_question": task.pending_question,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


def task_list(db: Session, project_slug: str) -> list[dict[str, Any]]:
    try:
        tasks = service.list_tasks_for_project(db, project_slug)
    except service.ProjectNotFound:
        raise HTTPException(status_code=404, detail=f"Project '{project_slug}' not found")
    return [_task_dict(t) for t in tasks]


def task_create(
    db: Session,
    project_slug: str,
    title: str,
    description: str | None = None,
) -> dict[str, Any]:
    try:
        task = service.create_task(
            db,
            project_slug,
            TaskCreate(title=title, description=description),
        )
    except service.ProjectNotFound:
        raise HTTPException(status_code=404, detail=f"Project '{project_slug}' not found")
    return _task_dict(task)


def task_status(db: Session, task_id: int) -> dict[str, Any]:
    try:
        task = service.get_task(db, task_id)
    except service.TaskNotFound:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return _task_dict(task)


def task_respond(db: Session, task_id: int, response: str) -> dict[str, Any]:
    try:
        task = service.respond_to_task(db, task_id, response)
    except service.TaskNotFound:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    except service.TaskNotWaitingInput:
        raise HTTPException(status_code=409, detail="Task is not waiting for input")
    return _task_dict(task)


def task_cancel(db: Session, task_id: int) -> dict[str, Any]:
    try:
        task = service.cancel_task(db, task_id)
    except service.TaskNotFound:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    except service.TaskNotCancellable:
        raise HTTPException(status_code=409, detail="Task cannot be cancelled in its current state")
    return _task_dict(task)


def task_retry(db: Session, task_id: int) -> dict[str, Any]:
    try:
        task = service.retry_task(db, task_id)
    except service.TaskNotFound:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    except service.TaskNotRetryable:
        raise HTTPException(status_code=409, detail="Task cannot be retried in its current state")
    return _task_dict(task)
