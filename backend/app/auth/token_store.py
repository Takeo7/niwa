"""API token management — create, validate, revoke."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session as DBSession

from ..models.api_token import ApiToken

_PREFIX = "niwa_"


def create_token(db: DBSession, name: str, scopes: list[str]) -> tuple[str, ApiToken]:
    """Create a new API token. Returns (raw_token, ApiToken model).

    The raw token is only returned once; the stored hash cannot be reversed.
    """
    raw = _PREFIX + secrets.token_hex(32)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    row = ApiToken(name=name, token_hash=token_hash, scopes=" ".join(scopes))
    db.add(row)
    db.commit()
    db.refresh(row)
    return raw, row


def validate_token(db: DBSession, raw: str) -> ApiToken | None:
    """Return the ApiToken if valid and not revoked; update last_used_at."""
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    row = (
        db.query(ApiToken)
        .filter(ApiToken.token_hash == token_hash, ApiToken.revoked_at.is_(None))
        .first()
    )
    if row is None:
        return None
    row.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return row


def revoke_token(db: DBSession, token_id: int) -> ApiToken | None:
    row = db.get(ApiToken, token_id)
    if row is None or row.revoked_at is not None:
        return None
    row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return row


def list_tokens(db: DBSession) -> list[ApiToken]:
    return db.query(ApiToken).filter(ApiToken.revoked_at.is_(None)).all()
