"""Pure helpers for ``/api/readiness`` (PR-V1-18).

Each helper returns ``(ok, details)``. Best-effort: on crash ``ok=False``
and ``details["error"]`` carries the message. Scope per SPEC §7: presence
of ``claude`` / ``gh`` only (no auth subcommands), ``git --version`` the
single subprocess, ``SELECT 1`` for DB.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


GH_INSTALL_HINT = "install from github.com/cli/cli"


def check_db_via_session(session: Session) -> tuple[bool, dict[str, Any]]:
    """Probe DB reachability using the session injected by the DI graph.

    Using the request-scoped ``Session`` (rather than an ad-hoc engine off
    a filesystem path) guarantees the check targets the same database the
    rest of the app is talking to and — critically — does not create a
    SQLite file as a side effect of the health probe.
    """

    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        return False, {"reachable": False, "error": str(exc)[:200]}
    return True, {"reachable": True}


def check_claude_cli(cli: str | None) -> tuple[bool, dict[str, Any]]:
    path = shutil.which(cli or "claude")
    found = path is not None
    return found, {"path": path, "found": found}


def check_git() -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {}
    try:
        proc = subprocess.run(
            ["git", "--version"], check=False, capture_output=True, text=True, timeout=5
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        details["error"] = str(exc)
        return False, details
    if proc.returncode != 0:
        details["error"] = proc.stderr.strip() or f"exit {proc.returncode}"
        return False, details
    details["version"] = proc.stdout.strip()
    return True, details


def check_gh() -> tuple[bool, dict[str, Any]]:
    path = shutil.which("gh")
    found = path is not None
    details: dict[str, Any] = {"found": found}
    if not found:
        details["hint"] = GH_INSTALL_HINT
    return found, details
