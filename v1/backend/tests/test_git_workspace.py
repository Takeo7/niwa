"""Unit tests for ``app.executor.git_workspace`` (PR-V1-08).

The module owns the "branch per task" invariant — every task is executed
on a `niwa/task-<id>-<slug>` branch in the project's working tree. These
tests pin the four failure/reuse paths the executor needs to rely on,
plus a pure ``build_branch_name`` case table because slug derivation
drives the on-disk branch layout.
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
    """Run a git command without relying on the module under test.

    Used by these tests to set up repos; calling ``prepare_task_branch``'s
    own helper here would couple the tests to the SUT's internals.
    """

    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path: Path) -> None:
    """Create a git repo with a single commit so ``HEAD`` is defined."""

    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", "main"], cwd=path)
    _git(["config", "user.email", "niwa@test.local"], cwd=path)
    _git(["config", "user.name", "Niwa Test"], cwd=path)
    (path / "README.md").write_text("seed\n")
    _git(["add", "README.md"], cwd=path)
    _git(["commit", "-m", "init"], cwd=path)


def _make_task(task_id: int, title: str) -> Task:
    """A detached Task instance — these tests never hit the DB."""

    task = Task(title=title, description="")
    task.id = task_id
    return task


# ---------------------------------------------------------------------------
# build_branch_name — pure, no disk, no subprocess
# ---------------------------------------------------------------------------


def test_build_branch_name_cases() -> None:
    # Normal title.
    assert (
        build_branch_name(_make_task(42, "Fix: login crashes on empty email"))
        == "niwa/task-42-fix-login-crashes-on-empt"
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


def test_prepare_task_branch_creates_and_switches(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    task = _make_task(42, "Fix: login crashes on empty email")

    name = prepare_task_branch(str(repo), task)

    assert name == "niwa/task-42-fix-login-crashes-on-empt"
    current = _git(["branch", "--show-current"], cwd=repo).stdout.strip()
    assert current == name


def test_prepare_reuses_existing_branch(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    task = _make_task(42, "Fix: login crashes on empty email")
    name = build_branch_name(task)

    # Create the target branch up front with an extra commit on it so we
    # can assert nothing gets reset.
    _git(["checkout", "-b", name], cwd=repo)
    (repo / "seed.txt").write_text("existing\n")
    _git(["add", "seed.txt"], cwd=repo)
    _git(["commit", "-m", "existing work"], cwd=repo)
    _git(["checkout", "main"], cwd=repo)

    returned = prepare_task_branch(str(repo), task)

    assert returned == name
    current = _git(["branch", "--show-current"], cwd=repo).stdout.strip()
    assert current == name
    # The extra commit survives — no reset, no force-recreate.
    assert (repo / "seed.txt").exists()
    log = _git(["log", "--oneline"], cwd=repo).stdout
    assert "existing work" in log


def test_prepare_rejects_non_git_dir(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    task = _make_task(1, "whatever")

    with pytest.raises(GitWorkspaceError) as excinfo:
        prepare_task_branch(str(plain), task)

    assert "not a git repository" in str(excinfo.value).lower()


def test_prepare_rejects_dirty_working_tree(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    # Leave an uncommitted modification behind.
    (repo / "README.md").write_text("dirty\n")
    task = _make_task(1, "whatever")

    with pytest.raises(GitWorkspaceError) as excinfo:
        prepare_task_branch(str(repo), task)

    msg = str(excinfo.value).lower()
    assert "dirty" in msg or "uncommitted" in msg or "working tree" in msg
    # No stash happened — the modification is still there.
    assert (repo / "README.md").read_text() == "dirty\n"
