"""Wrapper around ``gh pr list --json`` (PR-V1-34, project pulls view).

The ``GET /api/projects/{slug}/pulls`` endpoint shells out here. We keep
the wire format raw on purpose — the frontend table maps gh's enum
casing (OPEN/MERGED/MERGEABLE/...) directly so a future schema bump in
gh requires changing both ends together rather than adding a translation
layer here. Read-only: never mutates refs and never calls ``gh pr
merge`` (PR-V1-35); ``GhUnavailable`` maps to 503 + install hint,
``GhCommandFailed`` (rc != 0 / timeout / parse error) maps to 502.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from typing import Any


logger = logging.getLogger("niwa.github_pulls")

_GH_TIMEOUT_S = 15
_GH_LIMIT = 30
_NIWA_BRANCH_PREFIX = "niwa/task-"

# Accepts ``https://github.com/owner/repo[.git]`` and
# ``git@github.com:owner/repo[.git]``; trailing ``.git`` optional.
_REMOTE_RE = re.compile(
    r"(?:github\.com[:/])([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?$"
)


class GhUnavailable(RuntimeError):
    """``gh`` is not on PATH; API maps to 503."""


class GhCommandFailed(RuntimeError):
    """``gh pr list`` exited non-zero, timed out, or returned invalid JSON."""


def parse_owner_repo(remote: str) -> tuple[str, str] | None:
    """``(owner, repo)`` from a GitHub remote URL, or ``None`` for
    unsupported shapes (self-hosted, gitlab, mirrors)."""

    match = _REMOTE_RE.search(remote.strip())
    return (match.group(1), match.group(2)) if match else None


def list_pulls(
    *, owner: str, repo: str, state: str = "open", include_all: bool = False
) -> list[dict[str, Any]]:
    """Run ``gh pr list`` for ``owner/repo`` and return parsed pulls.

    Default filters to PRs whose ``headRefName`` starts with
    ``niwa/task-`` so the user sees only branches Niwa opened.
    """

    if shutil.which("gh") is None:
        raise GhUnavailable("gh CLI not installed")

    argv = [
        "gh", "pr", "list",
        "--repo", f"{owner}/{repo}",
        "--state", state,
        "--json",
        "number,title,state,url,mergeable,statusCheckRollup,"
        "createdAt,updatedAt,headRefName",
        "--limit", str(_GH_LIMIT),
    ]
    logger.info("gh cmd argv=%s", argv)
    try:
        proc = subprocess.run(
            argv, check=False, capture_output=True, text=True,
            timeout=_GH_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GhCommandFailed(f"gh pr list failed: {exc}") from exc
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()[:500]
        raise GhCommandFailed(f"gh pr list rc={proc.returncode} stderr={stderr}")
    try:
        parsed = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise GhCommandFailed(f"gh pr list returned non-JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise GhCommandFailed("gh pr list payload was not a JSON array")

    if include_all:
        return parsed
    return [
        item for item in parsed
        if isinstance(item, dict)
        and isinstance(item.get("headRefName"), str)
        and item["headRefName"].startswith(_NIWA_BRANCH_PREFIX)
    ]


__all__ = [
    "GhCommandFailed", "GhUnavailable", "list_pulls", "parse_owner_repo",
]
