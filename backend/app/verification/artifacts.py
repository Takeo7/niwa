"""E3 + E4 — artifact-scanning checks (PR-V1-11b).

* **E3** confirms *something* changed inside the task cwd. We shell out
  to ``git status --porcelain``; each non-empty line counts as one
  artifact. Zero lines → ``no_artifacts``. A cwd that is not a git
  repository degrades gracefully (``git_available = False``) so runs on
  ``project.kind = script`` with a non-git workspace still pass E3 —
  11c will gate further checks on ``git_available``. If the cwd path
  does not exist at all we fail hard with ``error_code="cwd_missing"``
  since that points to an executor/operator bug rather than a legit
  non-git workspace.
* **E4** catches writes the adapter made *outside* the task cwd. We
  replay ``run_events`` inspecting **both** tool_use shapes Claude
  emits: top-level ``event_type="tool_use"`` frames (legacy / fake CLI)
  and ``tool_use`` blocks embedded inside an ``assistant`` message's
  ``message.content[]`` (the canonical CLI shape, per v0.2
  ``FIX-20260420``). Payloads with a write-class ``name`` are checked
  for absolute ``file_path`` escaping the resolved cwd. Relative paths
  are accepted: Claude emits them relative to its own cwd, which is the
  task cwd. ``Bash`` tool_use is not inspected — heuristic coverage of
  arbitrary shell is out of scope for the MVP.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterator
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
    or ``error_code="cwd_missing"`` in ``evidence``).
    """

    cwd_path = Path(cwd)
    # Pre-check the cwd: a missing directory is an executor/operator
    # bug, not a legit non-git workspace. Treating it as ``FileNotFoundError``
    # from ``subprocess.run`` would be indistinguishable from "git not
    # installed" and silently skip the check. Fail hard instead.
    if not cwd_path.is_dir():
        evidence["cwd_exists"] = False
        evidence["git_available"] = False
        evidence["artifacts_count"] = None
        evidence["error_code"] = "cwd_missing"
        return False
    evidence["cwd_exists"] = True
    try:
        # Force C locale so the "not a git repository" stderr substring
        # match below is locale-independent. Spread first, overrides last.
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(cwd_path),
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "LANG": "C", "LC_ALL": "C", "LANGUAGE": "C"},
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


def _iter_tool_use_payloads(
    session: Session, run: Run
) -> Iterator[dict[str, Any]]:
    """Yield every ``tool_use`` payload the run emitted, in id order.

    Two shapes are supported (mirroring v0.2
    ``_extract_tool_uses_from_msg`` after ``FIX-20260420``):

    1. Top-level ``event_type == "tool_use"`` — the legacy/fake shape
       carried by a handful of unit tests and ``fake_claude.py``.
    2. Embedded ``event_type == "assistant"`` where
       ``payload.message.content`` is a list of blocks and one or more
       blocks have ``type == "tool_use"`` — the **canonical** shape the
       real Claude CLI emits. Skipping this path was the E4 blocker
       codex flagged: real runs never see top-level frames, so every
       real E4 pass was vacuous.
    """

    rows = session.execute(
        select(RunEvent)
        .where(
            RunEvent.run_id == run.id,
            RunEvent.event_type.in_(("tool_use", "assistant")),
        )
        .order_by(RunEvent.id.asc())
    ).scalars().all()

    for row in rows:
        if row.payload_json is None:
            continue
        try:
            payload = json.loads(row.payload_json)
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        if row.event_type == "tool_use":
            yield payload
            continue
        # event_type == "assistant": dig into message.content[]
        message = payload.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                yield block


def check_no_artifacts_outside_cwd(
    session: Session, run: Run, cwd: Path | str, evidence: dict[str, Any]
) -> bool:
    """E4 — pass if every write-class tool_use stayed inside ``cwd``.

    Walks the run's ``tool_use`` payloads (both top-level and embedded
    in assistant messages, see ``_iter_tool_use_payloads``) in id order;
    for each write-class payload with an absolute ``file_path``, asserts
    the path is a subpath of ``cwd.resolve()``. On first offender
    returns ``False`` and fills ``evidence["offending_paths"]`` with the
    raw (unresolved) path — matching the user-visible value they'd
    recognise from the stream.
    """

    cwd_resolved = Path(cwd).resolve()

    scanned = 0
    absolute = 0
    offender: str | None = None

    for payload in _iter_tool_use_payloads(session, run):
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
