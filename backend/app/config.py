"""Configuration loading for Niwa v1.

Reads ``~/.niwa/config.toml`` if present. The file is optional in dev; when
absent we fall back to sensible defaults so the backend can boot.

Section naming matches the contract emitted by
``v1/templates/config.toml.tmpl`` (``[claude]``, ``[db]``, ``[executor]``)
and the env var name matches what the service templates export
(``com.niwa.executor.plist.tmpl`` / ``niwa-executor.service.tmpl``).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CONFIG_PATH = Path.home() / ".niwa" / "config.toml"
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "niwa-v1.sqlite3"
DEFAULT_CLAUDE_TIMEOUT_S = 1800
DEFAULT_EXECUTOR_POLL_INTERVAL_S = 5


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for the backend process."""

    db_path: Path
    bind_host: str
    bind_port: int
    claude_cli: str | None
    claude_timeout_s: int
    executor_poll_interval_s: int
    config_source: Path | None


def _load_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _resolve_config_path(config_path: Path | None) -> Path:
    """Pick the config file, preferring ``NIWA_CONFIG_PATH`` over ``NIWA_CONFIG``.

    ``NIWA_CONFIG_PATH`` is what the service templates
    (``com.niwa.executor.plist.tmpl`` / ``niwa-executor.service.tmpl``) export
    and the canonical name going forward. ``NIWA_CONFIG`` stays accepted as a
    deprecated alias so callers that still set it (e.g. legacy test fixtures)
    keep working. When both are defined they are expected to point at the same
    path in practice; if they diverge ``NIWA_CONFIG_PATH`` wins.
    """

    if config_path is not None:
        return config_path
    env = os.environ.get("NIWA_CONFIG_PATH") or os.environ.get("NIWA_CONFIG")
    return Path(env) if env else DEFAULT_CONFIG_PATH


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings, preferring the given path then the default location."""

    candidate = _resolve_config_path(config_path)
    data = _load_toml(candidate)

    claude = data.get("claude", {}) if isinstance(data, dict) else {}
    db = data.get("db", {}) if isinstance(data, dict) else {}
    executor = data.get("executor", {}) if isinstance(data, dict) else {}
    # ``[server]`` is not in the template today but we still read it when
    # present so operators who set host/port by hand don't regress.
    server = data.get("server", {}) if isinstance(data, dict) else {}

    claude_cli_raw = claude.get("cli")
    claude_cli = str(claude_cli_raw) if claude_cli_raw else None

    return Settings(
        db_path=Path(db.get("path", DEFAULT_DB_PATH)).expanduser(),
        bind_host=str(server.get("host", "127.0.0.1")),
        bind_port=int(server.get("port", 8000)),
        claude_cli=claude_cli,
        claude_timeout_s=int(claude.get("timeout", DEFAULT_CLAUDE_TIMEOUT_S)),
        executor_poll_interval_s=int(
            executor.get("poll_interval_seconds", DEFAULT_EXECUTOR_POLL_INTERVAL_S)
        ),
        config_source=candidate if candidate.is_file() else None,
    )
