"""Audit log service — write and query audit events (Phase 6, SEC-03)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..models.audit_event import AuditEvent


def log_event(
    db: Session,
    *,
    actor_type: str,
    action: str,
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    payload: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditEvent:
    """Write a single audit event. Commits immediately."""
    event = AuditEvent(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        payload_json=json.dumps(payload) if payload else None,
        ip_address=ip_address,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def list_events(
    db: Session,
    *,
    limit: int = 100,
    offset: int = 0,
    actor_type: str | None = None,
    action: str | None = None,
) -> list[AuditEvent]:
    q = db.query(AuditEvent)
    if actor_type:
        q = q.filter(AuditEvent.actor_type == actor_type)
    if action:
        q = q.filter(AuditEvent.action == action)
    return q.order_by(AuditEvent.id.desc()).offset(offset).limit(limit).all()
