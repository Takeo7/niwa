"""FastAPI auth dependencies.

When auth is disabled (no password file), all requests pass through.
When enabled, a valid session cookie or Bearer token is required.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..api.deps import get_session
from ..models.api_token import ApiToken
from .password_file import is_auth_enabled
from .session_store import validate_session
from .token_store import validate_token


def _get_token_from_request(request: Request, db: Session) -> ApiToken | None:
    """Extract and validate a Bearer token from the Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return validate_token(db, auth[7:])


def require_auth(
    request: Request,
    db: Session = Depends(get_session),
) -> ApiToken | None:
    """Pass when auth is disabled, session cookie valid, or Bearer token valid."""
    if not is_auth_enabled():
        return None

    cookie = request.cookies.get("niwa_session")
    if cookie and validate_session(db, cookie):
        return None

    token = _get_token_from_request(request, db)
    if token is not None:
        return token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_scope(scope: str):
    """Return a dependency that requires a specific scope on the API token.

    Cookie (session) auth grants all scopes; token auth is scope-checked.
    """

    def _dep(
        request: Request,
        db: Session = Depends(get_session),
    ) -> None:
        if not is_auth_enabled():
            return

        cookie = request.cookies.get("niwa_session")
        if cookie and validate_session(db, cookie):
            return

        token = _get_token_from_request(request, db)
        if token is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

        token_scopes = set(token.scopes.split())
        if "admin" in token_scopes or scope in token_scopes:
            return

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Scope '{scope}' required",
        )

    return _dep
