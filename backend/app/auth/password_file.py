"""Admin password stored in ~/.niwa/auth/password.hash.

Auth is disabled if the file does not exist (local-only dev mode).
"""

from __future__ import annotations

import os
from pathlib import Path


def _auth_dir() -> Path:
    return Path(os.environ.get("NIWA_HOME", Path.home() / ".niwa")) / "auth"


def is_auth_enabled() -> bool:
    """Return True when a password hash file exists."""
    return (_auth_dir() / "password.hash").is_file()


def get_password_hash() -> str | None:
    f = _auth_dir() / "password.hash"
    return f.read_text().strip() if f.is_file() else None


def set_password_hash(hash_str: str) -> None:
    d = _auth_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "password.hash").write_text(hash_str + "\n", encoding="utf-8")
    (d / "password.hash").chmod(0o600)
