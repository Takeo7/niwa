"""Tests for ``_get_service_status('llm_anthropic')``.

Regression guard for the "indicador mentiroso" bug observed in System
→ Agentes: the service card showed "CONFIGURADO ✓" (green badge) when
only a Setup Token was set, but the conversational chat
(``assistant_turn``) requires an Anthropic API key — they are two
disjoint auth systems (subscription billing vs API billing) and the
Setup Token does NOT unlock the chat. The user sees green, opens the
chat, hits ``llm_not_configured``, loses time debugging.

These tests pin down the honest four-state matrix:

  | api_key | setup_token | expected status   |
  |---------|-------------|-------------------|
  | yes     | no          | configured        |
  | yes     | yes         | configured        |
  | no      | yes         | warning (new)     |
  | no      | no          | not_configured    |

The ``warning`` state makes the UI badge yellow with a message that
spells out the gap. The existing ``STATUS_BADGE`` map in
``frontend/src/features/system/components/ServiceCard.tsx`` already
renders a "warning" state as yellow with label "Aviso" — no frontend
changes needed.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "niwa-app" / "backend"
DB_DIR = REPO_ROOT / "niwa-app" / "db"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def tmp_db_app(monkeypatch):
    """Fresh sqlite DB with schema.sql + ``app`` module wired to it."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    try:
        with sqlite3.connect(path) as conn:
            conn.executescript((DB_DIR / "schema.sql").read_text())
            conn.commit()
        monkeypatch.setenv("NIWA_DB_PATH", path)
        monkeypatch.setenv("NIWA_APP_AUTH_REQUIRED", "0")
        # Fresh import so module-level constants pick up the env.
        for mod in ("app", "tasks_service"):
            sys.modules.pop(mod, None)
        import app  # noqa: E402
        yield app, path
    finally:
        os.unlink(path)


def _set(app_mod, key: str, value: str) -> None:
    app_mod.save_setting(key, value)


class TestLlmAnthropicStatus:
    """Matrix of (api_key, setup_token) → status."""

    def test_api_key_only_is_configured(self, tmp_db_app):
        app_mod, _ = tmp_db_app
        _set(app_mod, "svc.llm.anthropic.api_key", "sk-ant-test-real-api-key")

        result = app_mod._get_service_status("llm_anthropic")

        assert result["status"] == "configured"
        assert "api key" in result["message"].lower()

    def test_setup_token_only_is_warning_not_configured(self, tmp_db_app):
        """The bug: before the fix this returned ``configured`` and
        the chat then broke with ``llm_not_configured``."""
        app_mod, _ = tmp_db_app
        _set(app_mod, "svc.llm.anthropic.setup_token", "sk-ant-setup-xyz")
        _set(app_mod, "svc.llm.anthropic.auth_method", "setup_token")

        result = app_mod._get_service_status("llm_anthropic")

        assert result["status"] == "warning", (
            f"Setup Token alone must NOT claim fully configured, "
            f"got: {result}"
        )
        msg = result["message"].lower()
        assert "api key" in msg and "chat" in msg, (
            f"message must spell out the gap, got: {result['message']}"
        )

    def test_setup_token_only_legacy_key_is_also_warning(self, tmp_db_app):
        """Pre-PR-10 installs wrote ``int.llm_setup_token`` without the
        explicit ``svc.llm.anthropic.auth_method`` flag. Must still be
        flagged as partial."""
        app_mod, _ = tmp_db_app
        _set(app_mod, "int.llm_setup_token", "sk-ant-legacy-token")
        _set(app_mod, "int.llm_provider", "claude")

        result = app_mod._get_service_status("llm_anthropic")

        assert result["status"] == "warning"
        assert "chat" in result["message"].lower()

    def test_both_present_is_configured(self, tmp_db_app):
        """When both are set the user is fully covered (chat + CLI)."""
        app_mod, _ = tmp_db_app
        _set(app_mod, "svc.llm.anthropic.api_key", "sk-ant-real-key")
        _set(app_mod, "svc.llm.anthropic.setup_token", "sk-ant-setup-xyz")

        result = app_mod._get_service_status("llm_anthropic")

        assert result["status"] == "configured"

    def test_neither_present_is_not_configured(self, tmp_db_app):
        app_mod, _ = tmp_db_app

        result = app_mod._get_service_status("llm_anthropic")

        assert result["status"] == "not_configured"
