"""Pydantic schemas for the project pulls endpoint (PR-V1-34).

The wire contract is snake_case Pydantic, not raw ``gh`` JSON. The service
layer (``app.services.github_pulls``) maps the camelCase payload from
``gh pr list --json`` into these shapes and collapses
``statusCheckRollup`` (a heterogeneous array of check runs) into a single
``check_state`` literal. Frontend (PR-V1-34b) consumes this contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


CheckState = Literal["failing", "pending", "passing", "none"]


class PullCheck(BaseModel):
    """Collapsed CI status for a pull request.

    ``statusCheckRollup`` from gh is a list of check runs with mixed
    ``conclusion`` / ``status`` / ``state`` fields depending on whether
    they are GitHub Actions, status contexts, or status check rollups.
    The service collapses them by priority
    ``failing > pending > passing > none`` so the table column shows a
    single icon.
    """

    model_config = ConfigDict(extra="forbid")

    state: CheckState


class PullRead(BaseModel):
    """Response item for ``GET /api/projects/{slug}/pulls``.

    Mirrors gh's payload but with snake_case field names. ``state`` and
    ``mergeable`` keep gh's enum casing (``OPEN`` / ``MERGEABLE`` / ...)
    because the frontend renders them as badges and the strings are
    user-facing.
    """

    model_config = ConfigDict(extra="forbid")

    number: int
    title: str
    state: str
    url: str
    mergeable: str
    checks: PullCheck
    head_ref_name: str
    created_at: datetime
    updated_at: datetime


class PullsResponse(BaseModel):
    """Envelope returned by the endpoint.

    ``warning`` is set when no shell-out happened (no/invalid remote);
    ``pulls`` is then an empty list. Errors (``gh`` missing, command
    failed, timeout) bubble up as non-200 status codes instead.
    """

    model_config = ConfigDict(extra="forbid")

    pulls: list[PullRead]
    warning: str | None = None


__all__ = ["CheckState", "PullCheck", "PullRead", "PullsResponse"]
