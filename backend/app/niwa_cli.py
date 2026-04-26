"""``niwa-executor`` CLI — launcher + status + logs for the v1 executor.

Thin wrapper over ``launchctl`` (macOS) / ``systemctl --user`` (Linux).
PR-V1-14 writes the service file; this CLI loads/starts/stops/watches
it. Everything is stdlib; the module is registered as the
``niwa-executor`` entry point of the backend package so after
``pip install -e backend`` inside the ``~/.niwa/venv`` the command
``niwa-executor <subcmd>`` is on PATH.

Subcommands: ``start | stop | restart | status | logs | update``.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

import app as _app_pkg


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


def _resolve_repo_path(override: str | None = None) -> Path | None:
    """Walk up from ``app/__init__.py`` looking for ``.git/``."""
    if override:
        c = Path(override).expanduser().resolve()
        return c if (c / ".git").exists() else None
    for p in Path(_app_pkg.__file__).resolve().parents:
        if (p / ".git").exists():
            return p
    return None


def cmd_update(args: argparse.Namespace) -> int:
    repo = _resolve_repo_path(getattr(args, "repo_path", None))
    if repo is None:
        sys.stderr.write("could not locate Niwa git repo; pass --repo-path\n")
        return 1
    git = ["git", "-C", str(repo)]
    out = lambda c: subprocess.run(c, capture_output=True, text=True).stdout or ""  # noqa: E731
    if _run(git + ["fetch", "origin", "main"]) != 0:
        return 1
    before = out(git + ["rev-parse", "HEAD"]).strip()
    if before == out(git + ["rev-parse", "origin/main"]).strip():
        sys.stdout.write("Already up to date.\n")
        return 0
    if _run(git + ["pull", "origin", "main", "--ff-only"]) != 0:
        sys.stderr.write(
            f"git pull --ff-only failed in {repo}; resolve divergence "
            "manually (git fetch && git rebase origin/main).\n"
        )
        return 1
    after = out(git + ["rev-parse", "HEAD"]).strip()
    changed = out(git + ["diff", "--name-only", f"{before}..{after}"]).splitlines()
    summary, bin_ = ["pulled origin/main"], Path.home() / ".niwa" / "venv" / "bin"
    if "backend/pyproject.toml" in changed:
        if _run([str(bin_ / "pip"), "install", "-e", str(repo / "backend")]) != 0:
            return 1
        summary.append("reinstalled backend")
    if any(p.startswith("backend/migrations/versions/") for p in changed):
        from app.config import load_settings
        url = f"sqlite:///{load_settings().db_path}"
        if _run([str(bin_ / "alembic"), "-x", f"db_url={url}", "upgrade", "head"]) != 0:
            return 1
        summary.append("applied migrations")
    if not args.no_restart:
        if cmd_restart(args) != 0:
            return 1
        summary.append("restarted executor")
    sys.stdout.write("update done: " + ", ".join(summary) + ".\n")
    return 0


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
    update = sub.add_parser("update", help="pull + pip + alembic + restart")
    update.add_argument("--no-restart", action="store_true")
    update.add_argument("--repo-path", default=None)
    return parser


_DISPATCH = {
    "start": cmd_start,
    "stop": cmd_stop,
    "restart": cmd_restart,
    "status": cmd_status,
    "logs": cmd_logs,
    "update": cmd_update,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = _DISPATCH[args.subcommand]
    return handler(args)


if __name__ == "__main__":  # pragma: no cover — direct invocation
    raise SystemExit(main())
