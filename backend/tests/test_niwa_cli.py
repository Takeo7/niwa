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
import os
import signal
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


# ---- PR-V1-31: update subcommand ----


def _stub_update(monkeypatch, cli, repo, *, same_sha, diff_files):
    monkeypatch.setattr(cli, "_resolve_repo_path", lambda _o=None: repo)
    calls: list[list[str]] = []

    def fake(args, *a, **kw):
        calls.append(list(args))
        out = ""
        if "rev-parse" in args:
            out = "A\n" if ("HEAD" in args or same_sha) else "B\n"
        elif "diff" in args:
            out = diff_files
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")

    monkeypatch.setattr(subprocess, "run", fake)
    return calls


def test_update_skips_when_already_up_to_date(tmp_path, monkeypatch, capsys):
    cli = _load_cli(monkeypatch, tmp_path)
    calls = _stub_update(monkeypatch, cli, tmp_path, same_sha=True, diff_files="")
    assert cli.main(["update"]) == 0
    joined = [" ".join(c) for c in calls]
    assert not any("pip" in s or "alembic" in s for s in joined)
    assert "up to date" in capsys.readouterr().out.lower()


def test_update_runs_pip_when_pyproject_changed(tmp_path, monkeypatch):
    cli = _load_cli(monkeypatch, tmp_path)
    calls = _stub_update(
        monkeypatch, cli, tmp_path, same_sha=False,
        diff_files="backend/pyproject.toml\nREADME.md\n",
    )
    monkeypatch.setattr(cli, "cmd_restart", lambda _a: 0)
    assert cli.main(["update"]) == 0
    expected_pip = str(Path.home() / ".niwa" / "venv" / "bin" / "pip")
    pip_calls = [c for c in calls if c and c[0] == expected_pip]
    assert pip_calls, f"no pip call at venv-absolute path; calls={calls}"
    assert pip_calls[0][:3] == [expected_pip, "install", "-e"]
    assert not any("alembic" in " ".join(c) for c in calls)


def test_update_with_no_restart_skips_restart(tmp_path, monkeypatch):
    cli = _load_cli(monkeypatch, tmp_path)
    _stub_update(monkeypatch, cli, tmp_path, same_sha=False, diff_files="")
    seen = {"r": 0}
    monkeypatch.setattr(
        cli, "cmd_restart", lambda _a: (seen.update(r=seen["r"] + 1) or 0),
    )
    assert cli.main(["update", "--no-restart"]) == 0
    assert seen["r"] == 0


# ---- PR-V1-32: dev start/stop/status ----


def _seed_pids(tmp_path: Path, uv: str, vt: str) -> Path:
    run = tmp_path / "run"
    run.mkdir(parents=True)
    (run / "uvicorn.pid").write_text(uv + "\n")
    (run / "vite.pid").write_text(vt + "\n")
    return run


def test_dev_start_detach_writes_pid_files(tmp_path, monkeypatch):
    cli = _load_cli(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    (repo / "frontend" / "node_modules").mkdir(parents=True)
    (repo / "backend").mkdir(parents=True)
    (tmp_path / "venv" / "bin").mkdir(parents=True)
    (tmp_path / "venv" / "bin" / "uvicorn").write_text("")
    monkeypatch.setattr(cli, "_resolve_repo_path", lambda _o=None: repo)
    monkeypatch.setattr(cli, "NIWA_HOME", tmp_path)
    pids = iter([4242, 4343])
    monkeypatch.setattr(
        subprocess, "Popen",
        lambda *a, **kw: type("P", (), {"pid": next(pids)})(),
    )
    assert cli.main(["dev", "start", "--detach"]) == 0
    assert (tmp_path / "run" / "uvicorn.pid").read_text().strip() == "4242"
    assert (tmp_path / "run" / "vite.pid").read_text().strip() == "4343"


def test_dev_stop_kills_pids_from_files(tmp_path, monkeypatch):
    cli = _load_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "NIWA_HOME", tmp_path)
    run = _seed_pids(tmp_path, "100", "200")
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: calls.append((pid, sig)))
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    assert cli.main(["dev", "stop"]) == 0
    assert {(100, signal.SIGTERM), (200, signal.SIGTERM),
            (100, signal.SIGKILL), (200, signal.SIGKILL)} <= set(calls)
    assert not (run / "uvicorn.pid").exists()
    assert not (run / "vite.pid").exists()


def test_dev_stop_no_pid_files_is_noop(tmp_path, monkeypatch, capsys):
    cli = _load_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "NIWA_HOME", tmp_path)
    assert cli.main(["dev", "stop"]) == 0
    assert "no dev process running" in capsys.readouterr().out


def test_dev_status_reports_alive_or_dead(tmp_path, monkeypatch, capsys):
    cli = _load_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "NIWA_HOME", tmp_path)
    _seed_pids(tmp_path, "111", "222")

    def fake_kill(pid, sig):
        if pid == 222:
            raise ProcessLookupError(pid)

    monkeypatch.setattr(os, "kill", fake_kill)
    assert cli.main(["dev", "status"]) == 0
    out = capsys.readouterr().out
    assert "uvicorn: alive" in out and "111" in out
    assert "vite:" in out and "dead" in out
