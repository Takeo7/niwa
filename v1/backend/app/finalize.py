"""Safe mode finalize (PR-V1-13).

After ``verify_run`` approves a run (outcome ``verified``), the executor
invokes ``finalize_task`` which — best-effort, never raising — runs the
safe-mode git pipeline:

    1. ``git add -A`` + ``git commit`` (skipped if working tree clean).
    2. ``git push -u origin <branch>`` (skipped if ``project.git_remote``
       is ``None`` or commit failed).
    3. ``gh pr create`` (skipped if ``gh`` is not on ``PATH`` or push
       failed). Captures the URL printed on stdout and persists it into
       ``task.pr_url``.

Every failure lands as a string in :attr:`FinalizeResult.commands_skipped`;
the task still closes ``done`` regardless so the executor never gets
stuck on a shell hiccup.

Commit flags use ``-c user.email`` / ``-c user.name`` inline so Niwa does
not depend on the caller's global git config — the MVP must work on a
fresh machine where nobody has run ``git config --global`` yet.
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

    ``commands_skipped`` accumulates human-readable reasons for each step
    that did not complete successfully — ``"nothing_to_commit"``,
    ``"no_remote"``, ``"gh_missing: ..."``, ``"commit_failed: ..."``,
    etc. Safe to render verbatim in logs / ``verification_json``.
    """

    committed: bool
    pushed: bool
    pr_url: str | None
    commands_skipped: list[str] = field(default_factory=list)


def finalize_task(
    session: Session, run: Run, task: Task, project: Project
) -> FinalizeResult:
    """Run the safe-mode finalize pipeline for ``task``.

    Never raises. Each sub-step that fails is recorded in the returned
    ``FinalizeResult.commands_skipped`` and logged at ``warning`` or
    ``info`` level. The task's ``pr_url`` is persisted via ``session``
    only when ``gh pr create`` succeeded with a valid URL.
    """

    cwd = project.local_path
    branch = task.branch_name or ""
    skipped: list[str] = []

    committed, commit_skip = _commit(task, cwd)
    skipped.extend(commit_skip)

    pushed = False
    if committed:
        if not project.git_remote:
            skipped.append("no_remote")
            logger.info("skip push task_id=%s: project.git_remote is None", task.id)
        elif not branch:
            skipped.append("no_branch")
            logger.info("skip push task_id=%s: task.branch_name is empty", task.id)
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
        committed=committed,
        pushed=pushed,
        pr_url=pr_url,
        commands_skipped=skipped,
    )


# ---------------------------------------------------------------------------
# Helpers (private).
# ---------------------------------------------------------------------------


def _run_cmd(args: Sequence[str], cwd: str) -> tuple[int, str, str]:
    """Thin wrapper around ``subprocess.run`` with capture + 30 s timeout.

    Returns ``(returncode, stdout, stderr)``. Any exception from the
    ``subprocess`` layer (timeout, file not found) is caught and surfaced
    as ``(-1, "", str(exc))`` so the caller only handles one shape.
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
    """Stage everything and commit — skip cleanly if the tree is clean.

    Returns ``(committed, skipped_reasons)``.
    """

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
            "-c",
            "user.email=niwa@localhost",
            "-c",
            "user.name=Niwa",
            "commit",
            "-m",
            subject,
            "-m",
            body,
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
    """Push the branch to ``origin`` with upstream tracking."""

    skipped: list[str] = []
    rc, _, stderr = _run_cmd(["git", "push", "-u", "origin", branch], cwd)
    if rc != 0:
        reason = (
            f"push_failed: git push -u origin {branch} rc={rc} "
            f"stderr={stderr.strip()[:200]}"
        )
        skipped.append(reason)
        logger.warning(reason)
        return False, skipped
    return True, skipped


def _pr_create(task: Task, branch: str, cwd: str) -> tuple[str | None, list[str]]:
    """Run ``gh pr create`` and extract the URL from stdout.

    Returns ``(url_or_None, skipped_reasons)``.
    """

    skipped: list[str] = []
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
            f"gh_pr_create_failed: rc={rc} "
            f"stderr={stderr.strip()[:500]} "
            f"manual='gh pr create --head {branch}'"
        )
        skipped.append(reason)
        logger.warning(reason)
        return None, skipped

    for line in stdout.splitlines():
        candidate = line.strip()
        if _URL_RE.match(candidate):
            return candidate, skipped

    # ``gh`` returned 0 but nothing that looks like a URL — log and keep
    # the task without a pr_url so the UI does not render a bogus link.
    reason = f"gh_pr_create_no_url: stdout={stdout.strip()[:200]}"
    skipped.append(reason)
    logger.warning(reason)
    return None, skipped


__all__ = ["FinalizeResult", "finalize_task"]
