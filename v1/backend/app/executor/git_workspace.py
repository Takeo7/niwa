"""Git workspace — one branch per task (PR-V1-08).

The executor calls :func:`prepare_task_branch` before spawning the
Claude Code adapter. On success the working tree is on
``niwa/task-<id>-<slug>`` and the name is returned for persistence on
``Task.branch_name``. On failure a :class:`GitWorkspaceError` is
raised and the executor finalizes the run with
``outcome='git_setup_failed'`` without invoking the adapter.

Scope: verify repo + clean tree + create-or-reuse branch. No commit,
no push, no PR — those live in the finalize step (PR-V1-11+). Only
stdlib (``subprocess`` + ``re``).
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
    """Return ``niwa/task-<id>-<slug>`` for ``task``. Pure — no I/O.

    Slug rules: lowercase, ``[^a-z0-9]+`` → ``-``, strip ``-`` from
    edges, truncate to 30 chars, fall back to ``untitled`` when empty.
    """

    title = (task.title or "").lower()
    slug = _SLUG_PATTERN.sub("-", title).strip("-")[:_SLUG_MAX_LEN].strip("-")
    return f"niwa/task-{task.id}-{slug or 'untitled'}"


def prepare_task_branch(local_path: str, task: "Task") -> str:
    """Create or reuse the task branch and check it out. Returns the name.

    Raises :class:`GitWorkspaceError` when ``local_path`` is not a git
    repo, the working tree is dirty, ``git`` is missing from PATH, or
    any git command exits non-zero.
    """

    branch = build_branch_name(task)

    # ``rev-parse --is-inside-work-tree`` also rejects bare repos.
    try:
        inside = _run_git(
            ["rev-parse", "--is-inside-work-tree"], cwd=local_path
        ).stdout.strip()
    except FileNotFoundError as exc:
        raise GitWorkspaceError("git cli not found in PATH") from exc
    except GitWorkspaceError as exc:
        raise GitWorkspaceError(
            f"not a git repository: {local_path} ({exc})"
        ) from exc
    if inside != "true":
        raise GitWorkspaceError(f"not a git repository: {local_path}")

    if _run_git(["status", "--porcelain"], cwd=local_path).stdout.strip():
        raise GitWorkspaceError(
            "dirty working tree — clean the repo before queuing tasks"
        )

    # ``show-ref --verify --quiet`` exits non-zero when the ref is
    # missing; that's the expected "create new branch" signal, so we
    # can't use ``check=True`` here.
    exists = (
        subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=local_path,
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )
    _run_git(
        ["checkout", branch] if exists else ["checkout", "-b", branch],
        cwd=local_path,
    )
    return branch


def _detect_default_branch(local_path: str) -> str:
    """Return the repo's default branch name.

    Detection order: ``origin/HEAD`` symbolic-ref, then local ``main``,
    then local ``master``, then the first local branch listed by
    ``git branch``. Raises :class:`GitWorkspaceError` if none match —
    the caller has no reasonable base to branch from.
    """

    head = subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        cwd=local_path,
        capture_output=True,
        text=True,
    )
    if head.returncode == 0:
        ref = head.stdout.strip()
        if ref:
            return ref.rsplit("/", 1)[-1]

    for candidate in ("main", "master"):
        probe = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"],
            cwd=local_path,
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            return candidate

    listing = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"],
        cwd=local_path,
        capture_output=True,
        text=True,
    )
    if listing.returncode == 0:
        for line in listing.stdout.splitlines():
            name = line.strip()
            if name:
                return name

    raise GitWorkspaceError("no default branch detected")


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    """Run ``git <args>`` in ``cwd`` with ``check=True``.

    Failures raise :class:`GitWorkspaceError` with the captured stderr.
    A single entry point keeps future mocking/patching trivial.
    """

    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
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
    "_detect_default_branch",
]
