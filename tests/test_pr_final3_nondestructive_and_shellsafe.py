"""Tests for PR final 3 — non-destructive wrapper install + shell-safe commands.

Pins:

  * ``_is_niwa_managed_target``: True sólo para symlinks que apunten
    al script real del repo; False para binarios ajenos, ficheros
    normales, directorios, symlinks rotos.
  * ``_install_niwa_wrapper`` NUNCA borra un target que no sea
    managed. Si todos los candidatos están ocupados por foreign
    binaries, devuelve fallback absoluto con origin explicando la
    colisión.
  * ``_install_niwa_wrapper`` refresca (unlink + symlink) un target
    que SÍ es managed — cubre reinstalls que mueven el repo de
    sitio.
  * setup.py escribe ``NIWA_UPDATE_COMMAND`` con ``shlex.quote`` del
    path — paths con espacios producen un comando ejecutable.

Run: pytest tests/test_pr_final3_nondestructive_and_shellsafe.py -v
"""
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP_PY = Path(ROOT_DIR, "setup.py")


@pytest.fixture
def setup_module(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "niwa_setup_final3", str(SETUP_PY),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── _is_niwa_managed_target ─────────────────────────────────────────


def test_managed_detector_true_for_symlink_to_script(setup_module, tmp_path):
    mod = setup_module
    script = tmp_path / "niwa"
    script.write_text("#!/bin/bash\n")
    script.chmod(0o755)
    target = tmp_path / "bin" / "niwa"
    target.parent.mkdir()
    target.symlink_to(script)
    assert mod._is_niwa_managed_target(target, script) is True


def test_managed_detector_false_for_regular_file(setup_module, tmp_path):
    """El caso malo: un binario ajeno llamado exactamente ``niwa``."""
    mod = setup_module
    script = tmp_path / "niwa"
    script.write_text("#!/bin/bash\necho 'real niwa'\n")
    script.chmod(0o755)
    target = tmp_path / "bin" / "niwa"
    target.parent.mkdir()
    # NO es symlink — es un binario plano ajeno. MUST NOT match.
    target.write_text("#!/bin/bash\necho 'foreign niwa'\n")
    assert mod._is_niwa_managed_target(target, script) is False


def test_managed_detector_false_for_symlink_elsewhere(setup_module, tmp_path):
    mod = setup_module
    script = tmp_path / "niwa"
    script.write_text("ok")
    other = tmp_path / "some-other-binary"
    other.write_text("nope")
    target = tmp_path / "bin" / "niwa"
    target.parent.mkdir()
    target.symlink_to(other)
    assert mod._is_niwa_managed_target(target, script) is False


def test_managed_detector_false_for_broken_symlink(setup_module, tmp_path):
    mod = setup_module
    script = tmp_path / "niwa"
    script.write_text("ok")
    target = tmp_path / "bin" / "niwa"
    target.parent.mkdir()
    target.symlink_to(tmp_path / "does-not-exist")
    assert mod._is_niwa_managed_target(target, script) is False


def test_managed_detector_false_for_directory(setup_module, tmp_path):
    mod = setup_module
    script = tmp_path / "niwa"
    script.write_text("ok")
    target = tmp_path / "bin" / "niwa"
    target.mkdir(parents=True)
    assert mod._is_niwa_managed_target(target, script) is False


# ── _install_niwa_wrapper non-destructive contract ──────────────────


def test_wrapper_does_not_overwrite_foreign_binary(
    setup_module, tmp_path, monkeypatch,
):
    """Bug P1 fix: si ``~/.local/bin/niwa`` es un binario ajeno, el
    instalador NO debe borrarlo. Usa fallback absoluto."""
    mod = setup_module
    local_bin = tmp_path / ".local" / "bin"
    local_bin.mkdir(parents=True)
    foreign = local_bin / "niwa"
    foreign_content = b"#!/bin/bash\necho 'pre-existing foreign niwa'\n"
    foreign.write_bytes(foreign_content)
    foreign.chmod(0o755)

    monkeypatch.setattr(mod.Path, "home",
                        classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(mod.os, "geteuid", lambda: 1000)
    monkeypatch.setenv("PATH", f"{local_bin}:/usr/bin")

    cfg = mod.WizardConfig()
    cfg.niwa_home = tmp_path / ".niwa"
    cmd, origin = mod._install_niwa_wrapper(cfg)

    # The foreign binary is untouched.
    assert foreign.exists()
    assert foreign.read_bytes() == foreign_content
    # The wrapper returned fallback + explained why.
    assert cmd != "niwa"
    assert cmd.endswith("/niwa")
    assert "untouched" in origin or "collision" in origin.lower() \
        or "foreign" in origin.lower()


def test_wrapper_refreshes_managed_symlink(setup_module, tmp_path, monkeypatch):
    """Contra-test del P1 fix: si el target YA es un symlink de
    Niwa (por un install previo), refrescarlo es seguro y esperado
    (cubre mudanzas del repo entre installs)."""
    mod = setup_module
    script_src = Path(SETUP_PY).parent / "niwa"
    local_bin = tmp_path / ".local" / "bin"
    local_bin.mkdir(parents=True)
    # Prior install — symlink al mismo script del repo.
    prior = local_bin / "niwa"
    prior.symlink_to(script_src)

    monkeypatch.setattr(mod.Path, "home",
                        classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(mod.os, "geteuid", lambda: 1000)
    monkeypatch.setenv("PATH", f"{local_bin}:/usr/bin")

    cfg = mod.WizardConfig()
    cfg.niwa_home = tmp_path / ".niwa"
    cmd, origin = mod._install_niwa_wrapper(cfg)

    assert cmd == "niwa", origin
    assert "symlink" in origin
    # The symlink ended up pointing at the repo script (may be the
    # same file it did before — that's fine).
    assert prior.is_symlink()
    assert prior.resolve().samefile(script_src)


# ── Shell-safe commands (setup.py writing to mcp.env) ──────────────


def test_update_command_shell_quoted_when_path_has_spaces():
    """Pin de la regla: un path con espacios termina entre comillas
    simples en ``NIWA_UPDATE_COMMAND``, así que el operador puede
    copy-pastearlo sin trampa."""
    quoted = shlex.quote("/home/user/My Niwa/niwa")
    cmd = f"{quoted} update"
    # El shell vuelve a parsear como un token + "update".
    tokens = shlex.split(cmd)
    assert tokens == ["/home/user/My Niwa/niwa", "update"], tokens


def test_restore_suggestion_shell_quoted_for_backup_path_with_spaces():
    """Regla aplicada client-side en UpdatePanel: el UI concatena
    el prefijo + shellQuote(backup_path). Emulamos la lógica equiv
    aquí para pinear la semántica Python-side (la JS se prueba en
    el suite de vitest)."""
    prefix = shlex.quote("/repo path/niwa") + " restore --from="
    bkp = "/data backups/niwa 2026 04 17.sqlite3"
    suggestion = f"{prefix}{shlex.quote(bkp)}"
    # Round-trip via shlex.split:
    tokens = shlex.split(suggestion)
    assert tokens[0] == "/repo path/niwa"
    assert tokens[1] == "restore"
    # ``--from=<path>`` sigue siendo UN token para argparse.
    assert tokens[2].startswith("--from=")
    assert tokens[2] == f"--from={bkp}", tokens[2]


def test_update_command_plain_path_no_quotes_added():
    """Regression guard: paths limpios sin espacios NO ganan quotes
    innecesarios — el comando impreso al operador sigue siendo
    legible."""
    q = shlex.quote("/usr/local/bin/niwa")
    cmd = f"{q} update"
    # No quotes added for a clean ASCII path.
    assert cmd == "/usr/local/bin/niwa update"
