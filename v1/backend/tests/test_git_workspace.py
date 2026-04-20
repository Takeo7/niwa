"""Unit tests for ``app.executor.git_workspace`` (PR-V1-08).

The module owns the "branch per task" invariant — every task is executed
on a `niwa/task-<id>-<slug>` branch in the project's working tree. These
tests pin the four failure/reuse paths the executor needs to rely on,
plus a pure ``build_branch_name`` case table. Repo setup reuses the
shared ``git_project`` fixture from ``conftest.py``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.executor.git_workspace import (
    GitWorkspaceError,
    build_branch_name,
    prepare_task_branch,
)
from app.models import Task


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Thin wrapper so tests don't call the SUT's own ``_run_git`` helper."""

    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _make_task(task_id: int, title: str) -> Task:
    """A detached Task instance — these tests never hit the DB."""

    task = Task(title=title, description="")
    task.id = task_id
    return task


# ---------------------------------------------------------------------------
# build_branch_name — pure, no disk, no subprocess
# ---------------------------------------------------------------------------


def test_build_branch_name_cases() -> None:
    # Normal title — slug is lowercase, symbols collapse to ``-``, truncated
    # to 30 characters (brief rule; the brief's worked example used a 25-char
    # slug, which we flag at review time — the rule is the source of truth).
    assert (
        build_branch_name(_make_task(42, "Fix: login crashes on empty email"))
        == "niwa/task-42-fix-login-crashes-on-empty-ema"
    )
    # Symbols and consecutive separators collapse.
    assert (
        build_branch_name(_make_task(7, "Hello!!!   World???"))
        == "niwa/task-7-hello-world"
    )
    # All symbols → ``untitled`` fallback.
    assert build_branch_name(_make_task(9, "!!!")) == "niwa/task-9-untitled"
    # Very long title truncates the slug to 30 chars.
    long_title = "a" * 200
    name = build_branch_name(_make_task(1, long_title))
    assert name.startswith("niwa/task-1-")
    slug = name.split("niwa/task-1-", 1)[1]
    assert len(slug) == 30
    # Empty title also falls back to ``untitled``.
    assert build_branch_name(_make_task(5, "")) == "niwa/task-5-untitled"


# ---------------------------------------------------------------------------
# prepare_task_branch
# ---------------------------------------------------------------------------


def test_prepare_task_branch_creates_and_switches(git_project: Path) -> None:
    task = _make_task(42, "Fix: login crashes on empty email")

    name = prepare_task_branch(str(git_project), task)

    assert name == "niwa/task-42-fix-login-crashes-on-empty-ema"
    current = _git(["branch", "--show-current"], cwd=git_project).stdout.strip()
    assert current == name


def test_prepare_reuses_existing_branch(git_project: Path) -> None:
    task = _make_task(42, "Fix: login crashes on empty email")
    name = build_branch_name(task)

    # Create the target branch up front with an extra commit on it so we
    # can assert nothing gets reset.
    _git(["checkout", "-b", name], cwd=git_project)
    (git_project / "seed.txt").write_text("existing\n")
    _git(["add", "seed.txt"], cwd=git_project)
    _git(["commit", "-m", "existing work"], cwd=git_project)
    _git(["checkout", "main"], cwd=git_project)

    returned = prepare_task_branch(str(git_project), task)

    assert returned == name
    current = _git(["branch", "--show-current"], cwd=git_project).stdout.strip()
    assert current == name
    # The extra commit survives — no reset, no force-recreate.
    assert (git_project / "seed.txt").exists()
    log = _git(["log", "--oneline"], cwd=git_project).stdout
    assert "existing work" in log


def test_prepare_rejects_non_git_dir(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()

    with pytest.raises(GitWorkspaceError) as excinfo:
        prepare_task_branch(str(plain), _make_task(1, "whatever"))

    assert "not a git repository" in str(excinfo.value).lower()


def test_prepare_rejects_dirty_working_tree(git_project: Path) -> None:
    # Leave an uncommitted modification behind.
    (git_project / "README.md").write_text("dirty\n")

    with pytest.raises(GitWorkspaceError) as excinfo:
        prepare_task_branch(str(git_project), _make_task(1, "whatever"))

    msg = str(excinfo.value).lower()
    assert "dirty" in msg or "uncommitted" in msg or "working tree" in msg
    # No stash happened — the modification is still there.
    assert (git_project / "README.md").read_text() == "dirty\n"
