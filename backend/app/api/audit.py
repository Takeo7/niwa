"""Audit log API — read-only endpoint for the audit trail (Phase 6, SEC-02)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..auth.deps import require_auth
from ..services.audit import list_events
from .deps import get_session

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_type: str
    actor_id: str | None
    action: str
    target_type: str | None
    target_id: str | None
    payload_json: str | None
    ip_address: str | None
    created_at: datetime


@router.get(
    "/events",
    response_model=list[AuditEventRead],
    dependencies=[Depends(require_auth)],
)
def get_audit_events(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    actor_type: str | None = None,
    action: str | None = None,
    db: Session = Depends(get_session),
) -> list[AuditEventRead]:
    rows = list_events(
        db,
        limit=limit,
        offset=offset,
        actor_type=actor_type,
        action=action,
    )
    return [AuditEventRead.model_validate(r) for r in rows]
