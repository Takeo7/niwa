"""Tests for ``app.config`` — alignment with templates (FIX-20260421).

The config parser must match the contract emitted by
``v1/templates/config.toml.tmpl`` (sections ``[claude]``, ``[db]``,
``[executor]``) and honour the env var name used by the service templates
(``NIWA_CONFIG_PATH``). Historical ``NIWA_CONFIG`` is still accepted as an
alias so pre-fix tests (see ``test_models.py``) keep passing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import load_settings


TEMPLATE_TOML = """\
[claude]
cli = "{cli}"
timeout = 2400

[db]
path = "{db}"

[executor]
poll_interval_seconds = 9
"""


def _write_toml(tmp_path: Path, *, name: str = "config.toml", **fmt: str) -> Path:
    path = tmp_path / name
    path.write_text(TEMPLATE_TOML.format(**fmt))
    return path


def test_niwa_config_path_is_preferred_over_niwa_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When both env vars are set, ``NIWA_CONFIG_PATH`` wins."""

    winner = _write_toml(
        tmp_path,
        name="winner.toml",
        cli="/opt/winner/claude",
        db=str(tmp_path / "winner.sqlite3"),
    )
    loser = _write_toml(
        tmp_path,
        name="loser.toml",
        cli="/opt/loser/claude",
        db=str(tmp_path / "loser.sqlite3"),
    )

    monkeypatch.setenv("NIWA_CONFIG_PATH", str(winner))
    monkeypatch.setenv("NIWA_CONFIG", str(loser))

    settings = load_settings()

    assert settings.config_source == winner
    assert settings.claude_cli == "/opt/winner/claude"
    assert settings.db_path == tmp_path / "winner.sqlite3"


def test_niwa_config_alias_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``NIWA_CONFIG`` keeps working as a deprecated alias."""

    path = _write_toml(
        tmp_path,
        cli="/usr/local/bin/claude",
        db=str(tmp_path / "legacy.sqlite3"),
    )
    monkeypatch.delenv("NIWA_CONFIG_PATH", raising=False)
    monkeypatch.setenv("NIWA_CONFIG", str(path))

    settings = load_settings()

    assert settings.config_source == path
    assert settings.db_path == tmp_path / "legacy.sqlite3"


def test_claude_section_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``[claude].cli`` and ``[claude].timeout`` land on ``Settings``."""

    path = _write_toml(
        tmp_path,
        cli="/some/where/claude",
        db=str(tmp_path / "db.sqlite3"),
    )
    monkeypatch.delenv("NIWA_CONFIG", raising=False)
    monkeypatch.setenv("NIWA_CONFIG_PATH", str(path))

    settings = load_settings()

    assert settings.claude_cli == "/some/where/claude"
    assert settings.claude_timeout_s == 2400


def test_db_section_replaces_database_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``[db].path`` is authoritative; legacy ``[database].path`` is ignored."""

    expected = tmp_path / "real.sqlite3"
    decoy = tmp_path / "ignored.sqlite3"
    path = tmp_path / "config.toml"
    path.write_text(
        f'[db]\npath = "{expected}"\n[database]\npath = "{decoy}"\n'
    )
    monkeypatch.delenv("NIWA_CONFIG", raising=False)
    monkeypatch.setenv("NIWA_CONFIG_PATH", str(path))

    assert load_settings().db_path == expected


def test_executor_section_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``[executor].poll_interval_seconds`` lands on ``Settings``."""

    path = _write_toml(
        tmp_path,
        cli="/bin/claude",
        db=str(tmp_path / "db.sqlite3"),
    )
    monkeypatch.delenv("NIWA_CONFIG", raising=False)
    monkeypatch.setenv("NIWA_CONFIG_PATH", str(path))

    settings = load_settings()

    assert settings.executor_poll_interval_s == 9


def test_missing_toml_falls_back_to_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-existent config path yields sensible defaults (no raise)."""

    missing = tmp_path / "nope.toml"
    monkeypatch.setenv("NIWA_CONFIG_PATH", str(missing))
    monkeypatch.delenv("NIWA_CONFIG", raising=False)

    settings = load_settings()

    assert settings.config_source is None
    assert settings.claude_cli is None
    assert settings.claude_timeout_s == 1800
    assert settings.executor_poll_interval_s == 5
    assert settings.bind_host == "127.0.0.1"
    assert settings.bind_port == 8000
