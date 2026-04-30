"""Tests for niwa-executor doctor (OPS-01)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.ops.doctor import (
    DoctorCheck,
    DoctorReport,
    _check_claude,
    _check_db,
    _check_gh,
    _check_git,
    _check_node,
    _check_python,
    _check_write_permissions,
    format_report,
    run_doctor,
)
from app.niwa_cli import main as cli_main


# ---------------------------------------------------------------------------
# Individual check tests
# ---------------------------------------------------------------------------


def test_check_python_ok():
    check = _check_python()
    assert check.name == "python"
    assert check.status == "ok"


def test_check_git_ok():
    check = _check_git()
    assert check.status in ("ok", "fail")  # whatever the env has
    if check.status == "ok":
        assert "git" in check.detail.lower()


def test_check_git_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    check = _check_git()
    assert check.status == "fail"
    assert check.remediation


def test_check_gh_missing(monkeypatch):
    import shutil
    original_which = shutil.which

    def fake_which(name):
        if name == "gh":
            return None
        return original_which(name)

    with patch("app.ops.doctor.shutil.which", side_effect=fake_which):
        check = _check_gh()
    assert check.status == "warn"
    assert "install" in check.remediation.lower()


def test_check_claude_missing():
    check = _check_claude(None)
    # In test env claude may or may not exist; just validate shape
    assert check.name == "claude"
    assert check.severity == "critical"


def test_check_claude_with_env():
    check = _check_claude("/usr/local/bin/claude-fake")
    # Path provided → treat as found (we don't verify existence here)
    assert check.name == "claude"
    assert check.status == "ok"
    assert "/usr/local/bin/claude-fake" in check.detail


def test_check_db_no_file(tmp_path):
    from app.config import Settings

    settings = Settings(
        db_path=tmp_path / "new.sqlite3",
        bind_host="127.0.0.1",
        bind_port=8000,
        claude_cli=None,
        claude_timeout_s=1800,
        executor_poll_interval_s=5,
        config_source=None,
    )
    check = _check_db(settings)
    assert check.name == "db"
    assert check.status == "ok"
    assert "not created yet" in check.detail


def test_check_db_exists(tmp_path):
    import sqlite3
    from app.config import Settings

    db = tmp_path / "niwa.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE t (x INT)")
    conn.close()

    settings = Settings(
        db_path=db,
        bind_host="127.0.0.1",
        bind_port=8000,
        claude_cli=None,
        claude_timeout_s=1800,
        executor_poll_interval_s=5,
        config_source=None,
    )
    check = _check_db(settings)
    assert check.status == "ok"
    assert str(db) in check.detail


def test_check_write_permissions_ok(tmp_path):
    from app.config import Settings

    settings = Settings(
        db_path=tmp_path / "sub" / "niwa.sqlite3",
        bind_host="127.0.0.1",
        bind_port=8000,
        claude_cli=None,
        claude_timeout_s=1800,
        executor_poll_interval_s=5,
        config_source=None,
    )
    check = _check_write_permissions(settings)
    assert check.status == "ok"


# ---------------------------------------------------------------------------
# Report + formatting
# ---------------------------------------------------------------------------


def test_format_report_human():
    report = DoctorReport()
    report.add(DoctorCheck("python", "critical", "ok", "Python 3.11"))
    report.add(DoctorCheck("gh", "warning", "warn", "not found", "Install gh"))
    text = format_report(report)
    assert "python" in text
    assert "gh" in text
    assert "Install gh" in text
    assert "Doctor: OK" in text


def test_format_report_critical_fail():
    report = DoctorReport()
    report.add(DoctorCheck("git", "critical", "fail", "git not found", "Install git"))
    assert not report.overall_ok
    text = format_report(report)
    assert "FAIL" in text


def test_format_report_json():
    report = DoctorReport()
    report.add(DoctorCheck("python", "critical", "ok", "Python 3.11"))
    text = format_report(report, json_mode=True)
    data = json.loads(text)
    assert data["overall_ok"] is True
    assert data["checks"][0]["name"] == "python"


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_doctor_runs():
    rc = cli_main(["doctor"])
    assert rc in (0, 1)  # 0 if all critical pass, 1 if not


def test_cli_doctor_json():
    import io
    import sys

    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        rc = cli_main(["doctor", "--json"])
    finally:
        sys.stdout = old_stdout

    output = buf.getvalue()
    data = json.loads(output.strip())
    assert "checks" in data
    assert "overall_ok" in data
