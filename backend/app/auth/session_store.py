"""DB-backed session tokens (HttpOnly cookie transport)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as DBSession

from ..models.niwa_session import NiwaSession

_SESSION_TTL_HOURS = 24


def create_session(db: DBSession) -> str:
    """Create a session, persist a hash, and return the raw token."""
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=_SESSION_TTL_HOURS)
    db.add(NiwaSession(token_hash=token_hash, expires_at=expires_at))
    db.commit()
    return token


def validate_session(db: DBSession, token: str) -> bool:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    row = (
        db.query(NiwaSession)
        .filter(NiwaSession.token_hash == token_hash, NiwaSession.expires_at > now)
        .first()
    )
    return row is not None


def delete_session(db: DBSession, token: str) -> None:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = db.query(NiwaSession).filter(NiwaSession.token_hash == token_hash).first()
    if row:
        db.delete(row)
        db.commit()
