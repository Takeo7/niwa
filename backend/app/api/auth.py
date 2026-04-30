"""Auth API — login, logout, me, API token CRUD (Phase 5, NET-01/02)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session

from ..auth.deps import require_auth
from ..auth.hashing import hash_password, verify_password
from ..auth.password_file import get_password_hash, is_auth_enabled, set_password_hash
from ..auth.session_store import create_session, delete_session
from ..auth.token_store import create_token, list_tokens, revoke_token
from ..models.api_token import VALID_SCOPES
from ..services.audit import log_event
from .deps import get_session

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Request / Response schemas ────────────────────────────────────────────────

class LoginRequest(BaseModel):
    password: str


class TokenCreateRequest(BaseModel):
    name: str
    scopes: list[str] = ["read"]

    @field_validator("scopes")
    @classmethod
    def check_scopes(cls, v: list[str]) -> list[str]:
        invalid = set(v) - VALID_SCOPES
        if invalid:
            raise ValueError(f"Unknown scopes: {invalid}. Valid: {sorted(VALID_SCOPES)}")
        return v


class TokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    scopes: str
    created_at: datetime
    last_used_at: datetime | None


class TokenCreateResponse(TokenRead):
    token: str


class SetPasswordRequest(BaseModel):
    password: str
    current_password: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
def auth_status() -> dict:
    """Return whether auth is enabled (safe to call unauthenticated)."""
    return {"enabled": is_auth_enabled()}


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict:
    if not is_auth_enabled():
        raise HTTPException(status_code=400, detail="Auth is not enabled on this instance")
    stored = get_password_hash()
    ip = request.client.host if request.client else None
    if not stored or not verify_password(body.password, stored):
        log_event(db, actor_type="anon", action="login.failed", ip_address=ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_session(db)
    response.set_cookie(
        "niwa_session",
        value=token,
        httponly=True,
        samesite="strict",
        max_age=86400,
        path="/",
    )
    log_event(db, actor_type="user", action="login.success", ip_address=ip)
    return {"ok": True}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict:
    session_token = request.cookies.get("niwa_session")
    if session_token:
        delete_session(db, session_token)
    response.delete_cookie("niwa_session", path="/")
    ip = request.client.host if request.client else None
    log_event(db, actor_type="user", action="logout", ip_address=ip)
    return {"ok": True}


@router.get("/me")
def me(_auth=Depends(require_auth)) -> dict:
    return {"authenticated": True}


@router.post("/set-password", dependencies=[Depends(require_auth)])
def set_password(
    body: SetPasswordRequest,
) -> dict:
    """Set or change the admin password. Requires current password when already set."""
    existing = get_password_hash()
    if existing is not None:
        if body.current_password is None or not verify_password(body.current_password, existing):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password required")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    set_password_hash(hash_password(body.password))
    return {"ok": True}


# ── API Tokens ────────────────────────────────────────────────────────────────

@router.get("/tokens", response_model=list[TokenRead], dependencies=[Depends(require_auth)])
def get_tokens(db: Session = Depends(get_session)) -> list[TokenRead]:
    return [TokenRead.model_validate(t) for t in list_tokens(db)]


@router.post("/tokens", response_model=TokenCreateResponse, dependencies=[Depends(require_auth)])
def create_api_token(
    body: TokenCreateRequest,
    db: Session = Depends(get_session),
) -> TokenCreateResponse:
    raw, token = create_token(db, name=body.name, scopes=body.scopes)
    log_event(
        db,
        actor_type="user",
        action="token.create",
        target_type="api_token",
        target_id=token.id,
        payload={"name": body.name, "scopes": body.scopes},
    )
    return TokenCreateResponse(
        id=token.id,
        name=token.name,
        scopes=token.scopes,
        created_at=token.created_at,
        last_used_at=token.last_used_at,
        token=raw,
    )


@router.delete("/tokens/{token_id}", status_code=204, dependencies=[Depends(require_auth)])
def revoke_api_token(
    token_id: int,
    db: Session = Depends(get_session),
) -> None:
    result = revoke_token(db, token_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Token not found or already revoked")
    log_event(
        db,
        actor_type="user",
        action="token.revoke",
        target_type="api_token",
        target_id=token_id,
    )
