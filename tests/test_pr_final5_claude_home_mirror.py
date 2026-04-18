"""Tests for PR final 5 — Claude HOME mirror (symlink farm).

PR final 4 arreglaba Bug 33 con un HOME tmp VACÍO. GPT señaló (P1)
que esa solución rompía dos contratos:

  1. ``--resume`` de Claude — las sesiones viven en
     ``$HOME/.claude/projects/...``. HOME vacío = no resume.
  2. MCP user-scope + settings — Niwa registra sus servidores con
     ``claude mcp add --scope user`` (en ``~/.claude.json``) y puede
     tener ``settings.json`` en ``~/.claude/``. HOME vacío =
     tools como ``project_create`` desaparecen.

El fix de PR final 5 es un HOME tmp con symlink farm: refleja
entry-by-entry el ``~/.claude/`` real EXCEPTO ``.credentials.json``,
y añade un symlink a ``~/.claude.json``. El CLI ve:

  - projects/ → real (resume funciona).
  - settings.json → real.
  - ~/.claude.json → real (MCP user-scope).
  - .credentials.json → ABSENT (trick que fuerza env var).

Tests pinean:

  * ``projects/`` del home real se ve desde el tmp_home (resume OK).
  * ``settings.json`` y otros files normales también.
  * ``.claude.json`` sibling symlinked.
  * ``.credentials.json`` NO aparece en tmp_home (aislado).
  * Sin ``~/.claude/`` real → tmp_home tiene ``.claude/`` vacío.
  * Codex no toca HOME.
  * Llamadas sucesivas → tmp dirs distintos.

Run: pytest tests/test_pr_final5_claude_home_mirror.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(ROOT_DIR, "bin")
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
for p in (BIN_DIR, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def executor(tmp_path, monkeypatch):
    """Load the executor + point Path.home() at a controllable fake
    home so we can plant realistic ``~/.claude/`` state."""
    niwa_home = tmp_path / "niwa-home"
    (niwa_home / "secrets").mkdir(parents=True)
    (niwa_home / "secrets" / "mcp.env").write_text(
        'NIWA_DB_PATH=/tmp/nope.sqlite3\n'
    )
    (niwa_home / "data").mkdir()
    monkeypatch.setenv("NIWA_HOME", str(niwa_home))

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "task_executor_pr_final5", os.path.join(BIN_DIR, "task-executor.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Plant a realistic fake user home at tmp_path/user_home with the
    # pieces Niwa + operators actually put there.
    fake_user_home = tmp_path / "user_home"
    (fake_user_home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(mod.Path, "home",
                        classmethod(lambda cls: fake_user_home))
    return {"mod": mod, "user_home": fake_user_home}


# ── Mirror preserves projects/ (resume) ────────────────────────────


def test_mirror_preserves_projects_dir_for_resume(executor):
    """Guard crítico: si un run previo dejó una sesión en
    ``~/.claude/projects/cwd/<uuid>.jsonl``, el subprocess con HOME
    aislado debe poder leerla (si Claude pasa ``--resume <uuid>``)
    y escribir actualizaciones al FICHERO REAL, no a la copia."""
    mod = executor["mod"]
    user_home = executor["user_home"]
    # Plant a pre-existing session.
    projects = user_home / ".claude" / "projects" / "-home-user-niwa"
    projects.mkdir(parents=True)
    session_file = projects / "abc-session.jsonl"
    session_file.write_text('{"role":"user","content":"hola"}\n')

    mod.LLM_SETUP_TOKEN = "sk-ant-oat01-VALID"
    mod.LLM_API_KEY = None
    env = mod._prepare_backend_env({"slug": "claude_code"})
    home = Path(env["HOME"])
    assert (home / ".claude" / "projects").exists()
    # Symlink → real dir → same file visible.
    mirrored_session = home / ".claude" / "projects" / "-home-user-niwa" / "abc-session.jsonl"
    assert mirrored_session.exists()
    assert mirrored_session.read_text() == '{"role":"user","content":"hola"}\n'
    # Write-through contract: appending via the mirror path lands in
    # the REAL file. Simulamos lo que Claude haría al resumir +
    # continuar la conversación.
    with mirrored_session.open("a") as f:
        f.write('{"role":"assistant","content":"hola tu"}\n')
    assert session_file.read_text().count("\n") == 2


# ── Mirror preserves settings.json and other files ──────────────────


def test_mirror_preserves_settings_json(executor):
    mod = executor["mod"]
    user_home = executor["user_home"]
    settings = user_home / ".claude" / "settings.json"
    settings.write_text('{"permissions":{"allow":["*"]}}')

    mod.LLM_SETUP_TOKEN = "sk-ant-oat01-VALID"
    mod.LLM_API_KEY = None
    env = mod._prepare_backend_env({"slug": "claude_code"})
    mirrored = Path(env["HOME"]) / ".claude" / "settings.json"
    assert mirrored.exists()
    assert mirrored.read_text() == '{"permissions":{"allow":["*"]}}'


def test_mirror_preserves_arbitrary_files_in_claude_dir(executor):
    """Cualquier entrada que Claude/Niwa ponga en ``~/.claude/`` debe
    quedar visible tras el mirror. Defensa contra futuras adiciones
    (mcp_servers.json, cache, etc.)."""
    mod = executor["mod"]
    user_home = executor["user_home"]
    (user_home / ".claude" / "mcp_servers.json").write_text("{}")
    (user_home / ".claude" / "commands").mkdir()
    (user_home / ".claude" / "commands" / "foo.md").write_text("# foo")

    mod.LLM_SETUP_TOKEN = "sk-ant-oat01-VALID"
    mod.LLM_API_KEY = None
    env = mod._prepare_backend_env({"slug": "claude_code"})
    h = Path(env["HOME"]) / ".claude"
    assert (h / "mcp_servers.json").exists()
    assert (h / "commands" / "foo.md").read_text() == "# foo"


# ── Mirror preserves ~/.claude.json (sibling) — MCP user-scope ─────


def test_mirror_preserves_home_claude_json(executor):
    """Niwa registra sus MCP con ``claude mcp add --scope user``, que
    persiste en ``~/.claude.json``. Si ese fichero no es visible al
    subprocess, ``project_create`` y otras tools desaparecen."""
    mod = executor["mod"]
    user_home = executor["user_home"]
    claude_json = user_home / ".claude.json"
    claude_json.write_text('{"mcpServers":{"niwa-tasks":{}}}')

    mod.LLM_SETUP_TOKEN = "sk-ant-oat01-VALID"
    mod.LLM_API_KEY = None
    env = mod._prepare_backend_env({"slug": "claude_code"})
    mirrored = Path(env["HOME"]) / ".claude.json"
    assert mirrored.exists()
    assert mirrored.read_text() == '{"mcpServers":{"niwa-tasks":{}}}'


# ── Mirror hides .credentials.json (the whole point) ────────────────


def test_mirror_hides_credentials_json(executor):
    """EL trick del fix: el mirror omite ``credentials.json``, así
    que el CLI cae al env var. Sin este assert, un refactor bien
    intencionado podría symlinkar todo y reintroducir Bug 33."""
    mod = executor["mod"]
    user_home = executor["user_home"]
    creds = user_home / ".claude" / ".credentials.json"
    creds.write_text('{"claudeAiOauth":{"accessToken":"expired"}}')

    mod.LLM_SETUP_TOKEN = "sk-ant-oat01-VALID"
    mod.LLM_API_KEY = None
    env = mod._prepare_backend_env({"slug": "claude_code"})
    tmp_home = Path(env["HOME"])
    # El trick del aislamiento: NO existe credentials.json en el
    # tmp_home. El CLI buscará, no encontrará, y usará el env var.
    tmp_creds = tmp_home / ".claude" / ".credentials.json"
    assert not tmp_creds.exists()
    assert not tmp_creds.is_symlink()
    # El fichero del host sigue intacto — NUNCA lo tocamos.
    assert creds.exists()
    assert creds.read_text() == '{"claudeAiOauth":{"accessToken":"expired"}}'


# ── Edge cases ──────────────────────────────────────────────────────


def test_mirror_with_no_real_claude_dir_still_sets_home(executor, tmp_path):
    """Fresh install: el user niwa nunca ejecutó ``claude setup-token``
    ni Niwa instaló un ``.claude/``. El mirror debe dar un HOME tmp
    válido (con ``.claude/`` vacío, sin credentials.json) — comportamiento
    idéntico al PR final 4 original para installs limpias."""
    mod = executor["mod"]
    user_home = tmp_path / "empty_user_home"
    user_home.mkdir()
    # Redirect Path.home to an EMPTY home.
    import types
    mod.Path.home = classmethod(lambda cls: user_home)

    mod.LLM_SETUP_TOKEN = "sk-ant-oat01-VALID"
    mod.LLM_API_KEY = None
    env = mod._prepare_backend_env({"slug": "claude_code"})
    h = Path(env["HOME"])
    assert (h / ".claude").is_dir()
    assert list((h / ".claude").iterdir()) == []  # empty
    assert not (h / ".claude" / ".credentials.json").exists()
    assert not (h / ".claude.json").exists()


def test_mirror_without_setup_token_does_not_create_home(executor):
    """Sin setup_token no hay aislamiento — el flow legacy gestiona
    el credentials.json real (el operador pone env var u otro)."""
    mod = executor["mod"]
    mod.LLM_SETUP_TOKEN = None
    mod.LLM_API_KEY = None
    env = mod._prepare_backend_env({"slug": "claude_code"})
    assert "HOME" not in env


def test_codex_unaffected(executor):
    """El mirror solo aplica a claude_code. Codex tiene su propio
    flujo (CODEX_HOME) y no debe recibir un HOME de Niwa."""
    mod = executor["mod"]
    mod._get_openai_oauth_token = lambda: "oai-tok"
    mod._get_openai_refresh_token = lambda: "oai-refresh"
    env = mod._prepare_backend_env({"slug": "codex"})
    if "HOME" in env:
        assert not Path(env["HOME"]).name.startswith("niwa-claude-home-")


def test_successive_calls_create_distinct_tmp_dirs(executor):
    """Dos runs sucesivos del adapter Claude deben recibir tmp dirs
    diferentes — evita race conditions si coinciden en paralelo."""
    mod = executor["mod"]
    mod.LLM_SETUP_TOKEN = "sk-ant-oat01-VALID"
    mod.LLM_API_KEY = None
    env1 = mod._prepare_backend_env({"slug": "claude_code"})
    env2 = mod._prepare_backend_env({"slug": "claude_code"})
    assert env1["HOME"] != env2["HOME"]
