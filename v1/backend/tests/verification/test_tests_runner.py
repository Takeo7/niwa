"""E5 — project tests runner unit tests (PR-V1-11c).

Three cases per brief:

* ``test_npm_test_passes`` — ``package.json`` with ``scripts.test`` that
  exits 0 → runner detected as ``npm``, ``run_project_tests`` passes.
* ``test_pytest_failure`` — ``pyproject.toml`` + a ``test_dummy.py``
  that asserts ``False`` → runner detected as ``pytest``,
  ``run_project_tests`` returns ``passed=False`` with non-zero exit.
* ``test_no_test_script_detected_skips`` — empty ``tmp_path`` →
  ``detect_test_runner`` returns ``None`` with reason
  ``no_test_script_detected``.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.verification.tests_runner import (
    TestRunnerChoice,
    detect_test_runner,
    run_project_tests,
)


@dataclass
class _Project:
    """Minimal stand-in for the real ``Project`` model.

    The runner only reads ``kind``; no need to drag SQLAlchemy in.
    """

    kind: str


def test_npm_test_passes(tmp_path: Path) -> None:
    if shutil.which("npm") is None:
        pytest.skip("npm not available on this sandbox")
    (tmp_path / "package.json").write_text(
        '{"name":"demo","scripts":{"test":"exit 0"}}\n'
    )
    choice = detect_test_runner(tmp_path, _Project(kind="library"))
    assert isinstance(choice, TestRunnerChoice)
    assert choice.tool == "npm"

    result = run_project_tests(choice, timeout=60)
    assert result.passed is True
    assert result.exit_code == 0
    assert result.timed_out is False


def test_pytest_failure(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\n\n[tool.pytest.ini_options]\naddopts = '-q'\n"
    )
    (tmp_path / "test_dummy.py").write_text(
        "def test_fail():\n    assert False\n"
    )
    choice = detect_test_runner(tmp_path, _Project(kind="library"))
    assert isinstance(choice, TestRunnerChoice)
    assert choice.tool == "pytest"

    result = run_project_tests(choice, timeout=60)
    assert result.passed is False
    assert result.exit_code not in (None, 0)
    assert result.timed_out is False


def test_no_test_script_detected_skips(tmp_path: Path) -> None:
    choice = detect_test_runner(tmp_path, _Project(kind="library"))
    assert choice is None


def test_runner_missing_binary_returns_failure(tmp_path: Path) -> None:
    # Regression: if the runner binary is absent (e.g. ``npm`` not
    # installed on a minimal host), ``subprocess.run`` raises
    # ``FileNotFoundError``. Before the fix this escaped ``verify_run``
    # and left the run wedged in ``running``; now we surface a plain
    # failed ``TestRunResult`` with ``exit_code=None`` and a descriptive
    # ``output_tail``.
    choice = TestRunnerChoice(
        cmd=["/nonexistent/niwa-test-binary", "--version"],
        tool="make",
        cwd=tmp_path,
    )
    result = run_project_tests(choice, timeout=5)
    assert result.passed is False
    assert result.exit_code is None
    assert result.timed_out is False
    assert "FileNotFoundError" in result.output_tail
