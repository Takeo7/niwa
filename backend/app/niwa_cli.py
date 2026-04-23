"""``niwa-executor`` CLI — launcher + status + logs for the v1 executor.

Thin wrapper over ``launchctl`` (macOS) / ``systemctl --user`` (Linux).
PR-V1-14 writes the service file; this CLI loads/starts/stops/watches
it. Everything is stdlib; the module is registered as the
``niwa-executor`` entry point of the backend package so after
``pip install -e v1/backend`` inside the ``~/.niwa/venv`` the command
``niwa-executor <subcmd>`` is on PATH.

Subcommands: ``start | stop | restart | status | logs``.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path


NIWA_HOME = Path(os.environ.get("NIWA_HOME", str(Path.home() / ".niwa")))
LOG_PATH = NIWA_HOME / "logs" / "executor.log"

# macOS
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "com.niwa.executor.plist"
LAUNCHD_LABEL = "com.niwa.executor"

# Linux
SYSTEMD_UNIT = "niwa-executor.service"


def _run(cmd: list[str], *, inherit_stdio: bool = False) -> int:
    """Run ``cmd`` and return its exit code.

    ``inherit_stdio`` lets the child own the terminal (used by ``status``
    and ``logs`` so the user sees output live and can Ctrl-C ``tail -f``).
    Missing binaries (``FileNotFoundError``) become exit 127 with a
    human-friendly message on stderr.
    """

    try:
        if inherit_stdio:
            result = subprocess.run(cmd)
        else:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.stdout:
                sys.stdout.write(result.stdout)
            if result.stderr:
                sys.stderr.write(result.stderr)
        return result.returncode
    except FileNotFoundError:
        sys.stderr.write(f"command not found: {cmd[0]}\n")
        return 127


def _ensure_plist_exists() -> bool:
    """Return ``True`` if the launchd plist exists.

    On miss, prints a useful error to stderr and returns ``False`` so
    the caller can propagate exit code 1 without raising ``SystemExit``
    (makes the CLI testable without ``pytest.raises``).
    """

    if not PLIST_PATH.exists():
        sys.stderr.write(
            f"service file missing at {PLIST_PATH}; "
            "run ./bootstrap.sh first\n"
        )
        return False
    return True


def _unsupported() -> int:
    sys.stderr.write(f"Unsupported OS: {platform.system()}\n")
    return 1


def cmd_start(args: argparse.Namespace) -> int:
    system = platform.system()
    if system == "Darwin":
        if not _ensure_plist_exists():
            return 1
        return _run(["launchctl", "load", "-w", str(PLIST_PATH)])
    if system == "Linux":
        return _run(
            ["systemctl", "--user", "enable", "--now", SYSTEMD_UNIT]
        )
    return _unsupported()


def cmd_stop(args: argparse.Namespace) -> int:
    system = platform.system()
    if system == "Darwin":
        return _run(["launchctl", "unload", "-w", str(PLIST_PATH)])
    if system == "Linux":
        return _run(
            ["systemctl", "--user", "disable", "--now", SYSTEMD_UNIT]
        )
    return _unsupported()


def cmd_restart(args: argparse.Namespace) -> int:
    system = platform.system()
    if system == "Darwin":
        if not _ensure_plist_exists():
            return 1
        target = f"gui/{os.getuid()}/{LAUNCHD_LABEL}"
        return _run(["launchctl", "kickstart", "-k", target])
    if system == "Linux":
        return _run(["systemctl", "--user", "restart", SYSTEMD_UNIT])
    return _unsupported()


def cmd_status(args: argparse.Namespace) -> int:
    system = platform.system()
    if system == "Darwin":
        return _run(
            ["launchctl", "list", LAUNCHD_LABEL], inherit_stdio=True
        )
    if system == "Linux":
        return _run(
            ["systemctl", "--user", "status", SYSTEMD_UNIT],
            inherit_stdio=True,
        )
    return _unsupported()


def cmd_logs(args: argparse.Namespace) -> int:
    if not LOG_PATH.exists():
        sys.stdout.write(
            f"log not found at {LOG_PATH}; "
            "run 'niwa-executor start' first\n"
        )
        return 1
    cmd = ["tail", "-n", str(args.lines)]
    if args.follow:
        cmd.append("-f")
    cmd.append(str(LOG_PATH))
    return _run(cmd, inherit_stdio=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="niwa-executor",
        description="Launcher for the Niwa v1 executor service.",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)
    sub.add_parser("start", help="load + start the executor service")
    sub.add_parser("stop", help="stop + unload the executor service")
    sub.add_parser("restart", help="restart (reloads the service file)")
    sub.add_parser("status", help="print service status")
    logs = sub.add_parser("logs", help="tail ~/.niwa/logs/executor.log")
    logs.add_argument(
        "--follow", "-f", action="store_true", help="follow log output",
    )
    logs.add_argument(
        "--lines", "-n", type=int, default=50,
        help="lines from the end of the log (default: 50)",
    )
    return parser


_DISPATCH = {
    "start": cmd_start,
    "stop": cmd_stop,
    "restart": cmd_restart,
    "status": cmd_status,
    "logs": cmd_logs,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = _DISPATCH[args.subcommand]
    return handler(args)


if __name__ == "__main__":  # pragma: no cover — direct invocation
    raise SystemExit(main())
