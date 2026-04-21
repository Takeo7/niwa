"""Safe mode finalize (PR-V1-13) + dangerous auto-merge (PR-V1-16).

After ``verify_run`` approves a run the executor calls ``finalize_task``
which, best-effort, runs: ``git add -A`` + ``git commit`` → ``git push
-u origin <branch>`` (if ``project.git_remote``) → ``gh pr create`` (if
``gh`` is on PATH). Each step that fails is recorded in
:attr:`FinalizeResult.commands_skipped`; the function never raises.

When ``project.autonomy_mode == "dangerous"`` and a PR URL was produced,
one extra step runs: ``gh pr merge <url> --squash --delete-branch``.
Success flips ``FinalizeResult.pr_merged`` to ``True``; any failure is
logged with the manual command the user can replay.

Commit flags use inline ``-c user.email`` / ``-c user.name`` so a fresh
machine with no global git config still produces a valid commit.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Sequence

from sqlalchemy.orm import Session

from .models import Project, Run, Task


logger = logging.getLogger("niwa.finalize")

_CMD_TIMEOUT_S = 30
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


@dataclass(frozen=True)
class FinalizeResult:
    """Outcome of :func:`finalize_task`. ``commands_skipped`` holds
    human-readable reasons (``"no_remote"``, ``"gh_missing: ..."``,
    ``"commit_failed: ..."``, ``"gh_pr_merge_failed: ..."``) safe to
    render in logs. ``pr_merged`` is only ``True`` when dangerous mode
    ran ``gh pr merge`` with exit 0; safe mode and failed merges leave
    it ``False``."""

    committed: bool
    pushed: bool
    pr_url: str | None
    pr_merged: bool = False
    commands_skipped: list[str] = field(default_factory=list)


def finalize_task(
    session: Session, run: Run, task: Task, project: Project
) -> FinalizeResult:
    """Run the safe-mode finalize pipeline for ``task``. Never raises."""

    del run  # reserved for future use (e.g. attach finalize notes to run)
    cwd = project.local_path
    branch = task.branch_name or ""
    skipped: list[str] = []

    committed, commit_skip = _commit(task, cwd)
    skipped.extend(commit_skip)

    pushed = False
    if committed:
        if not project.git_remote:
            skipped.append("no_remote")
        elif not branch:
            skipped.append("no_branch")
        else:
            pushed, push_skip = _push(branch, cwd)
            skipped.extend(push_skip)

    pr_url: str | None = None
    if pushed:
        if shutil.which("gh") is None:
            skipped.append(
                f"gh_missing: run 'gh pr create --head {branch}' to open the PR manually"
            )
        else:
            pr_url, pr_skip = _pr_create(task, branch, cwd)
            skipped.extend(pr_skip)

    if pr_url:
        task.pr_url = pr_url
        session.commit()

    # PR-V1-16: auto-merge when the project opted into dangerous mode.
    # Safe mode is a silent no-op (human merges by hand). We only attempt
    # the merge if we actually have a PR URL *and* `gh` is on PATH — if
    # `gh` went missing between pr_create and here it's already logged.
    pr_merged = False
    if (
        pr_url
        and getattr(project, "autonomy_mode", "safe") == "dangerous"
        and shutil.which("gh") is not None
    ):
        pr_merged, merge_skip = _pr_merge(pr_url, cwd)
        skipped.extend(merge_skip)
        if pr_merged:
            logger.info("auto-merged PR for task_id=%s url=%s", task.id, pr_url)

    return FinalizeResult(
        committed=committed,
        pushed=pushed,
        pr_url=pr_url,
        pr_merged=pr_merged,
        commands_skipped=skipped,
    )


def _run_cmd(args: Sequence[str], cwd: str) -> tuple[int, str, str]:
    """Run ``args`` in ``cwd`` with 30 s timeout. Returns ``(rc, stdout,
    stderr)``; OS/subprocess errors surface as ``(-1, "", str(exc))``."""

    logger.info("cmd cwd=%s argv=%s", cwd, list(args))
    try:
        proc = subprocess.run(
            list(args), cwd=cwd, check=False, capture_output=True,
            text=True, timeout=_CMD_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", str(exc)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _commit(task: Task, cwd: str) -> tuple[bool, list[str]]:
    """Stage + commit; skip cleanly when the working tree is clean."""

    rc, stdout, stderr = _run_cmd(["git", "status", "--porcelain"], cwd)
    if rc != 0:
        return False, [_fail("commit_failed: git status", rc, stderr)]
    if not stdout.strip():
        return False, ["nothing_to_commit"]
    rc, _, stderr = _run_cmd(["git", "add", "-A"], cwd)
    if rc != 0:
        return False, [_fail("commit_failed: git add", rc, stderr)]
    subject = f"niwa: {(task.title or '')[:60]}"
    body = (task.description or "") + f"\n\nNiwa task #{task.id}"
    rc, _, stderr = _run_cmd(
        ["git", "-c", "user.email=niwa@localhost", "-c", "user.name=Niwa",
         "commit", "-m", subject, "-m", body],
        cwd,
    )
    if rc != 0:
        return False, [_fail("commit_failed: git commit", rc, stderr)]
    return True, []


def _push(branch: str, cwd: str) -> tuple[bool, list[str]]:
    """Push to ``origin`` with upstream tracking."""

    rc, _, stderr = _run_cmd(["git", "push", "-u", "origin", branch], cwd)
    if rc != 0:
        return False, [_fail(f"push_failed: git push -u origin {branch}", rc, stderr)]
    return True, []


def _pr_create(task: Task, branch: str, cwd: str) -> tuple[str | None, list[str]]:
    """Run ``gh pr create`` and extract the URL from stdout."""

    title = (task.title or f"Niwa task #{task.id}")[:70]
    body = (task.description or "(no description)") + (
        f"\n\n---\nOpened by Niwa for task #{task.id}"
    )
    rc, stdout, stderr = _run_cmd(
        ["gh", "pr", "create", "--title", title, "--body", body, "--head", branch],
        cwd,
    )
    if rc != 0:
        return None, [_fail(
            f"gh_pr_create_failed: manual='gh pr create --head {branch}'",
            rc, stderr,
        )]
    for line in stdout.splitlines():
        candidate = line.strip()
        if _URL_RE.match(candidate):
            return candidate, []
    # ``gh`` returned 0 but emitted nothing URL-shaped — drop pr_url so
    # the UI never renders a bogus link.
    msg = f"gh_pr_create_no_url: stdout={stdout.strip()[:200]}"
    logger.warning(msg)
    return None, [msg]


def _pr_merge(pr_url: str, cwd: str) -> tuple[bool, list[str]]:
    """Run ``gh pr merge <url> --squash --delete-branch``. On failure the
    returned reason embeds the stderr (truncated) and the manual command
    so the user can replay it verbatim."""

    argv = ["gh", "pr", "merge", pr_url, "--squash", "--delete-branch"]
    rc, _, stderr = _run_cmd(argv, cwd)
    if rc == 0:
        return True, []
    manual = f"gh pr merge {pr_url} --squash --delete-branch"
    reason = (
        f"gh_pr_merge_failed: {stderr.strip()[:500]} (manual: {manual})"
    )
    logger.warning(reason)
    return False, [reason]


def _fail(prefix: str, rc: int, stderr: str) -> str:
    """Format + log a one-line failure reason."""

    msg = f"{prefix} rc={rc} stderr={stderr.strip()[:200]}"
    logger.warning(msg)
    return msg


__all__ = ["FinalizeResult", "finalize_task"]
