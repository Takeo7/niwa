"""``GET /api/readiness`` — composed health snapshot for ``/system``.

Sync ``def`` so FastAPI runs it in the threadpool (safe for ``subprocess``
in ``check_git``). Read-only, local state only.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from ..config import load_settings
from ..services import readiness_checks as svc


class ReadinessDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db: dict[str, Any]
    claude_cli: dict[str, Any]
    git: dict[str, Any]
    gh: dict[str, Any]


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db_ok: bool
    claude_cli_ok: bool
    git_ok: bool
    gh_ok: bool
    details: ReadinessDetails


router = APIRouter(prefix="/readiness", tags=["readiness"])


@router.get("", response_model=ReadinessResponse)
def get_readiness() -> ReadinessResponse:
    settings = load_settings()
    db_ok, db_details = svc.check_db(settings.db_path)
    cli_ok, cli_details = svc.check_claude_cli(settings.claude_cli)
    git_ok, git_details = svc.check_git()
    gh_ok, gh_details = svc.check_gh()
    return ReadinessResponse(
        db_ok=db_ok,
        claude_cli_ok=cli_ok,
        git_ok=git_ok,
        gh_ok=gh_ok,
        details=ReadinessDetails(
            db=db_details, claude_cli=cli_details, git=git_details, gh=gh_details
        ),
    )
