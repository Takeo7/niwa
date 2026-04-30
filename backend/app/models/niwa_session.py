"""Server-side session model (HttpOnly cookie sessions)."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, func

from ..db import Base


class NiwaSession(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
