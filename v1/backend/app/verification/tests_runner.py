"""E5 — project tests runner (PR-V1-11c).

Last link of the SPEC §5 evidence chain. If the task's project declares
a test script (Makefile, ``npm test``, or pytest), we run it and use the
exit code as the verification signal. If nothing is detected (or the
project is ``kind=script``) we skip gracefully — ``evidence.tests_ran``
stays ``False`` and E5 passes vacuously.

Only stdlib: ``subprocess`` for the run, ``tomllib`` (stdlib 3.11+) for
``pyproject.toml``, ``json`` for ``package.json``. No new dependency.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# Last 4 KB of combined stdout/stderr is stored on the run. Enough to
# recognise which test failed without bloating the DB.
_OUTPUT_TAIL_BYTES = 4096

# ``^test:`` at column 0 is Make's rule-definition marker. We grep the
# raw file rather than invoking ``make -n`` because that would execute
# arbitrary recipes during detection — opposite of the brief.
_MAKE_TEST_RULE = re.compile(r"^test\s*:", re.MULTILINE)


@dataclass
class TestRunnerChoice:
    """Resolved runner: the command to invoke, its label, and the cwd."""

    # Tell pytest not to collect this dataclass as a test class despite
    # its ``Test`` prefix — ``__init__`` on a dataclass trips collection.
    __test__ = False

    cmd: list[str]
    tool: str  # "make" | "npm" | "pytest"
    cwd: Path


@dataclass
class TestRunResult:
    """Outcome of a single ``run_project_tests`` invocation."""

    __test__ = False

    passed: bool           # exit_code == 0 and not timed_out
    exit_code: int | None  # None only when timed_out
    timed_out: bool
    duration_s: float
    output_tail: str       # last 4 KB of stdout+stderr combined


def _makefile_has_test_rule(cwd: Path) -> bool:
    mk = cwd / "Makefile"
    if not mk.is_file():
        return False
    try:
        content = mk.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_MAKE_TEST_RULE.search(content))


def _package_json_has_test_script(cwd: Path) -> bool:
    pj = cwd / "package.json"
    if not pj.is_file():
        return False
    try:
        data = json.loads(pj.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return False
    test_cmd = scripts.get("test")
    return isinstance(test_cmd, str) and test_cmd.strip() != ""


def _pyproject_declares_pytest(cwd: Path) -> bool:
    """Heuristic: pytest is declared if ``[tool.pytest*]`` exists or
    ``pytest`` is pinned under ``[project.optional-dependencies].test``.

    We only *detect* — we don't assert pytest is installed. If it isn't,
    the subprocess will exit non-zero and E5 will report ``tests_failed``
    with the import error in ``output_tail``.
    """

    pp = cwd / "pyproject.toml"
    if not pp.is_file():
        return False
    try:
        with pp.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return False
    tool = data.get("tool") if isinstance(data, dict) else None
    if isinstance(tool, dict) and any(k.startswith("pytest") for k in tool):
        return True
    project = data.get("project") if isinstance(data, dict) else None
    if isinstance(project, dict):
        opt = project.get("optional-dependencies")
        if isinstance(opt, dict):
            test_deps = opt.get("test")
            if isinstance(test_deps, list):
                for dep in test_deps:
                    if isinstance(dep, str) and re.match(r"^\s*pytest\b", dep):
                        return True
    return False


def detect_test_runner(cwd: Path, project: Any) -> TestRunnerChoice | None:
    """Pick the first matching runner; return ``None`` to skip E5.

    Order matters: Makefile wins over ``npm`` wins over pytest. A script
    project (``kind=="script"``) skips unconditionally — no ``test``
    target is expected on ad-hoc scripts. The reason-code that lands in
    ``evidence.test_reason`` is decided by the orchestrator from the
    combination of ``project.kind`` and the ``None`` return.
    """

    kind = getattr(project, "kind", None)
    if kind == "script":
        return None

    cwd_path = Path(cwd)
    if _makefile_has_test_rule(cwd_path):
        return TestRunnerChoice(
            cmd=["make", "test", "-s"], tool="make", cwd=cwd_path
        )
    if _package_json_has_test_script(cwd_path):
        return TestRunnerChoice(
            cmd=["npm", "test", "--silent"], tool="npm", cwd=cwd_path
        )
    if _pyproject_declares_pytest(cwd_path):
        return TestRunnerChoice(
            cmd=["python", "-m", "pytest", "-q"], tool="pytest", cwd=cwd_path
        )
    return None


def _tail(stdout: str | None, stderr: str | None) -> str:
    blob = (stdout or "") + (stderr or "")
    if len(blob) <= _OUTPUT_TAIL_BYTES:
        return blob
    return blob[-_OUTPUT_TAIL_BYTES:]


def run_project_tests(
    choice: TestRunnerChoice, *, timeout: int = 300
) -> TestRunResult:
    """Run ``choice.cmd`` in ``choice.cwd`` with a hard timeout.

    ``subprocess.run`` handles the kill on timeout and re-raises
    ``TimeoutExpired`` with whatever partial output it captured; we
    record that same tail so the operator sees where it got stuck.
    """

    start = time.monotonic()
    try:
        proc = subprocess.run(
            choice.cmd,
            cwd=str(choice.cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - start
        return TestRunResult(
            passed=False,
            exit_code=None,
            timed_out=True,
            duration_s=duration,
            output_tail=_tail(exc.stdout, exc.stderr),
        )

    duration = time.monotonic() - start
    exit_code = proc.returncode
    return TestRunResult(
        passed=exit_code == 0,
        exit_code=exit_code,
        timed_out=False,
        duration_s=duration,
        output_tail=_tail(proc.stdout, proc.stderr),
    )


__all__ = [
    "TestRunResult",
    "TestRunnerChoice",
    "detect_test_runner",
    "run_project_tests",
]
