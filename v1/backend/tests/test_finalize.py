"""Unit tests for ``app.finalize`` (PR-V1-13, safe mode).

Every case mocks ``subprocess.run`` via ``monkeypatch`` so no real git or
``gh`` ever executes. The ``_mock_cmd`` dispatcher routes each invocation
by the first argv token (``git`` or ``gh``) and — for git — by the first
non-``-c`` token so the four pipeline steps (``status``, ``add``,
``commit``, ``push``) can be scripted independently per test.
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


def _seed(
    session: Session,
    *,
    git_remote: str | None = "git@github.com:owner/repo.git",
) -> tuple[Project, Task, Run]:
    project = Project(
        slug="demo", name="Demo", kind="library",
        local_path="/tmp/demo", git_remote=git_remote,
    )
    session.add(project)
    session.commit()
    task = Task(
        project_id=project.id, title="Ship feature X",
        description="Do the thing.", status="running",
        branch_name="niwa/task-1-ship-feature-x",
    )
    session.add(task)
    session.commit()
    run = Run(
        task_id=task.id, status="running", model="claude-code",
        artifact_root="/tmp/demo",
    )
    session.add(run)
    session.commit()
    return project, task, run


def _mock_cmd(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, tuple[int, str, str]],
) -> list[list[str]]:
    """Stub ``subprocess.run`` to return canned ``(rc, stdout, stderr)`` per key.

    Key format: ``"git status"``, ``"git add"``, ``"git commit"``,
    ``"git push"``, or ``"gh"``. ``git`` flags (``-c key=val``) are
    skipped when computing the subcommand. Unknown keys fail loudly so
    tests cannot pass by accident when the dispatcher drifts.
    """

    seen: list[list[str]] = []

    def fake_run(args, *a, **kw):
        seen.append(list(args))
        key = args[0]
        if key == "git":
            idx = 1
            while idx < len(args) and args[idx] == "-c":
                idx += 2
            key = f"git {args[idx] if idx < len(args) else ''}"
        if key not in responses:
            raise AssertionError(f"unmocked subprocess call: {args}")
        rc, stdout, stderr = responses[key]
        return subprocess.CompletedProcess(args, rc, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return seen


def test_commit_push_and_pr_happy_path(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, task, run = _seed(session)

    monkeypatch.setattr(
        "shutil.which", lambda name: "/usr/bin/gh" if name == "gh" else None
    )
    _mock_cmd(monkeypatch, {
        "git status": (0, " M file.py\n", ""),
        "git add": (0, "", ""),
        "git commit": (0, "", ""),
        "git push": (0, "", ""),
        "gh": (0, "https://github.com/owner/repo/pull/42\n", ""),
    })

    result = finalize_task(session, run, task, project)

    assert isinstance(result, FinalizeResult)
    assert result.committed and result.pushed
    assert result.pr_url == "https://github.com/owner/repo/pull/42"
    assert result.commands_skipped == []

    session.refresh(task)
    assert task.pr_url == "https://github.com/owner/repo/pull/42"


def test_nothing_to_commit_skipped(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, task, run = _seed(session)
    _mock_cmd(monkeypatch, {"git status": (0, "", "")})

    result = finalize_task(session, run, task, project)

    assert not result.committed and not result.pushed
    assert result.pr_url is None
    assert "nothing_to_commit" in result.commands_skipped
    session.refresh(task)
    assert task.pr_url is None


def test_no_git_remote_skips_push_and_pr(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, task, run = _seed(session, git_remote=None)
    _mock_cmd(monkeypatch, {
        "git status": (0, " M file.py\n", ""),
        "git add": (0, "", ""),
        "git commit": (0, "", ""),
    })

    result = finalize_task(session, run, task, project)

    assert result.committed and not result.pushed
    assert result.pr_url is None
    assert "no_remote" in result.commands_skipped
    session.refresh(task)
    assert task.pr_url is None


def test_gh_missing_skips_pr(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, task, run = _seed(session)
    monkeypatch.setattr("shutil.which", lambda name: None)
    _mock_cmd(monkeypatch, {
        "git status": (0, " M file.py\n", ""),
        "git add": (0, "", ""),
        "git commit": (0, "", ""),
        "git push": (0, "", ""),
    })

    result = finalize_task(session, run, task, project)

    assert result.committed and result.pushed
    assert result.pr_url is None
    assert any(s.startswith("gh_missing") for s in result.commands_skipped)
    # The manual command hint mentions the branch so the user can replay it.
    assert any(task.branch_name in s for s in result.commands_skipped)


def test_gh_pr_create_failure_logs_command(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, task, run = _seed(session)
    monkeypatch.setattr(
        "shutil.which", lambda name: "/usr/bin/gh" if name == "gh" else None
    )
    _mock_cmd(monkeypatch, {
        "git status": (0, " M file.py\n", ""),
        "git add": (0, "", ""),
        "git commit": (0, "", ""),
        "git push": (0, "", ""),
        "gh": (1, "", "gh: not authenticated\n"),
    })

    result = finalize_task(session, run, task, project)

    assert result.committed and result.pushed
    assert result.pr_url is None
    assert any("gh_pr_create_failed" in s for s in result.commands_skipped)
    session.refresh(task)
    assert task.pr_url is None
