"""Pure helpers for ``/api/readiness`` (PR-V1-18).

Each helper returns ``(ok, details)``. Best-effort: on crash ``ok=False``
and ``details["error"]`` carries the message. Scope per SPEC §7: presence
of ``claude`` / ``gh`` only (no auth subcommands), ``git --version`` the
single subprocess, ``SELECT 1`` for DB.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text


GH_INSTALL_HINT = "install from github.com/cli/cli"


def check_db(db_path: Path) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"path": str(db_path), "reachable": False}
    try:
        engine = create_engine(f"sqlite:///{db_path}", future=True)
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        finally:
            engine.dispose()
    except Exception as exc:  # pragma: no cover — defensive
        details["error"] = str(exc)
        return False, details
    details["reachable"] = True
    return True, details


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
