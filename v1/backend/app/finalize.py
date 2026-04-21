"""Safe mode finalize (PR-V1-13).

After ``verify_run`` approves a run the executor calls ``finalize_task``
which, best-effort:

1. ``git add -A`` + ``git commit`` (skipped if working tree clean).
2. ``git push -u origin <branch>`` (skipped if no ``project.git_remote``
   or commit failed).
3. ``gh pr create`` (skipped if ``gh`` missing or push failed). Captures
   the URL ``gh`` prints on stdout and persists it into ``task.pr_url``.

Commit flags use ``-c user.email`` / ``-c user.name`` inline so a fresh
machine with no global git config still produces a valid commit. Nothing
here raises: every failing step is recorded in
:attr:`FinalizeResult.commands_skipped` and logged.
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
    """Outcome of :func:`finalize_task`.

    ``commands_skipped`` accumulates human-readable reasons (``"no_remote"``,
    ``"gh_missing: ..."``, ``"commit_failed: ..."``) — safe to render
    verbatim in logs or ``verification_json``.
    """

    committed: bool
    pushed: bool
    pr_url: str | None
    commands_skipped: list[str] = field(default_factory=list)


def finalize_task(
    session: Session, run: Run, task: Task, project: Project
) -> FinalizeResult:
    """Run the safe-mode finalize pipeline for ``task``. Never raises."""

    _ = run  # reserved for future use (e.g. attach finalize notes to run)
    cwd = project.local_path
    branch = task.branch_name or ""
    skipped: list[str] = []

    committed, commit_skip = _commit(task, cwd)
    skipped.extend(commit_skip)

    pushed = False
    if committed:
        if not project.git_remote:
            skipped.append("no_remote")
            logger.info("skip push task_id=%s: no git_remote", task.id)
        elif not branch:
            skipped.append("no_branch")
            logger.info("skip push task_id=%s: empty branch_name", task.id)
        else:
            pushed, push_skip = _push(branch, cwd)
            skipped.extend(push_skip)

    pr_url: str | None = None
    if pushed:
        if shutil.which("gh") is None:
            skipped.append(
                f"gh_missing: run 'gh pr create --head {branch}' to open the PR manually"
            )
            logger.info("skip gh pr create task_id=%s: gh not on PATH", task.id)
        else:
            pr_url, pr_skip = _pr_create(task, branch, cwd)
            skipped.extend(pr_skip)

    if pr_url:
        task.pr_url = pr_url
        session.commit()

    return FinalizeResult(
        committed=committed, pushed=pushed, pr_url=pr_url, commands_skipped=skipped
    )


# ---------------------------------------------------------------------------
# Helpers (private).
# ---------------------------------------------------------------------------


def _run_cmd(args: Sequence[str], cwd: str) -> tuple[int, str, str]:
    """Run ``args`` in ``cwd`` with capture + 30 s timeout.

    Returns ``(rc, stdout, stderr)``. OS/subprocess errors come back as
    ``(-1, "", str(exc))`` so the caller has one shape to handle.
    """

    logger.info("cmd cwd=%s argv=%s", cwd, list(args))
    try:
        proc = subprocess.run(
            list(args),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=_CMD_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", str(exc)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _commit(task: Task, cwd: str) -> tuple[bool, list[str]]:
    """Stage + commit; skip cleanly when the working tree is clean."""

    skipped: list[str] = []

    rc, stdout, stderr = _run_cmd(["git", "status", "--porcelain"], cwd)
    if rc != 0:
        reason = f"commit_failed: git status rc={rc} stderr={stderr.strip()[:200]}"
        skipped.append(reason)
        logger.warning(reason)
        return False, skipped
    if not stdout.strip():
        skipped.append("nothing_to_commit")
        return False, skipped

    rc, _, stderr = _run_cmd(["git", "add", "-A"], cwd)
    if rc != 0:
        reason = f"commit_failed: git add rc={rc} stderr={stderr.strip()[:200]}"
        skipped.append(reason)
        logger.warning(reason)
        return False, skipped

    subject = f"niwa: {(task.title or '')[:60]}"
    body = (task.description or "") + f"\n\nNiwa task #{task.id}"
    rc, _, stderr = _run_cmd(
        [
            "git",
            "-c", "user.email=niwa@localhost",
            "-c", "user.name=Niwa",
            "commit", "-m", subject, "-m", body,
        ],
        cwd,
    )
    if rc != 0:
        reason = f"commit_failed: git commit rc={rc} stderr={stderr.strip()[:200]}"
        skipped.append(reason)
        logger.warning(reason)
        return False, skipped
    return True, skipped


def _push(branch: str, cwd: str) -> tuple[bool, list[str]]:
    """Push to ``origin`` with upstream tracking."""

    rc, _, stderr = _run_cmd(["git", "push", "-u", "origin", branch], cwd)
    if rc != 0:
        reason = (
            f"push_failed: git push -u origin {branch} rc={rc} "
            f"stderr={stderr.strip()[:200]}"
        )
        logger.warning(reason)
        return False, [reason]
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
        reason = (
            f"gh_pr_create_failed: rc={rc} stderr={stderr.strip()[:500]} "
            f"manual='gh pr create --head {branch}'"
        )
        logger.warning(reason)
        return None, [reason]

    for line in stdout.splitlines():
        candidate = line.strip()
        if _URL_RE.match(candidate):
            return candidate, []

    # ``gh`` returned 0 but emitted nothing URL-shaped — drop the url so
    # the UI never renders a bogus link.
    reason = f"gh_pr_create_no_url: stdout={stdout.strip()[:200]}"
    logger.warning(reason)
    return None, [reason]


__all__ = ["FinalizeResult", "finalize_task"]
