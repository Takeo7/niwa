"""Tests for PR-A2 — installer Step 0 offers to install Docker.

``_offer_docker_install(non_interactive)`` encapsulates the prompt,
the platform-specific install command, and the re-detection.

Run with:
    pytest tests/test_pr_a2_docker_step0.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import setup  # noqa: E402


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _no_prompt(*_args, **_kw):
    raise AssertionError("prompt_bool must not be called on this path")


def _no_subprocess(*_args, **_kw):
    raise AssertionError("subprocess.run must not be called on this path")


class TestOfferDockerInstall:
    def test_non_interactive_never_prompts_nor_runs(self, monkeypatch):
        """--yes sin --install-docker: no se promptea ni se ejecuta nada."""
        monkeypatch.setattr(setup, "_platform_key", lambda: "linux")
        monkeypatch.setattr(setup, "prompt_bool", _no_prompt)
        monkeypatch.setattr(setup.subprocess, "run", _no_subprocess)
        assert setup._offer_docker_install(non_interactive=True) is None

    def test_user_declines_returns_none(self, monkeypatch):
        monkeypatch.setattr(setup, "_platform_key", lambda: "linux")
        monkeypatch.setattr(setup, "prompt_bool", lambda _q, default=False: False)
        monkeypatch.setattr(setup.subprocess, "run", _no_subprocess)
        assert setup._offer_docker_install(non_interactive=False) is None

    def test_linux_accept_and_success(self, monkeypatch):
        monkeypatch.setattr(setup, "_platform_key", lambda: "linux")
        monkeypatch.setattr(setup, "prompt_bool", lambda _q, default=False: True)

        calls: list = []

        def fake_run(cmd, **_kw):
            calls.append(cmd)
            return _FakeCompleted(returncode=0)

        monkeypatch.setattr(setup.subprocess, "run", fake_run)
        monkeypatch.setattr(
            setup, "detect_docker",
            lambda: {"available": True, "version": "Docker 27.0", "runtime": "docker"},
        )
        result = setup._offer_docker_install(non_interactive=False)
        assert result is not None
        assert result["available"] is True
        # The Linux command must invoke get.docker.com via shell.
        flat = " ".join(" ".join(c) if isinstance(c, (list, tuple)) else str(c) for c in calls)
        assert "get.docker.com" in flat

    def test_linux_accept_but_subprocess_fails(self, monkeypatch):
        monkeypatch.setattr(setup, "_platform_key", lambda: "linux")
        monkeypatch.setattr(setup, "prompt_bool", lambda _q, default=False: True)
        monkeypatch.setattr(
            setup.subprocess, "run",
            lambda *_a, **_kw: _FakeCompleted(returncode=1, stderr="need sudo"),
        )
        # Even if detect_docker is never reached, stub it defensively so a
        # bug in the helper can't reach the real binary.
        monkeypatch.setattr(setup, "detect_docker", lambda: {"available": False})
        assert setup._offer_docker_install(non_interactive=False) is None

    def test_linux_accept_but_still_not_detected(self, monkeypatch):
        """subprocess rc==0 pero `docker` sigue sin estar en PATH."""
        monkeypatch.setattr(setup, "_platform_key", lambda: "linux")
        monkeypatch.setattr(setup, "prompt_bool", lambda _q, default=False: True)
        monkeypatch.setattr(
            setup.subprocess, "run",
            lambda *_a, **_kw: _FakeCompleted(returncode=0),
        )
        monkeypatch.setattr(setup, "detect_docker", lambda: {"available": False})
        assert setup._offer_docker_install(non_interactive=False) is None

    def test_macos_with_brew_accept(self, monkeypatch):
        monkeypatch.setattr(setup, "_platform_key", lambda: "macos")
        monkeypatch.setattr(setup, "which",
                            lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None)
        monkeypatch.setattr(setup, "prompt_bool", lambda _q, default=False: True)

        calls: list = []

        def fake_run(cmd, **_kw):
            calls.append(cmd)
            return _FakeCompleted(returncode=0)

        monkeypatch.setattr(setup.subprocess, "run", fake_run)
        monkeypatch.setattr(
            setup, "detect_docker",
            lambda: {"available": True, "version": "Docker 27.0",
                     "runtime": "Docker Desktop"},
        )
        result = setup._offer_docker_install(non_interactive=False)
        assert result is not None
        assert result["available"] is True
        flat = " ".join(" ".join(c) if isinstance(c, (list, tuple)) else str(c) for c in calls)
        assert "brew" in flat and "docker" in flat

    def test_macos_without_brew_no_prompt(self, monkeypatch):
        monkeypatch.setattr(setup, "_platform_key", lambda: "macos")
        monkeypatch.setattr(setup, "which", lambda _name: None)
        monkeypatch.setattr(setup, "prompt_bool", _no_prompt)
        monkeypatch.setattr(setup.subprocess, "run", _no_subprocess)
        assert setup._offer_docker_install(non_interactive=False) is None

    def test_other_platform_no_prompt(self, monkeypatch):
        monkeypatch.setattr(setup, "_platform_key", lambda: "other")
        monkeypatch.setattr(setup, "prompt_bool", _no_prompt)
        monkeypatch.setattr(setup.subprocess, "run", _no_subprocess)
        assert setup._offer_docker_install(non_interactive=False) is None


class TestBuildQuickConfigOffersDocker:
    """build_quick_config must call _offer_docker_install when docker is
    missing, and must pass non_interactive=True when args.yes is set."""

    def test_missing_docker_with_yes_exits(self, tmp_path, monkeypatch):
        monkeypatch.setattr(setup, "detect_docker", lambda: {"available": False})
        monkeypatch.setattr(setup, "detect_port_free", lambda _p: True)
        monkeypatch.setattr(setup, "which", lambda _: None)

        captured = {}

        def fake_offer(non_interactive: bool = False):
            captured["non_interactive"] = non_interactive
            return None  # simulate decline / unsupported

        monkeypatch.setattr(setup, "_offer_docker_install", fake_offer)

        class _Args:
            mode = "core"
            yes = True
            workspace = None
            public_url = None
            admin_user = None
            admin_password = None
            instance = None
            dir = str(tmp_path / "niwa")
            rotate_secrets = False

        with pytest.raises(SystemExit):
            setup.build_quick_config(_Args())
        assert captured["non_interactive"] is True

    def test_missing_docker_but_offer_succeeds_continues(self, tmp_path, monkeypatch):
        """Si _offer_docker_install devuelve un dict available=True, el
        wizard continúa."""
        # detect_docker reports missing on the first call (pre-offer) and
        # never again — build_quick_config uses the value returned by
        # _offer_docker_install.
        monkeypatch.setattr(setup, "detect_docker", lambda: {"available": False})
        monkeypatch.setattr(setup, "detect_socket_path", lambda: "/var/run/docker.sock")
        monkeypatch.setattr(setup, "detect_port_free", lambda _p: True)
        monkeypatch.setattr(setup, "which", lambda _: None)
        monkeypatch.setattr(
            setup, "_offer_docker_install",
            lambda non_interactive=False: {
                "available": True, "version": "Docker 27.0", "runtime": "docker",
            },
        )

        class _Args:
            mode = "core"
            yes = False
            workspace = None
            public_url = None
            admin_user = None
            admin_password = None
            instance = None
            dir = str(tmp_path / "niwa")
            rotate_secrets = False

        cfg = setup.build_quick_config(_Args())
        assert cfg.detected["docker_socket"] == "/var/run/docker.sock"
