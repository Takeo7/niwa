"""API token model — hashed tokens with scopes for external/MCP clients."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, Text, func

from ..db import Base

VALID_SCOPES = frozenset(
    {"read", "task:create", "task:write", "merge", "deploy", "admin"}
)


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    scopes = Column(Text, nullable=False, default="read")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
