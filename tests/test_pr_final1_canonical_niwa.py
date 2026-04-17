"""Tests for PR final 1 — canonical ``niwa`` command on PATH + /api/version
exposes update_command / restore_command.

Contract pineado:

  * ``_install_niwa_wrapper`` crea symlink en /usr/local/bin si es
    sudo, en ~/.local/bin si no. Retorna "niwa" si el parent está en
    PATH; path absoluto al script del repo si nada del PATH es
    escribible.
  * mcp.env gana ``NIWA_UPDATE_COMMAND`` y ``NIWA_RESTORE_COMMAND``
    con el valor real.
  * /api/version expone ``update_command`` + ``restore_command``.
  * /api/system/update devuelve el ``update_command`` real (no
    hardcoded "niwa update") en la action intent.

Run: pytest tests/test_pr_final1_canonical_niwa.py -v
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
SETUP_PY = Path(ROOT_DIR, "setup.py")


@pytest.fixture
def setup_module(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "niwa_setup_cli", str(SETUP_PY),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_cfg(mod, niwa_home: Path):
    cfg = mod.WizardConfig()
    cfg.niwa_home = niwa_home
    return cfg


# ── _install_niwa_wrapper ────────────────────────────────────────────


def test_wrapper_symlinks_when_path_dir_writable(setup_module, tmp_path, monkeypatch):
    """Si el parent del target está en PATH, el wrapper devuelve
    ``niwa``. Para no depender de /usr/local/bin, redirigimos los
    candidatos a un tmp dir y lo metemos en PATH.
    """
    mod = setup_module
    # The candidate for non-root is Path.home()/".local/bin".
    # Redirect Path.home() to tmp_path and put tmp_path/.local/bin on
    # PATH so the wrapper finds a writable, PATH-visible location.
    monkeypatch.setattr(mod.Path, "home",
                        classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(mod.os, "geteuid", lambda: 1000)
    local_bin = tmp_path / ".local" / "bin"
    local_bin.mkdir(parents=True)
    monkeypatch.setenv("PATH", f"{local_bin}:{os.environ.get('PATH', '')}")

    cfg = _fake_cfg(mod, tmp_path / ".niwa")
    cmd, origin = mod._install_niwa_wrapper(cfg)
    assert cmd == "niwa", origin
    link = local_bin / "niwa"
    assert link.is_symlink()
    assert "symlink" in origin


def test_wrapper_falls_back_to_absolute_when_no_writable_path(setup_module, tmp_path, monkeypatch):
    """Si ninguno de los dirs candidatos está en PATH, devuelve el
    path absoluto al script del repo."""
    mod = setup_module
    # PATH sin ningún dir candidato.
    monkeypatch.setenv("PATH", "/this/path/does/not/matter")
    monkeypatch.setattr(mod.Path, "home",
                        classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(mod.os, "geteuid", lambda: 1000)
    (tmp_path / ".local" / "bin").mkdir(parents=True)
    cfg = _fake_cfg(mod, tmp_path / ".niwa")
    cmd, origin = mod._install_niwa_wrapper(cfg)
    # Should be the absolute path to <repo>/niwa, not "niwa".
    assert cmd != "niwa"
    assert cmd and Path(cmd).is_absolute()
    assert cmd.endswith("/niwa")
    assert "fallback" in origin


# ── /api/version exposes update_command ──────────────────────────────


def _free_port():
    import socket as _s
    with _s.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
def app_server(tmp_path, monkeypatch):
    db_path = str(tmp_path / "niwa.sqlite3")
    niwa_home = tmp_path / "home"
    niwa_home.mkdir()
    monkeypatch.setenv("NIWA_DB_PATH", db_path)
    monkeypatch.setenv("NIWA_APP_AUTH_REQUIRED", "0")
    monkeypatch.setenv("NIWA_APP_HOST", "127.0.0.1")
    monkeypatch.setenv("NIWA_HOME", str(niwa_home))

    schema_sql = Path(ROOT_DIR, "niwa-app", "db", "schema.sql").read_text()
    c = sqlite3.connect(db_path)
    c.executescript(schema_sql)
    c.commit()
    c.close()
    monkeypatch.delitem(sys.modules, "app", raising=False)
    import app
    app.DB_PATH = Path(db_path)
    port = _free_port()
    app.HOST = "127.0.0.1"
    app.PORT = port
    app.NIWA_APP_AUTH_REQUIRED = False
    app.init_db()

    srv = ThreadingHTTPServer(("127.0.0.1", port), app.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(30):
        try:
            urlopen(f"{base}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    yield {"base": base}
    srv.shutdown()
    srv.server_close()


def _get_json(base, path, *, method="GET", body=None):
    h = {"Content-Type": "application/json"} if body is not None else {}
    req = Request(f"{base}{path}", headers=h, method=method,
                  data=json.dumps(body).encode() if body is not None else None)
    with urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read())


def test_version_exposes_update_and_restore_commands_default(app_server):
    """Sin NIWA_UPDATE_COMMAND en env, /api/version devuelve
    fallbacks razonables ("niwa update" / "niwa restore --from=").
    """
    _, data = _get_json(app_server["base"], "/api/version")
    assert data["update_command"] == "niwa update"
    assert data["restore_command"] == "niwa restore --from="


def test_version_honors_NIWA_UPDATE_COMMAND_env(app_server, monkeypatch):
    """Si el installer escribió un path absoluto en mcp.env (y la
    app lo carga como env var), /api/version lo refleja."""
    monkeypatch.setenv("NIWA_UPDATE_COMMAND", "/root/niwa/niwa update")
    monkeypatch.setenv(
        "NIWA_RESTORE_COMMAND", "/root/niwa/niwa restore --from=",
    )
    _, data = _get_json(app_server["base"], "/api/version")
    assert data["update_command"] == "/root/niwa/niwa update"
    assert data["restore_command"] == "/root/niwa/niwa restore --from="


def test_system_update_intent_uses_real_command(app_server, monkeypatch):
    """La action intent del endpoint /api/system/update debe usar el
    update_command real (no hardcoded "niwa update") para que el
    operador pueda copy-paste algo que siempre funciona."""
    monkeypatch.setenv("NIWA_UPDATE_COMMAND", "/repo/niwa update")
    status, out = _get_json(
        app_server["base"], "/api/system/update", method="POST", body={},
    )
    assert status == 202
    assert out["command"] == "/repo/niwa update"
    assert "/repo/niwa update" in out["message"]


# ── Docs alignment smoke ────────────────────────────────────────────


def test_docs_do_not_advertise_bare_python3_setup_py_update():
    """Pin contra regresión del runbook: tras la alineación de
    docs/PR-final-1, ninguna de las tres docs canónicas debe mostrar
    ``python3 setup.py update`` como comando operativo (sigue siendo
    un fallback técnico, no lo que documentamos)."""
    for rel in ("README.md", "INSTALL.md", "docs/RELEASE-RUNBOOK.md"):
        body = Path(ROOT_DIR, rel).read_text()
        # Permitimos python3 setup.py en contextos que no sean el
        # flujo de update (p.ej. install interactivo es inofensivo),
        # pero sí pineamos que ``python3 setup.py update`` no está.
        assert "python3 setup.py update" not in body, (
            f"{rel} still advertises `python3 setup.py update`"
        )
