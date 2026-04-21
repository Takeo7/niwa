"""Unit tests for ``app.finalize`` (PR-V1-13, safe mode).

Every case mocks ``subprocess.run`` via ``monkeypatch`` so no real git or
``gh`` ever executes. A tiny dispatcher helper (``_mock_cmd``) routes each
invocation by the first argv token (``git`` or ``gh``) and — for git — by
the second token (``status``, ``add``, ``commit``, ``push``) so the four
pipeline steps can be scripted independently per test.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.finalize import FinalizeResult, finalize_task
from app.models import Base, Project, Run, Task


@pytest.fixture()
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'finalize.sqlite3'}", future=True)
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with Session_() as s:
        yield s
    engine.dispose()


def _make_project(
    session: Session,
    *,
    git_remote: str | None = "git@github.com:owner/repo.git",
) -> Project:
    project = Project(
        slug="demo",
        name="Demo",
        kind="library",
        local_path="/tmp/demo",
        git_remote=git_remote,
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def _make_task_run(session: Session, project: Project) -> tuple[Task, Run]:
    task = Task(
        project_id=project.id,
        title="Ship feature X",
        description="Do the thing.",
        status="running",
        branch_name="niwa/task-1-ship-feature-x",
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    run = Run(
        task_id=task.id,
        status="running",
        model="claude-code",
        artifact_root="/tmp/demo",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return task, run


def _mock_cmd(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, tuple[int, str, str]],
) -> list[list[str]]:
    """Stub ``subprocess.run`` to return canned ``(rc, stdout, stderr)`` per key.

    Key format: ``"git status"``, ``"git add"``, ``"git commit"``,
    ``"git push"``, or ``"gh"``. Matching takes the first argv token (or
    the first two for git). If no key matches the call fails loudly so
    tests never pass by accident when the dispatcher is out of date.
    """

    seen: list[list[str]] = []

    def fake_run(args, *a, **kw):
        seen.append(list(args))
        key = args[0]
        if key == "git":
            # ``git`` flags come as ``['git', '-c', 'user.email=...', '-c',
            # '...', 'commit', ...]``. Walk past the leading flags so the
            # second "real" token is the subcommand.
            idx = 1
            while idx < len(args) and args[idx] == "-c":
                idx += 2
            sub = args[idx] if idx < len(args) else ""
            key = f"git {sub}"
        if key not in responses:
            raise AssertionError(f"unmocked subprocess call: {args}")
        rc, stdout, stderr = responses[key]
        return subprocess.CompletedProcess(args, rc, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return seen


# ---------------------------------------------------------------------------
# Happy path: commit + push + pr_url persisted.
# ---------------------------------------------------------------------------


def test_commit_push_and_pr_happy_path(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(session)
    task, run = _make_task_run(session, project)

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/gh" if name == "gh" else None)
    _mock_cmd(
        monkeypatch,
        {
            "git status": (0, " M file.py\n", ""),
            "git add": (0, "", ""),
            "git commit": (0, "", ""),
            "git push": (0, "", ""),
            "gh": (0, "https://github.com/owner/repo/pull/42\n", ""),
        },
    )

    result = finalize_task(session, run, task, project)

    assert isinstance(result, FinalizeResult)
    assert result.committed is True
    assert result.pushed is True
    assert result.pr_url == "https://github.com/owner/repo/pull/42"
    assert result.commands_skipped == []

    session.refresh(task)
    assert task.pr_url == "https://github.com/owner/repo/pull/42"


# ---------------------------------------------------------------------------
# Nothing to commit — clean working tree.
# ---------------------------------------------------------------------------


def test_nothing_to_commit_skipped(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(session)
    task, run = _make_task_run(session, project)

    _mock_cmd(monkeypatch, {"git status": (0, "", "")})

    result = finalize_task(session, run, task, project)

    assert result.committed is False
    assert result.pushed is False
    assert result.pr_url is None
    assert "nothing_to_commit" in result.commands_skipped

    session.refresh(task)
    assert task.pr_url is None


# ---------------------------------------------------------------------------
# Commit OK, no remote configured → push + pr skipped with "no_remote".
# ---------------------------------------------------------------------------


def test_no_git_remote_skips_push_and_pr(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(session, git_remote=None)
    task, run = _make_task_run(session, project)

    _mock_cmd(
        monkeypatch,
        {
            "git status": (0, " M file.py\n", ""),
            "git add": (0, "", ""),
            "git commit": (0, "", ""),
        },
    )

    result = finalize_task(session, run, task, project)

    assert result.committed is True
    assert result.pushed is False
    assert result.pr_url is None
    assert "no_remote" in result.commands_skipped

    session.refresh(task)
    assert task.pr_url is None


# ---------------------------------------------------------------------------
# Commit + push OK, but `gh` not in PATH → manual command logged.
# ---------------------------------------------------------------------------


def test_gh_missing_skips_pr(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(session)
    task, run = _make_task_run(session, project)

    monkeypatch.setattr("shutil.which", lambda name: None)
    _mock_cmd(
        monkeypatch,
        {
            "git status": (0, " M file.py\n", ""),
            "git add": (0, "", ""),
            "git commit": (0, "", ""),
            "git push": (0, "", ""),
        },
    )

    result = finalize_task(session, run, task, project)

    assert result.committed is True
    assert result.pushed is True
    assert result.pr_url is None
    assert any(s.startswith("gh_missing") for s in result.commands_skipped)
    # The manual command hint mentions the branch so the user can replay it.
    assert any(task.branch_name in s for s in result.commands_skipped)


# ---------------------------------------------------------------------------
# `gh pr create` exits non-zero — command logged, task stays ``done``.
# ---------------------------------------------------------------------------


def test_gh_pr_create_failure_logs_command(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(session)
    task, run = _make_task_run(session, project)

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/gh" if name == "gh" else None)
    _mock_cmd(
        monkeypatch,
        {
            "git status": (0, " M file.py\n", ""),
            "git add": (0, "", ""),
            "git commit": (0, "", ""),
            "git push": (0, "", ""),
            "gh": (1, "", "gh: not authenticated\n"),
        },
    )

    result = finalize_task(session, run, task, project)

    assert result.committed is True
    assert result.pushed is True
    assert result.pr_url is None
    assert any("gh_pr_create_failed" in s for s in result.commands_skipped)

    session.refresh(task)
    assert task.pr_url is None
