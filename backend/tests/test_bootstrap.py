"""Subprocess tests for ``bootstrap.sh``.

Each test runs the shell script against an isolated ``HOME`` (``tmp_path``)
with ``NIWA_BOOTSTRAP_SKIP_NPM=1`` so CI doesn't spend time on ``npm``. The
tests cover the four scenarios declared in the PR-V1-14 brief:

* fresh install creates layout, venv, DB, config, service file
* rerun is idempotent and preserves an existing ``config.toml``
* missing ``python3`` makes the script exit fast with a legible error
* placeholders in the config template are fully substituted

The script lives at ``<repo>/bootstrap.sh``; it must exist and be
executable before these tests pass.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_DIR = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO_DIR / "bootstrap.sh"


def _service_relpath() -> str:
    """Return the expected service file relative to ``$HOME`` for this OS."""

    system = platform.system()
    if system == "Darwin":
        return "Library/LaunchAgents/com.niwa.executor.plist"
    if system == "Linux":
        return ".config/systemd/user/niwa-executor.service"
    pytest.skip(f"bootstrap.sh not supported on {system}")
    raise AssertionError("unreachable")  # pragma: no cover — skip raises


def _run_bootstrap(
    home: Path, *, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ``bootstrap.sh`` with ``HOME=home`` and npm skipped."""

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["NIWA_BOOTSTRAP_SKIP_NPM"] = "1"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(BOOTSTRAP)],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_bootstrap_script_is_executable() -> None:
    """The shell script exists and has the executable bit set."""

    assert BOOTSTRAP.is_file(), f"missing {BOOTSTRAP}"
    assert os.access(BOOTSTRAP, os.X_OK), f"{BOOTSTRAP} must be executable"


def test_fresh_install_creates_layout_and_config(tmp_path: Path) -> None:
    """HOME empty → bootstrap creates layout, DB, config, service file."""

    result = _run_bootstrap(tmp_path)
    assert result.returncode == 0, result.stderr

    niwa = tmp_path / ".niwa"
    assert (niwa / "venv" / "bin" / "python").exists()
    assert (niwa / "logs").is_dir()
    assert (niwa / "data" / "niwa-v1.sqlite3").exists()

    config = (niwa / "config.toml").read_text()
    assert 'cli = "' in config
    # Placeholders must be fully replaced — no literal ``{{...}}`` left over.
    assert "{{" not in config
    assert str(tmp_path) in config  # ``$HOME`` substitution landed

    service = tmp_path / _service_relpath()
    assert service.exists(), f"service file not written: {service}"

    # The promotion from ``v1/`` to repo root (PR-V1-25) exposed two
    # template regressions with ``{{REPO_DIR}}/v1/backend`` hardcoded
    # in the plist/systemd units. Assert the rendered service file has
    # no ``v1/`` leftovers and points at the real ``<repo>/backend``.
    service_content = service.read_text()
    assert "/v1/backend" not in service_content, (
        f"service file still references v1/backend:\n{service_content}"
    )
    assert f"{REPO_DIR}/backend" in service_content, (
        f"service file does not point to {REPO_DIR}/backend:\n{service_content}"
    )


def test_rerun_is_idempotent(tmp_path: Path) -> None:
    """Two runs in a row: config.toml is preserved between them."""

    first = _run_bootstrap(tmp_path)
    assert first.returncode == 0, first.stderr

    config_path = tmp_path / ".niwa" / "config.toml"
    sentinel = "\n# user-edited-sentinel\n"
    config_path.write_text(config_path.read_text() + sentinel)
    db_path = tmp_path / ".niwa" / "data" / "niwa-v1.sqlite3"
    db_mtime_before = db_path.stat().st_mtime

    second = _run_bootstrap(tmp_path)
    assert second.returncode == 0, second.stderr

    assert sentinel in config_path.read_text(), "config.toml was overwritten"
    # DB stays as a single file after ``alembic upgrade head`` re-runs
    # against an already-migrated schema.
    assert db_path.exists()
    assert db_path.stat().st_mtime >= db_mtime_before


def test_missing_python_fails_fast(tmp_path: Path) -> None:
    """With an empty ``PATH`` the script aborts with exit ≠ 0 and names Python."""

    # ``bash`` itself still needs to be locatable; pin the PATH to just the
    # directory containing ``bash`` so ``python3``/``npm``/``git`` are missing.
    bash_dir = str(Path(shutil.which("bash") or "/bin/bash").parent)
    result = _run_bootstrap(tmp_path, extra_env={"PATH": bash_dir})
    assert result.returncode != 0
    combined = f"{result.stdout}\n{result.stderr}".lower()
    assert "python" in combined


def test_config_substitution_replaces_placeholders(tmp_path: Path) -> None:
    """The rendered config.toml contains neither ``{{CLAUDE_CLI_PATH}}`` nor ``{{HOME}}``."""

    result = _run_bootstrap(tmp_path)
    assert result.returncode == 0, result.stderr

    config = (tmp_path / ".niwa" / "config.toml").read_text()
    assert "{{CLAUDE_CLI_PATH}}" not in config
    assert "{{HOME}}" not in config


def test_bootstrap_prefers_python311(tmp_path: Path) -> None:
    """When both ``python3`` and ``python3.11`` exist on PATH, bootstrap picks 3.11.

    Regression for fresh-install friction on macOS + brew, where ``python3``
    points to 3.13 but ``python3.11`` is the keg that Niwa actually needs.
    The bootstrap must pick ``python3.11`` explicitly.

    Setup: place a ``python3`` shim that reports an unsupported version
    (3.9) first on PATH, alongside the real ``python3.11``. Pre-fix, the
    script picks ``python3``, fails the version gate and exits non-zero.
    Post-fix, ``python3.11`` is preferred and the script completes.
    """

    real_python311 = shutil.which("python3.11")
    if real_python311 is None:
        pytest.skip("python3.11 not available on this host")

    # Shim dir with a fake ``python3`` that reports 3.9 and a real
    # ``python3.11`` symlinked to the host's interpreter.
    shim_dir = tmp_path / "shims"
    shim_dir.mkdir()
    fake_python3 = shim_dir / "python3"
    fake_python3.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "--version" ]]; then\n'
        '    echo "Python 3.9.0"\n'
        "    exit 0\n"
        "fi\n"
        "# Any other invocation: fail the version gate.\n"
        'if [[ "$1" == "-c" ]]; then\n'
        "    exit 1\n"
        "fi\n"
        "exit 1\n"
    )
    fake_python3.chmod(0o755)
    (shim_dir / "python3.11").symlink_to(real_python311)

    # Symlink the helper binaries the script uses (npm is skipped, but
    # bash/git plus coreutils are invoked). Put our shim dir first.
    helpers = (
        "bash",
        "cat",
        "command",
        "dirname",
        "git",
        "mkdir",
        "npm",
        "sed",
        "uname",
    )
    for name in helpers:
        path = shutil.which(name)
        if path is None:
            continue  # builtins like ``command`` are shell-level, skip if absent
        (shim_dir / name).symlink_to(path)

    home = tmp_path / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "NIWA_BOOTSTRAP_SKIP_NPM": "1",
        "PATH": str(shim_dir),
    }
    # Preserve SYSTEMROOT on Windows CI; here we mostly rely on the small
    # curated env to make the PATH restriction meaningful.
    result = subprocess.run(
        ["bash", str(BOOTSTRAP)],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"bootstrap exited {result.returncode} with restricted PATH\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    # The venv's interpreter must be (a link to) python3.11, not the fake.
    venv_python = home / ".niwa" / "venv" / "bin" / "python"
    assert venv_python.exists()
    pyvenv_cfg = (home / ".niwa" / "venv" / "pyvenv.cfg").read_text()
    # ``home`` path layout reveals which binary created the venv. Either
    # pyvenv.cfg's ``home`` line or ``version`` line should expose 3.11.
    assert "3.11" in pyvenv_cfg, f"pyvenv.cfg does not reference 3.11:\n{pyvenv_cfg}"
