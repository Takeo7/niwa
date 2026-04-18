"""Tests for PR final 4 — isolated HOME for claude_code subprocess
(Bug 33 fix).

The real Claude CLI 2.1.97 prefers ``$HOME/.claude/.credentials.json``
over the ``CLAUDE_CODE_OAUTH_TOKEN`` env var. If the host's file is
stale, the CLI silently exits 1 or returns 401 — even with a valid
token in env.

The fix: when the backend is ``claude_code`` and the operator has
set ``svc.llm.anthropic.setup_token`` (surfaced in executor as
``LLM_SETUP_TOKEN``), point the subprocess HOME at a fresh empty
tmp dir. With no credentials.json there, the CLI falls back to the
env var cleanly. The host's real ``/home/niwa/.claude/`` is never
touched.

Contract pineado:

  * slug=claude_code + setup_token set → HOME in extra_env, apuntando
    a un dir recién creado con prefix ``niwa-claude-home-``.
  * slug=claude_code + setup_token vacío → no HOME override (flow
    legacy sigue funcionando con whatever el user tenga).
  * slug=codex → no HOME override aunque haya setup_token.
  * El dir tmp empieza vacío (sin .claude/credentials.json falso).
  * El cleanup list del wrapper incluye ese HOME cuando procede.

Run: pytest tests/test_pr_final4_claude_isolated_home.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
BIN_DIR = os.path.join(ROOT_DIR, "bin")
for p in (BACKEND_DIR, BIN_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def executor(tmp_path, monkeypatch):
    """Load bin/task-executor.py as a module. The executor refuses to
    start without a NIWA_HOME, so we seed a minimal one."""
    niwa_home = tmp_path / "niwa-home"
    (niwa_home / "secrets").mkdir(parents=True)
    (niwa_home / "secrets" / "mcp.env").write_text(
        'NIWA_DB_PATH=/tmp/nope.sqlite3\n'
        'svc.llm.anthropic.setup_token=sk-ant-oat01-ZZZZZ\n'
    )
    (niwa_home / "data").mkdir()
    monkeypatch.setenv("NIWA_HOME", str(niwa_home))

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "task_executor_pr_final4", os.path.join(BIN_DIR, "task-executor.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Happy path: claude_code with setup token → HOME tmp ─────────────


def test_claude_code_with_setup_token_gets_isolated_home(executor, monkeypatch):
    mod = executor
    # Force the token globals — _prepare_backend_env reads module
    # globals, not the env directly.
    monkeypatch.setattr(mod, "LLM_SETUP_TOKEN", "sk-ant-oat01-VALID")
    monkeypatch.setattr(mod, "LLM_API_KEY", None)
    env = mod._prepare_backend_env({"slug": "claude_code"})
    assert "HOME" in env, env
    home = Path(env["HOME"])
    assert home.is_dir()
    assert home.name.startswith("niwa-claude-home-")
    # Empty — no leftover credentials.json from another run.
    assert list(home.iterdir()) == []
    # The env var is also there for completeness (belt + braces).
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-VALID"


# ── Without setup token: no HOME override ───────────────────────────


def test_claude_code_without_setup_token_no_home_override(executor, monkeypatch):
    """Si el operador no guardó setup-token, no tiene sentido crear
    un HOME tmp vacío — el CLI dependerá de lo que el user haya
    configurado a mano."""
    mod = executor
    monkeypatch.setattr(mod, "LLM_SETUP_TOKEN", None)
    monkeypatch.setattr(mod, "LLM_API_KEY", None)
    env = mod._prepare_backend_env({"slug": "claude_code"})
    assert "HOME" not in env, env


def test_claude_code_with_api_key_only_no_home_override(executor, monkeypatch):
    """Con API key pero sin setup-token tampoco hace falta el HOME
    aislado — la API key no pasa por el credentials.json flow."""
    mod = executor
    monkeypatch.setattr(mod, "LLM_SETUP_TOKEN", None)
    monkeypatch.setattr(mod, "LLM_API_KEY", "sk-ant-api-XXXX")
    env = mod._prepare_backend_env({"slug": "claude_code"})
    assert env.get("ANTHROPIC_API_KEY") == "sk-ant-api-XXXX"
    assert "HOME" not in env


# ── Codex: no HOME override ─────────────────────────────────────────


def test_codex_does_not_get_claude_home_override(executor, monkeypatch):
    """Codex tiene su propio flujo (CODEX_HOME). El HOME aislado es
    exclusivo de Claude."""
    mod = executor
    monkeypatch.setattr(mod, "_get_openai_oauth_token", lambda: "oai-tok")
    monkeypatch.setattr(mod, "_get_openai_refresh_token", lambda: "oai-refresh")
    env = mod._prepare_backend_env({"slug": "codex"})
    # Codex has CODEX_HOME (its own thing), but HOME should NOT be
    # one of our claude tmp dirs.
    if "HOME" in env:
        assert not Path(env["HOME"]).name.startswith("niwa-claude-home-")


# ── Cleanup mechanism covers the Claude HOME ────────────────────────


def test_claude_home_path_matches_cleanup_pattern(executor, monkeypatch):
    """Pin del contrato: el wrapper's finally detecta el HOME de
    Claude por el prefijo del nombre del dir. Si cambiamos el
    prefijo en un lado y olvidamos el otro, el tmp dir leakaría.
    """
    mod = executor
    monkeypatch.setattr(mod, "LLM_SETUP_TOKEN", "sk-ant-oat01-VALID")
    monkeypatch.setattr(mod, "LLM_API_KEY", None)
    env = mod._prepare_backend_env({"slug": "claude_code"})
    home_basename = Path(env["HOME"]).name
    # Source of truth: the check in _execute_task_v02_body.
    src = Path(ROOT_DIR, "bin", "task-executor.py").read_text()
    assert 'Path(extra_env["HOME"]).name.startswith("niwa-claude-home-")' in src, \
        "Cleanup check string changed — update the test AND the producer together"
    assert home_basename.startswith("niwa-claude-home-")


# ── Multiple invocations create distinct tmp dirs ───────────────────


def test_each_call_creates_a_distinct_tmp_home(executor, monkeypatch):
    """Dos runs consecutivos no deben compartir el mismo HOME — eso
    generaría race conditions si ambos corren concurrentes."""
    mod = executor
    monkeypatch.setattr(mod, "LLM_SETUP_TOKEN", "sk-ant-oat01-VALID")
    monkeypatch.setattr(mod, "LLM_API_KEY", None)
    env1 = mod._prepare_backend_env({"slug": "claude_code"})
    env2 = mod._prepare_backend_env({"slug": "claude_code"})
    assert env1["HOME"] != env2["HOME"]
