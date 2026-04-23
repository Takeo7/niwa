"""Unit tests for the ``niwa-executor`` CLI (PR-V1-15).

Every test mocks ``platform.system`` and ``subprocess.run`` so no real
``launchctl``/``systemctl``/``tail`` ever runs. ``NIWA_HOME`` is
overridden via ``monkeypatch.setenv`` so the module's path constants
resolve inside ``tmp_path``. Tests import ``app.niwa_cli`` lazily (via
``importlib.reload``) because the module resolves ``NIWA_HOME`` at
import time.
"""

from __future__ import annotations

import importlib
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


def _load_cli(monkeypatch: pytest.MonkeyPatch, niwa_home: Path):
    """Reload ``app.niwa_cli`` so module-level path constants see the
    patched ``NIWA_HOME`` env var."""

    monkeypatch.setenv("NIWA_HOME", str(niwa_home))
    import app.niwa_cli as cli  # noqa: WPS433 — intentional late import
    return importlib.reload(cli)


def _stub_run(
    monkeypatch: pytest.MonkeyPatch, rc: int = 0
) -> list[list[str]]:
    """Capture all ``subprocess.run`` argv lists and force a fixed rc."""

    calls: list[list[str]] = []

    def fake_run(args, *a, **kw):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, rc, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def _set_platform(monkeypatch: pytest.MonkeyPatch, system: str) -> None:
    monkeypatch.setattr("platform.system", lambda: system)


def test_start_macos_calls_launchctl_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = _load_cli(monkeypatch, tmp_path)
    _set_platform(monkeypatch, "Darwin")
    # fake plist must exist for ``start`` to proceed
    plist = tmp_path / "LaunchAgents" / "com.niwa.executor.plist"
    plist.parent.mkdir(parents=True)
    plist.write_text("<plist/>\n")
    monkeypatch.setattr(cli, "PLIST_PATH", plist)
    calls = _stub_run(monkeypatch)

    assert cli.main(["start"]) == 0
    assert calls == [["launchctl", "load", "-w", str(plist)]]


def test_start_linux_calls_systemctl_enable_now(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = _load_cli(monkeypatch, tmp_path)
    _set_platform(monkeypatch, "Linux")
    calls = _stub_run(monkeypatch)

    assert cli.main(["start"]) == 0
    assert calls == [
        ["systemctl", "--user", "enable", "--now", "niwa-executor.service"]
    ]


def test_start_macos_fails_when_plist_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = _load_cli(monkeypatch, tmp_path)
    _set_platform(monkeypatch, "Darwin")
    monkeypatch.setattr(
        cli, "PLIST_PATH", tmp_path / "nope" / "com.niwa.executor.plist"
    )
    # stub subprocess.run so an accidental call would be visible
    calls = _stub_run(monkeypatch)

    assert cli.main(["start"]) == 1
    assert calls == []  # never reached launchctl
    err = capsys.readouterr().err
    assert "service file missing" in err


@pytest.mark.parametrize(
    ("system", "expected"),
    [
        ("Darwin", ["launchctl", "unload", "-w"]),
        ("Linux", [
            "systemctl", "--user", "disable", "--now", "niwa-executor.service"
        ]),
    ],
)
def test_stop_dispatches_correct_cmd_per_platform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    expected: list[str],
) -> None:
    cli = _load_cli(monkeypatch, tmp_path)
    _set_platform(monkeypatch, system)
    calls = _stub_run(monkeypatch)

    assert cli.main(["stop"]) == 0
    assert len(calls) == 1
    # Darwin argv includes the PLIST_PATH trailing; compare prefix only
    assert calls[0][: len(expected)] == expected


def test_status_returns_subcmd_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = _load_cli(monkeypatch, tmp_path)
    _set_platform(monkeypatch, "Linux")
    _stub_run(monkeypatch, rc=3)

    assert cli.main(["status"]) == 3


def test_logs_missing_file_returns_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = _load_cli(monkeypatch, tmp_path)
    _set_platform(monkeypatch, "Linux")
    calls = _stub_run(monkeypatch)

    assert cli.main(["logs"]) == 1
    assert calls == []
    out = capsys.readouterr().out + capsys.readouterr().err
    assert "log not found" in out or "run 'niwa-executor start'" in out


def test_logs_invokes_tail_with_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = _load_cli(monkeypatch, tmp_path)
    _set_platform(monkeypatch, "Linux")
    log_path = tmp_path / "logs" / "executor.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("hello\n")
    monkeypatch.setattr(cli, "LOG_PATH", log_path)
    calls = _stub_run(monkeypatch)

    assert cli.main(["logs", "--lines", "100"]) == 0
    assert calls == [["tail", "-n", "100", str(log_path)]]


def test_unsupported_os_returns_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = _load_cli(monkeypatch, tmp_path)
    _set_platform(monkeypatch, "Windows")
    calls = _stub_run(monkeypatch)

    assert cli.main(["status"]) == 1
    assert calls == []
    err = capsys.readouterr().err
    assert "Unsupported OS" in err


def test_run_captures_file_not_found_returns_127(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = _load_cli(monkeypatch, tmp_path)
    _set_platform(monkeypatch, "Linux")

    def missing(args, *a, **kw):
        raise FileNotFoundError(args[0])

    monkeypatch.setattr(subprocess, "run", missing)

    assert cli.main(["status"]) == 127
    err = capsys.readouterr().err
    assert "systemctl" in err or "not found" in err
