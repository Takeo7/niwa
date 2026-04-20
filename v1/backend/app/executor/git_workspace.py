"""Git workspace — one branch per task (PR-V1-08).

The executor calls :func:`prepare_task_branch` right before spawning the
Claude Code adapter. On success the working tree is on
``niwa/task-<id>-<slug>`` and the name is returned so the caller can
persist it on ``Task.branch_name``. On failure a :class:`GitWorkspaceError`
is raised and the executor terminates the run with ``outcome='git_setup_failed'``
without ever invoking the adapter.

Scope for this module (see brief): no commit, no push, no PR. That lives
in the finalize step (PR-V1-11+). Here we only:

* verify the path is a git repo;
* verify the working tree is clean (no stash — the user owns cleanliness);
* create the target branch (or reuse it if it already exists) and check
  it out.

Only stdlib — ``subprocess`` + ``re``.
"""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for typing
    from ..models import Task


_SLUG_MAX_LEN = 30
_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


class GitWorkspaceError(RuntimeError):
    """A git setup step failed — the executor maps this to ``git_setup_failed``."""


def build_branch_name(task: "Task") -> str:
    """Return ``niwa/task-<id>-<slug>`` for ``task``.

    Pure function — no disk, no subprocess. Slug rules (brief):

    * lowercase;
    * ``[^a-z0-9]+`` → ``-``;
    * strip leading/trailing ``-``;
    * truncate to 30 chars;
    * fall back to ``untitled`` if the result is empty.
    """

    title = (task.title or "").lower()
    slug = _SLUG_PATTERN.sub("-", title).strip("-")[:_SLUG_MAX_LEN].strip("-")
    if not slug:
        slug = "untitled"
    return f"niwa/task-{task.id}-{slug}"


def prepare_task_branch(local_path: str, task: "Task") -> str:
    """Create or reuse the task branch and check it out. Returns the name.

    Raises :class:`GitWorkspaceError` if:

    * ``local_path`` is not a git repo;
    * the working tree has uncommitted changes;
    * ``git`` is not on PATH;
    * any git command exits non-zero.
    """

    branch = build_branch_name(task)

    # 1. Must be a git repo. ``rev-parse --is-inside-work-tree`` is the
    #    canonical probe; it also rules out bare repos (we need a work
    #    tree to run the adapter against).
    try:
        inside = _run_git(
            ["rev-parse", "--is-inside-work-tree"], cwd=local_path
        ).stdout.strip()
    except FileNotFoundError as exc:  # git binary missing
        raise GitWorkspaceError("git cli not found in PATH") from exc
    except GitWorkspaceError as exc:
        raise GitWorkspaceError(
            f"not a git repository: {local_path} ({exc})"
        ) from exc
    if inside != "true":
        raise GitWorkspaceError(f"not a git repository: {local_path}")

    # 2. Working tree must be clean. ``status --porcelain`` prints one
    #    line per dirty path; empty output means clean.
    status = _run_git(["status", "--porcelain"], cwd=local_path).stdout
    if status.strip():
        raise GitWorkspaceError(
            "dirty working tree — uncommitted changes present; "
            "clean the repo before queuing tasks"
        )

    # 3. Reuse the branch if it already exists (retry scenario). Otherwise
    #    create from the current HEAD. ``show-ref --verify --quiet`` exits
    #    zero iff the ref exists; we can't use ``check=True`` here because
    #    the non-zero exit is the expected "not found" signal.
    exists = (
        subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=local_path,
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )
    if exists:
        _run_git(["checkout", branch], cwd=local_path)
    else:
        _run_git(["checkout", "-b", branch], cwd=local_path)

    return branch


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    """Run ``git <args>`` in ``cwd``. Failures raise :class:`GitWorkspaceError`.

    Kept as a thin wrapper so tests (and future callers) can patch one
    entry point. ``check=True`` + ``capture_output=True`` + ``text=True``
    is the uniform calling convention — see the brief.
    """

    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip() or exc.stdout or ""
        raise GitWorkspaceError(
            f"git {' '.join(args)} failed: {stderr}"
        ) from exc


__all__ = [
    "GitWorkspaceError",
    "build_branch_name",
    "prepare_task_branch",
]
