"""Wrapper around ``gh pr list --json`` (PR-V1-34, project pulls view).

The ``GET /api/projects/{slug}/pulls`` endpoint shells out here and
receives ``PullRead`` objects (Pydantic, snake_case). Raw gh JSON is
mapped here so the wire contract stays stable across gh schema bumps —
``statusCheckRollup`` (heterogeneous array) is collapsed to a single
``check_state`` literal with priority
``failing > pending > passing > none``. Read-only: never mutates refs
and never calls ``gh pr merge`` (PR-V1-35).

Errors bubble as typed exceptions:
``GhUnavailable`` → 503 (CLI not on PATH);
``GhTimeout``     → 504 (subprocess exceeded ``_GH_TIMEOUT_S``);
``GhCommandFailed`` → 502 (rc != 0, OS error, or non-JSON stdout).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from typing import Any

from ..schemas.pulls import MergeMethod, PullCheck, PullRead


logger = logging.getLogger("niwa.github_pulls")

_GH_TIMEOUT_S = 15
_GH_MERGE_TIMEOUT_S = 30
_GH_LIMIT = 30
_NIWA_BRANCH_PREFIX = "niwa/task-"

# Accepts ``https://github.com/owner/repo[.git]`` and
# ``git@github.com:owner/repo[.git]``. Owner / repo cannot start with
# ``-`` (would otherwise round-trip to ``gh`` and fail noisily).
_REMOTE_RE = re.compile(
    r"(?:github\.com[:/])"
    r"([A-Za-z0-9_][A-Za-z0-9._-]*)/"
    r"([A-Za-z0-9_][A-Za-z0-9._-]*?)"
    r"(?:\.git)?/?$"
)


class GhUnavailable(RuntimeError):
    """``gh`` is not on PATH; API maps to 503."""


class GhTimeout(RuntimeError):
    """``gh pr list`` exceeded ``_GH_TIMEOUT_S``; API maps to 504."""


class GhCommandFailed(RuntimeError):
    """``gh pr list`` exited non-zero or returned invalid JSON; 502."""


class PullNotMergeable(RuntimeError):
    """``gh pr merge`` reported the PR cannot be merged; API maps to 409.

    Triggered when stderr contains gh's ``not mergeable`` phrasing — covers
    conflicts, failing required checks, missing reviews, etc. Distinct
    from ``GhCommandFailed`` so the API layer can surface a 409 instead
    of a 502 (the user can act on conflicts; auth/network they cannot).
    """


def parse_owner_repo(remote: str) -> tuple[str, str] | None:
    """``(owner, repo)`` from a GitHub remote URL, or ``None`` for
    unsupported shapes (self-hosted, gitlab, mirrors)."""

    match = _REMOTE_RE.search(remote.strip())
    return (match.group(1), match.group(2)) if match else None


_CHECK_PRIORITY = ("failing", "pending", "passing", "none")


def _check_state_from_run(run: dict[str, Any]) -> str:
    """Map a single check-run dict to one of the four canonical states.

    gh emits at least three distinct shapes here: GitHub Actions runs
    expose ``status`` + ``conclusion``; status contexts expose ``state``
    (success/failure/pending/error); the rollup itself sometimes shows
    up with a literal ``state`` of ``SUCCESS``/``FAILURE``/``PENDING``.
    Anything we cannot classify is treated as ``none`` so it does not
    dominate the rollup.
    """

    if not isinstance(run, dict):
        return "none"
    conclusion = (run.get("conclusion") or "").lower()
    status = (run.get("status") or "").lower()
    state = (run.get("state") or "").lower()
    if conclusion in {"failure", "timed_out", "cancelled", "action_required"}:
        return "failing"
    if state in {"failure", "error"}:
        return "failing"
    if conclusion == "success" or state == "success":
        return "passing"
    if status in {"queued", "in_progress", "waiting", "pending"}:
        return "pending"
    if state == "pending":
        return "pending"
    return "none"


def collapse_check_state(rollup: Any) -> str:
    """Reduce ``statusCheckRollup`` to one of ``failing|pending|passing|none``.

    Priority: ``failing > pending > passing > none``. Empty / missing
    rollups collapse to ``none``.
    """

    if not isinstance(rollup, list) or not rollup:
        return "none"
    states = {_check_state_from_run(run) for run in rollup}
    for candidate in _CHECK_PRIORITY:
        if candidate in states:
            return candidate
    return "none"


def _to_pull_read(item: dict[str, Any]) -> PullRead:
    """Map a single gh JSON entry to ``PullRead`` (snake_case)."""

    return PullRead(
        number=item["number"],
        title=item["title"],
        state=item["state"],
        url=item["url"],
        mergeable=item.get("mergeable") or "UNKNOWN",
        checks=PullCheck(state=collapse_check_state(item.get("statusCheckRollup"))),
        head_ref_name=item["headRefName"],
        created_at=item["createdAt"],
        updated_at=item["updatedAt"],
    )


def list_pulls(
    *, owner: str, repo: str, state: str = "open", include_all: bool = False
) -> list[PullRead]:
    """Run ``gh pr list`` for ``owner/repo`` and return mapped pulls.

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
    logger.debug("gh cmd argv=%s", argv)
    try:
        proc = subprocess.run(
            argv, check=False, capture_output=True, text=True,
            timeout=_GH_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise GhTimeout(f"gh pr list timed out after {_GH_TIMEOUT_S}s") from exc
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

    items = [item for item in parsed if isinstance(item, dict)]
    if not include_all:
        items = [
            item for item in items
            if isinstance(item.get("headRefName"), str)
            and item["headRefName"].startswith(_NIWA_BRANCH_PREFIX)
        ]
    return [_to_pull_read(item) for item in items]


# gh phrases that indicate the PR is blocked from merging in a way the
# user can act on (conflicts, failing checks, missing reviews, draft).
# Matched case-insensitively against stderr to avoid coupling to exact
# wording. Anything outside this set bubbles up as GhCommandFailed (502).
_NOT_MERGEABLE_MARKERS = (
    "not mergeable",
    "is not mergeable",
    "merge conflict",
    "required status check",
    "approving review",
    "is in draft state",
    "draft pull request",
)
# gh phrases that indicate the PR was already merged. Treat as success
# so a double-click on the Merge button is idempotent rather than a 502.
_ALREADY_MERGED_MARKERS = (
    "already been merged",
    "already merged",
)


def _run_gh_merge(argv: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv, check=False, capture_output=True, text=True,
            timeout=_GH_MERGE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise GhTimeout(
            f"gh pr merge timed out after {_GH_MERGE_TIMEOUT_S}s"
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise GhCommandFailed(f"gh pr merge failed: {exc}") from exc


def merge_pull(
    *, owner: str, repo: str, number: int, method: MergeMethod = "squash"
) -> None:
    """Run ``gh pr merge`` for ``owner/repo#number`` (PR-V1-35).

    No ``--auto`` flag: the Merge button is a "merge now" action, not a
    "queue when ready" action. ``--auto`` exits rc=0 having only enabled
    auto-merge when the PR doesn't yet meet branch-protection
    requirements, which would let the endpoint claim ``merged=true``
    while the PR is still open. Without ``--auto``, gh either merges
    immediately (rc=0) or refuses with a stderr explaining why
    (failing checks, missing reviews, conflicts, etc.) — those map to
    409 ``not_mergeable`` so the UI can show the user what to fix.
    Repeated clicks resolve via ``_ALREADY_MERGED_MARKERS``.
    """

    if shutil.which("gh") is None:
        raise GhUnavailable("gh CLI not installed")

    argv = [
        "gh", "pr", "merge", str(number),
        "--repo", f"{owner}/{repo}",
        f"--{method}", "--delete-branch",
    ]
    proc = _run_gh_merge(argv)
    if proc.returncode == 0:
        return
    stderr = (proc.stderr or "").strip()
    stderr_lc = stderr.lower()
    if any(marker in stderr_lc for marker in _ALREADY_MERGED_MARKERS):
        return  # idempotent: the PR is in the desired state
    if any(marker in stderr_lc for marker in _NOT_MERGEABLE_MARKERS):
        raise PullNotMergeable(stderr[:500] or "pull request is not mergeable")
    raise GhCommandFailed(
        f"gh pr merge rc={proc.returncode} stderr={stderr[:500]}"
    )


__all__ = [
    "GhCommandFailed", "GhTimeout", "GhUnavailable", "PullNotMergeable",
    "collapse_check_state", "list_pulls", "merge_pull", "parse_owner_repo",
]
