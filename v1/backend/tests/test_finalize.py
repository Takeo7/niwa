"""Unit tests for ``app.finalize`` (PR-V1-13, safe mode).

Every case mocks ``subprocess.run`` via ``monkeypatch`` so no real git
or ``gh`` ever executes. ``_mock_cmd`` routes each call by the first
argv token (``git``/``gh``) and — for git — by the first non-``-c``
token so the four pipeline steps (status/add/commit/push) can be
scripted independently per test.
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


PR_URL = "https://github.com/owner/repo/pull/42"
DIRTY = (0, " M file.py\n", "")
OK = (0, "", "")
COMMIT_SEQ = {"git status": DIRTY, "git add": OK, "git commit": OK}
PUSH_OK = {**COMMIT_SEQ, "git push": OK}


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
    autonomy_mode: str = "safe",
) -> tuple[Project, Task, Run]:
    project = Project(
        slug="demo", name="Demo", kind="library",
        local_path="/tmp/demo", git_remote=git_remote,
        autonomy_mode=autonomy_mode,
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
    """Stub ``subprocess.run`` to return ``(rc, stdout, stderr)`` per key
    (``"git status"``, ``"git add"``, ``"git commit"``, ``"git push"``,
    ``"gh"``, ``"gh pr create"``, ``"gh pr merge"``). Returns a list that
    records every invocation so tests can assert which commands fired.
    Unknown keys raise so drift fails loud."""

    calls: list[list[str]] = []

    def fake_run(args, *a, **kw):
        calls.append(list(args))
        key = args[0]
        if key == "git":
            idx = 1
            while idx < len(args) and args[idx] == "-c":
                idx += 2
            key = f"git {args[idx] if idx < len(args) else ''}"
        elif key == "gh" and len(args) >= 3:
            # Route `gh pr create` vs `gh pr merge` so dangerous mode tests
            # can script them independently. Fall back to "gh" for legacy
            # specs that only set a single gh response.
            sub = f"gh {args[1]} {args[2]}"
            if sub in responses:
                key = sub
        if key not in responses:
            raise AssertionError(f"unmocked subprocess call: {args}")
        rc, stdout, stderr = responses[key]
        return subprocess.CompletedProcess(args, rc, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def _gh_installed(monkeypatch: pytest.MonkeyPatch, installed: bool = True) -> None:
    path = "/usr/bin/gh" if installed else None
    monkeypatch.setattr("shutil.which", lambda name: path if name == "gh" else None)


def test_commit_push_and_pr_happy_path(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, task, run = _seed(session)
    _gh_installed(monkeypatch)
    _mock_cmd(monkeypatch, {**PUSH_OK, "gh": (0, PR_URL + "\n", "")})

    result = finalize_task(session, run, task, project)

    assert isinstance(result, FinalizeResult)
    assert result.committed and result.pushed
    assert result.pr_url == PR_URL
    assert result.commands_skipped == []
    session.refresh(task)
    assert task.pr_url == PR_URL


def test_nothing_to_commit_skipped(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, task, run = _seed(session)
    _mock_cmd(monkeypatch, {"git status": OK})

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
    _mock_cmd(monkeypatch, dict(COMMIT_SEQ))

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
    _gh_installed(monkeypatch, installed=False)
    _mock_cmd(monkeypatch, dict(PUSH_OK))

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
    _gh_installed(monkeypatch)
    _mock_cmd(monkeypatch, {**PUSH_OK, "gh": (1, "", "gh: not authenticated\n")})

    result = finalize_task(session, run, task, project)

    assert result.committed and result.pushed
    assert result.pr_url is None
    assert any("gh_pr_create_failed" in s for s in result.commands_skipped)
    session.refresh(task)
    assert task.pr_url is None


# ---- PR-V1-16: dangerous mode auto-merge --------------------------------

def test_dangerous_mode_runs_gh_pr_merge(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, task, run = _seed(session, autonomy_mode="dangerous")
    _gh_installed(monkeypatch)
    calls = _mock_cmd(monkeypatch, {
        **PUSH_OK,
        "gh pr create": (0, PR_URL + "\n", ""),
        "gh pr merge": (0, "", ""),
    })

    result = finalize_task(session, run, task, project)

    assert result.committed and result.pushed
    assert result.pr_url == PR_URL
    assert result.pr_merged is True
    assert not any("gh_pr_merge_failed" in s for s in result.commands_skipped)
    # gh pr merge must fire with the exact squash/delete-branch flags.
    merge_calls = [c for c in calls if c[:3] == ["gh", "pr", "merge"]]
    assert len(merge_calls) == 1
    assert merge_calls[0] == [
        "gh", "pr", "merge", PR_URL, "--squash", "--delete-branch",
    ]


def test_safe_mode_skips_auto_merge(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, task, run = _seed(session, autonomy_mode="safe")
    _gh_installed(monkeypatch)
    calls = _mock_cmd(monkeypatch, {**PUSH_OK, "gh pr create": (0, PR_URL + "\n", "")})

    result = finalize_task(session, run, task, project)

    assert result.pr_url == PR_URL
    assert result.pr_merged is False
    # Safe mode never invokes `gh pr merge`.
    assert not any(c[:3] == ["gh", "pr", "merge"] for c in calls)


def test_dangerous_mode_merge_failure_logs_manual_command(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, task, run = _seed(session, autonomy_mode="dangerous")
    _gh_installed(monkeypatch)
    _mock_cmd(monkeypatch, {
        **PUSH_OK,
        "gh pr create": (0, PR_URL + "\n", ""),
        "gh pr merge": (1, "", "merge conflict with base branch\n"),
    })

    result = finalize_task(session, run, task, project)

    assert result.pr_url == PR_URL
    assert result.pr_merged is False
    manual = [s for s in result.commands_skipped if "gh_pr_merge_failed" in s]
    assert manual, result.commands_skipped
    assert "--squash --delete-branch" in manual[0]
    assert "merge conflict" in manual[0]
