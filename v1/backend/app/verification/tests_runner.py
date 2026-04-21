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
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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


__all__ = [
    "TestRunnerChoice",
    "detect_test_runner",
]
