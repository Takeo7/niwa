"""``niwa-executor doctor`` — local environment diagnostics.

Each check returns a ``DoctorCheck`` with severity, status, and a
human-readable remediation when the check fails.  ``run_doctor`` returns
a ``DoctorReport`` suitable for printing or serialising to JSON.

Severities:
  critical — the executor / API cannot work without this
  warning  — degraded functionality (e.g. no gh means no PR creation)
  info     — useful context, never a blocker
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..config import load_settings


Severity = Literal["critical", "warning", "info"]
Status = Literal["ok", "fail", "warn", "skip"]


@dataclass
class DoctorCheck:
    name: str
    severity: Severity
    status: Status
    detail: str = ""
    remediation: str = ""


@dataclass
class DoctorReport:
    checks: list[DoctorCheck] = field(default_factory=list)
    overall_ok: bool = True

    def add(self, check: DoctorCheck) -> None:
        self.checks.append(check)
        if check.severity == "critical" and check.status == "fail":
            self.overall_ok = False


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_python() -> DoctorCheck:
    major, minor = sys.version_info[:2]
    version = f"{major}.{minor}.{sys.version_info[2]}"
    if major < 3 or (major == 3 and minor < 11):
        return DoctorCheck(
            name="python",
            severity="critical",
            status="fail",
            detail=f"Python {version} detected",
            remediation="Install Python 3.11+",
        )
    return DoctorCheck(name="python", severity="critical", status="ok", detail=f"Python {version}")


def _check_node() -> DoctorCheck:
    node = shutil.which("node")
    if not node:
        return DoctorCheck(
            name="node",
            severity="warning",
            status="warn",
            detail="node not found",
            remediation="Install Node.js 18+ (needed for frontend dev/build)",
        )
    try:
        r = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=5)
        version = r.stdout.strip()
    except Exception as exc:
        version = f"error: {exc}"
    return DoctorCheck(name="node", severity="warning", status="ok", detail=version)


def _check_git() -> DoctorCheck:
    git = shutil.which("git")
    if not git:
        return DoctorCheck(
            name="git",
            severity="critical",
            status="fail",
            detail="git not found",
            remediation="Install git (required for workspace and finalize)",
        )
    try:
        r = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
        version = r.stdout.strip()
    except Exception as exc:
        version = f"error: {exc}"
    return DoctorCheck(name="git", severity="critical", status="ok", detail=version)


def _check_gh() -> DoctorCheck:
    gh = shutil.which("gh")
    if not gh:
        return DoctorCheck(
            name="gh",
            severity="warning",
            status="warn",
            detail="gh not found",
            remediation="Install GitHub CLI from github.com/cli/cli (needed for PR creation)",
        )
    try:
        r = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            first_line = (r.stdout or r.stderr).splitlines()[0] if (r.stdout or r.stderr) else "authenticated"
            return DoctorCheck(name="gh", severity="warning", status="ok", detail=first_line)
        return DoctorCheck(
            name="gh",
            severity="warning",
            status="warn",
            detail="gh found but not authenticated",
            remediation="Run: gh auth login",
        )
    except Exception as exc:
        return DoctorCheck(
            name="gh",
            severity="warning",
            status="warn",
            detail=f"gh auth check failed: {exc}",
            remediation="Run: gh auth login",
        )


def _check_claude(settings_cli: str | None) -> DoctorCheck:
    cli = settings_cli or shutil.which("claude")
    if not cli:
        return DoctorCheck(
            name="claude",
            severity="critical",
            status="fail",
            detail="claude CLI not found (NIWA_CLAUDE_CLI not set, claude not on PATH)",
            remediation="Install Claude Code CLI or set NIWA_CLAUDE_CLI",
        )
    return DoctorCheck(name="claude", severity="critical", status="ok", detail=f"path: {cli}")


def _check_db(settings) -> DoctorCheck:
    db_path = settings.db_path
    if not db_path.parent.exists():
        return DoctorCheck(
            name="db_dir",
            severity="critical",
            status="fail",
            detail=f"DB directory missing: {db_path.parent}",
            remediation="Run ./bootstrap.sh or create the directory manually",
        )
    if db_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            conn.execute("SELECT 1")
            conn.close()
            size = db_path.stat().st_size
            return DoctorCheck(
                name="db",
                severity="critical",
                status="ok",
                detail=f"{db_path} ({size // 1024} KB)",
            )
        except Exception as exc:
            return DoctorCheck(
                name="db",
                severity="critical",
                status="fail",
                detail=f"DB not readable: {exc}",
                remediation="Check permissions or delete and re-run bootstrap",
            )
    return DoctorCheck(
        name="db",
        severity="info",
        status="ok",
        detail=f"{db_path} (not created yet — will be created on first start)",
    )


def _check_config(settings) -> DoctorCheck:
    if settings.config_source is None:
        return DoctorCheck(
            name="config",
            severity="info",
            status="ok",
            detail="No config.toml found — using defaults",
        )
    return DoctorCheck(
        name="config",
        severity="info",
        status="ok",
        detail=f"{settings.config_source}",
    )


def _check_port(settings) -> DoctorCheck:
    host = settings.bind_host
    port = settings.bind_port
    try:
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            result = s.connect_ex((host, port))
        if result == 0:
            return DoctorCheck(
                name="port",
                severity="warning",
                status="warn",
                detail=f"{host}:{port} already in use",
                remediation="Another process may be using the port; check with: lsof -i :{port}",
            )
        return DoctorCheck(
            name="port",
            severity="info",
            status="ok",
            detail=f"{host}:{port} is available",
        )
    except Exception as exc:
        return DoctorCheck(
            name="port",
            severity="info",
            status="ok",
            detail=f"port check skipped: {exc}",
        )


def _check_write_permissions(settings) -> DoctorCheck:
    niwa_home = settings.db_path.parent
    test_file = niwa_home / ".doctor_write_test"
    try:
        niwa_home.mkdir(parents=True, exist_ok=True)
        test_file.write_text("ok")
        test_file.unlink()
        return DoctorCheck(
            name="write_permissions",
            severity="critical",
            status="ok",
            detail=f"write OK in {niwa_home}",
        )
    except Exception as exc:
        return DoctorCheck(
            name="write_permissions",
            severity="critical",
            status="fail",
            detail=f"cannot write to {niwa_home}: {exc}",
            remediation=f"Fix permissions: chmod 755 {niwa_home}",
        )


def _check_os() -> DoctorCheck:
    system = platform.system()
    release = platform.release()
    return DoctorCheck(
        name="os",
        severity="info",
        status="ok",
        detail=f"{system} {release}",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_doctor(config_path: Path | None = None) -> DoctorReport:
    settings = load_settings(config_path)
    report = DoctorReport()

    report.add(_check_os())
    report.add(_check_python())
    report.add(_check_node())
    report.add(_check_git())
    report.add(_check_gh())
    report.add(_check_claude(settings.claude_cli))
    report.add(_check_db(settings))
    report.add(_check_config(settings))
    report.add(_check_port(settings))
    report.add(_check_write_permissions(settings))

    return report


def format_report(report: DoctorReport, *, json_mode: bool = False) -> str:
    if json_mode:
        import json
        return json.dumps(
            {
                "overall_ok": report.overall_ok,
                "checks": [
                    {
                        "name": c.name,
                        "severity": c.severity,
                        "status": c.status,
                        "detail": c.detail,
                        "remediation": c.remediation,
                    }
                    for c in report.checks
                ],
            },
            indent=2,
        )

    icons = {"ok": "✓", "fail": "✗", "warn": "!", "skip": "-"}
    lines = []
    for c in report.checks:
        icon = icons.get(c.status, "?")
        line = f"  [{icon}] {c.name:<22} {c.detail}"
        lines.append(line)
        if c.remediation:
            lines.append(f"       → {c.remediation}")
    overall = "OK" if report.overall_ok else "FAIL (critical checks failed)"
    lines.append(f"\nDoctor: {overall}")
    return "\n".join(lines)
