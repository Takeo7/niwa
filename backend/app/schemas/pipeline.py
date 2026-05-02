"""Read schemas for persisted task plan/review records."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


PlanStatus = Literal["ready", "approved", "rejected", "superseded"]
ReviewDecision = Literal["approved", "request_changes"]


class TaskPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    status: PlanStatus
    summary: str
    steps: list[str]
    risks: list[str]
    planner: str
    raw_json: str
    created_at: datetime


class TaskReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    run_id: int | None
    decision: ReviewDecision
    summary: str
    findings: list[str]
    reviewer: str
    raw_json: str
    created_at: datetime
