"""Audit event model — records critical actions (Phase 6, SEC-03)."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, Text, func

from ..db import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True)
    actor_type = Column(String(32), nullable=False)  # "human", "token", "executor"
    actor_id = Column(String(255))  # token name or "session"
    action = Column(String(128), nullable=False)
    target_type = Column(String(64))  # "project", "task", "token", etc.
    target_id = Column(String(255))
    payload_json = Column(Text)
    ip_address = Column(String(64))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
