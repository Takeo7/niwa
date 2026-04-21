"""E3 + E4 — artifact-scanning checks (PR-V1-11b).

* **E3** confirms *something* changed inside the task cwd. We shell out
  to ``git status --porcelain``; each non-empty line counts as one
  artifact. Zero lines → ``no_artifacts``. A cwd that is not a git
  repository degrades gracefully (``git_available = False``) so runs on
  ``project.kind = script`` with a non-git workspace still pass E3 —
  11c will gate further checks on ``git_available``.
* **E4** catches writes the adapter made *outside* the task cwd. We
  replay ``run_events`` (filtering to ``tool_use`` with a write-class
  ``name``) and flag any absolute ``file_path`` that is not a subpath of
  the resolved cwd. Relative paths are accepted: Claude emits them
  relative to its own cwd, which is the task cwd. ``Bash`` tool_use is
  not inspected — heuristic coverage of arbitrary shell is out of scope
  for the MVP.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Run, RunEvent


# Claude Code tools that write bytes to disk. ``Bash`` could too but is
# impossible to analyse without parsing arbitrary shell, so we punt.
_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def check_artifacts_in_cwd(cwd: Path | str, evidence: dict[str, Any]) -> bool:
    """E3 — pass if ``git status --porcelain`` reports ≥1 line.

    Returns ``True`` on pass (including the graceful "not a git repo"
    skip) and ``False`` on fail (populating ``error_code="no_artifacts"``
    in ``evidence``).
    """

    cwd_path = Path(cwd)
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(cwd_path),
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        stderr = ""
        if isinstance(exc, subprocess.CalledProcessError):
            stderr = (exc.stderr or "").lower()
        if "not a git repository" in stderr or isinstance(exc, FileNotFoundError):
            # Graceful skip: no git → no evidence to collect, but not a
            # hard failure. 11c will gate its own work on this flag.
            evidence["git_available"] = False
            evidence["artifacts_count"] = None
            return True
        evidence["git_available"] = False
        evidence["artifacts_count"] = None
        evidence["error_code"] = "no_artifacts"
        return False

    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    count = len(lines)
    evidence["git_available"] = True
    evidence["artifacts_count"] = count
    if count == 0:
        evidence["error_code"] = "no_artifacts"
        return False
    return True


def _extract_write_path(payload: dict[str, Any]) -> str | None:
    """Return the ``file_path`` declared by a write-class tool_use, or ``None``."""

    name = payload.get("name")
    if name not in _WRITE_TOOLS:
        return None
    inp = payload.get("input")
    if not isinstance(inp, dict):
        return None
    # ``NotebookEdit`` has historically used ``notebook_path``/``path``
    # rather than ``file_path``. Accept either shape so a schema drift
    # doesn't silently bypass E4.
    candidate = inp.get("file_path")
    if candidate is None and name == "NotebookEdit":
        candidate = inp.get("path") or inp.get("notebook_path")
    if not isinstance(candidate, str) or not candidate:
        return None
    return candidate


def check_no_artifacts_outside_cwd(
    session: Session, run: Run, cwd: Path | str, evidence: dict[str, Any]
) -> bool:
    """E4 — pass if every write-class tool_use stayed inside ``cwd``.

    Walks the run's ``tool_use`` events in id order; for each write-class
    payload with an absolute ``file_path``, asserts the path is a subpath
    of ``cwd.resolve()``. On first offender returns ``False`` and fills
    ``evidence["offending_paths"]`` with the raw (unresolved) path —
    matching the user-visible value they'd recognise from the stream.
    """

    cwd_resolved = Path(cwd).resolve()

    rows = session.execute(
        select(RunEvent)
        .where(RunEvent.run_id == run.id, RunEvent.event_type == "tool_use")
        .order_by(RunEvent.id.asc())
    ).scalars().all()

    scanned = 0
    absolute = 0
    offender: str | None = None

    for row in rows:
        if row.payload_json is None:
            continue
        try:
            payload = json.loads(row.payload_json)
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        file_path = _extract_write_path(payload)
        if file_path is None:
            continue
        scanned += 1

        p = Path(file_path)
        if not p.is_absolute():
            # Relative → assumed to be relative to the adapter cwd, i.e.
            # already inside. Accept without further checks.
            continue
        absolute += 1

        try:
            resolved = p.resolve()
        except OSError:
            # Broken path resolution still counts as an offender — we
            # can't prove it's inside cwd.
            offender = file_path
            break

        try:
            resolved.relative_to(cwd_resolved)
        except ValueError:
            offender = file_path
            break

    evidence["tool_use_writes_scanned"] = scanned
    evidence["tool_use_writes_absolute"] = absolute
    if offender is not None:
        evidence["artifacts_outside_cwd"] = True
        evidence["offending_paths"] = [offender]
        evidence["error_code"] = "artifacts_outside_cwd"
        return False
    evidence["artifacts_outside_cwd"] = False
    return True


__all__ = ["check_artifacts_in_cwd", "check_no_artifacts_outside_cwd"]
