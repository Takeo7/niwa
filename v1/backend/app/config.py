"""Configuration loading for Niwa v1.

Reads ``~/.niwa/config.toml`` if present. The file is optional in dev; when
absent we fall back to sensible defaults so the backend can boot. Actual
consumption of every field lands in later PRs — this module only exposes the
loader and the settings object.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CONFIG_PATH = Path.home() / ".niwa" / "config.toml"
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "niwa-v1.sqlite3"


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for the backend process."""

    db_path: Path
    bind_host: str
    bind_port: int
    config_source: Path | None


def _load_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings, preferring the given path then the default location."""

    candidate = config_path or Path(os.environ.get("NIWA_CONFIG", DEFAULT_CONFIG_PATH))
    data = _load_toml(candidate)

    server = data.get("server", {}) if isinstance(data, dict) else {}
    db = data.get("database", {}) if isinstance(data, dict) else {}

    return Settings(
        db_path=Path(db.get("path", DEFAULT_DB_PATH)).expanduser(),
        bind_host=str(server.get("host", "127.0.0.1")),
        bind_port=int(server.get("port", 8000)),
        config_source=candidate if candidate.is_file() else None,
    )
