"""Tests for the compose volume mount order-of-operations (PR-32, Bug 31).

Regression guard: on a root install, ``setup.py`` starts the Docker
stack (``docker compose up -d``) in step 14c with the compose file
pointing at ``cfg.niwa_home / "data"`` (e.g. ``/root/.niwa/data``).
Later, in ``_install_systemd_unit``, it creates ``/opt/<instance>/data``
and updates the compose to mount from there. But the app container
is already running with the OLD mount — it writes to
``/root/.niwa/data/niwa.sqlite3`` while the executor reads from
``/opt/<instance>/data/niwa.sqlite3``. Two divergent DBs.

The fix: after updating the compose volume, run
``docker compose up -d --no-deps app`` to recreate just the app
container with the new mount. These tests pin that the restart
is present in the code.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestComposeVolumeRestartPresent:
    """Pin that setup.py restarts the app container after updating
    the compose volume mount from cfg.niwa_home to shared_dir."""

    def _systemd_unit_body(self) -> str:
        src = (REPO_ROOT / "setup.py").read_text()
        start = src.index("def _install_systemd_unit(")
        tail = src[start:]
        end = re.search(r"\n(?=def [a-zA-Z_])", tail)
        return tail[: end.start() + 1] if end else tail

    def test_compose_up_after_volume_update(self):
        """After ``compose_path.write_text(content)`` (the volume
        update), there must be a ``docker compose up`` call to
        recreate the app container with the new mount."""
        body = self._systemd_unit_body()

        # The volume update writes the compose file.
        write_idx = body.index("compose_path.write_text(content)")

        # After that, there must be a docker compose up.
        after_write = body[write_idx:]
        assert "docker" in after_write and "compose" in after_write, (
            "after updating the compose volume mount, setup.py must "
            "run 'docker compose up -d' to recreate the app container "
            "with the new mount. Without this, the app writes to the "
            "old DB while the executor reads from the new one (Bug 31)."
        )

    def test_restart_targets_app_only(self):
        """The restart must target only the app container
        (``--no-deps app``), not the whole stack — gateways and
        caddy don't need a restart for a volume change."""
        body = self._systemd_unit_body()
        assert '"--no-deps", "app"' in body or "'--no-deps', 'app'" in body, (
            "compose restart after volume update must use "
            "'--no-deps app' to recreate only the app container. "
            "Restarting the whole stack is unnecessary and adds "
            "downtime to gateways/caddy."
        )

    def test_restart_happens_inside_volume_update_branch(self):
        """The restart must be inside the ``if old_data_dir in
        content:`` branch — if the volume was already correct
        (reinstall without path change), no restart is needed."""
        body = self._systemd_unit_body()

        # Find the branch that does the replace.
        branch_match = re.search(
            r'if old_data_dir in content:.*?(?=\n {8}\w|\n {8}#(?! ))',
            body,
            flags=re.DOTALL,
        )
        assert branch_match, (
            "could not locate the 'if old_data_dir in content:' "
            "branch in _install_systemd_unit"
        )
        branch_body = branch_match.group(0)
        assert "compose" in branch_body and "up" in branch_body, (
            "the docker compose restart must be INSIDE the "
            "'if old_data_dir in content:' branch, not outside — "
            "a reinstall that doesn't change the volume path "
            "should skip the restart"
        )
