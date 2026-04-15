"""Tests for _execute_task_v02's state machine compliance (PR-29, Bug 23).

Regression guard for **Bug 23** (docs/BUGS-FOUND.md): when
``routing_service.decide()`` returned ``approval_required=True``,
``_execute_task_v02`` used to UPDATE ``tasks.status`` to
``'pendiente'`` directly. That violates the task state machine
(``en_progreso → pendiente`` is not in ``TASK_TRANSITIONS``), and
because the executor's poll loop claims any task in ``pendiente``,
the task would cycle back through the approval check forever:

    pendiente → [claim] → en_progreso → [approval required] →
    pendiente → [reclaim] → en_progreso → [still no approval] →
    pendiente → ... (loop until operator approves or cancels)

The fix transitions the task to ``waiting_input`` — the canonical
"needs human action before proceeding" state per ``docs/SPEC-v0.2.md``
§ PR-02. Approval resolution (separately) transitions the task back
to ``pendiente``, which the executor then picks up normally.

These tests exercise the actual code path in ``bin/task-executor.py``
via the stdlib-only harness already used by ``test_task_executor_*``
tests. The approval handler's side of the contract lives in a
separate test file / PR — here we only pin that the executor side
stops violating the state machine.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXECUTOR_PATH = REPO_ROOT / "bin" / "task-executor.py"
BACKEND_DIR = REPO_ROOT / "niwa-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _load_executor_module():
    """Import ``bin/task-executor.py`` as a module so we can call
    its internals from tests. It's not in a package, so we use
    ``importlib.util`` to load it explicitly.

    The module's top-level runs ``_BACKEND_DIR`` resolution and
    may ``sys.exit(2)`` if the backend dir is missing — in a repo
    checkout (where we run) the dir exists so this is a no-op."""
    spec = importlib.util.spec_from_file_location(
        "task_executor_under_test", str(EXECUTOR_PATH),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestStaticSourceInvariants:
    """Regex-only checks pinning the invariant in source. These
    catch the regression even if nobody runs the behaviour tests
    below — cheap insurance against copy-paste regressions."""

    def test_execute_task_v02_transitions_to_waiting_input_not_pendiente(self):
        src = EXECUTOR_PATH.read_text()
        # Find the approval_required branch inside _execute_task_v02.
        start = src.index("def _execute_task_v02(")
        tail = src[start:]
        # End at next top-level def.
        import re
        end = re.search(r"\ndef [a-zA-Z_]", tail)
        body = tail[: end.start()] if end else tail

        # The approval-required branch must set status to
        # 'waiting_input', not 'pendiente'. Being strict on the
        # exact strings to catch the regression unambiguously.
        assert "UPDATE tasks SET status = 'waiting_input'" in body, (
            "approval_required branch must UPDATE to 'waiting_input' "
            "(Bug 23 fix). The prior buggy code UPDATEd to 'pendiente' "
            "which violates state_machines.TASK_TRANSITIONS and causes "
            "a re-claim loop."
        )
        # And it must NOT still contain the old buggy UPDATE.
        assert "UPDATE tasks SET status = 'pendiente'" not in body, (
            "found UPDATE to 'pendiente' in _execute_task_v02 — "
            "Bug 23 regression. Use 'waiting_input' instead."
        )

    def test_execute_task_v02_asserts_transition_before_updating(self):
        """The UPDATE must be guarded by _assert_task_transition so
        a future refactor that accidentally enters this branch from
        an invalid prior state fails loud instead of silently
        writing bad state."""
        src = EXECUTOR_PATH.read_text()
        start = src.index("def _execute_task_v02(")
        tail = src[start:]
        import re
        end = re.search(r"\ndef [a-zA-Z_]", tail)
        body = tail[: end.start()] if end else tail

        assert "_assert_task_transition(" in body, (
            "_execute_task_v02 must call _assert_task_transition "
            "before updating task status, so state machine "
            "violations surface at write-time instead of silently "
            "corrupting the DB."
        )


class TestStateMachineCompliance:
    """Verify the canonical state machine accepts the transition we
    use (en_progreso → waiting_input) and rejects the buggy one
    (en_progreso → pendiente)."""

    def test_en_progreso_to_waiting_input_is_allowed(self):
        import state_machines
        assert state_machines.can_transition_task(
            "en_progreso", "waiting_input",
        ), (
            "state_machines says en_progreso → waiting_input is NOT "
            "allowed; the PR-29 fix depends on it being allowed"
        )

    def test_en_progreso_to_pendiente_is_rejected(self):
        """Pin the regression: the state machine must still reject
        the buggy transition. If someone loosens the state machine
        to accept it, both sides of the bug reopen (executor writes
        the bad transition AND the DB silently accepts it)."""
        import state_machines
        assert not state_machines.can_transition_task(
            "en_progreso", "pendiente",
        ), (
            "state_machines now allows en_progreso → pendiente — "
            "that weakens the invariant that Bug 23 relied on. "
            "If this relaxation is intentional, document it in "
            "docs/DECISIONS-LOG.md and re-evaluate whether the "
            "executor-side fix is still necessary."
        )

    def test_waiting_input_to_pendiente_is_allowed(self):
        """The other half of the approval flow: once the operator
        approves, the task must transition from waiting_input back
        to pendiente so the executor re-claims it."""
        import state_machines
        assert state_machines.can_transition_task(
            "waiting_input", "pendiente",
        ), (
            "state_machines must allow waiting_input → pendiente "
            "for the approval-grant path to work end-to-end"
        )


class TestExecutorApprovalBranchBehaviour:
    """Drive the executor's approval-required branch against a real
    in-memory sqlite and assert the task ends up in
    ``waiting_input``, not ``pendiente``. This catches the bug even
    if someone writes the code in a way that satisfies the regex
    but still produces the wrong effect at runtime."""

    @pytest.fixture
    def setup_env(self, tmp_path, monkeypatch):
        """Initialise an in-memory DB + fake install dir with just
        enough scaffolding for ``task-executor.py`` to import
        without ``SystemExit``. The executor resolves its install
        dir by looking for ``<dir>/secrets/mcp.env``, so we create
        both."""
        db_path = tmp_path / "niwa.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                title TEXT,
                status TEXT NOT NULL,
                source TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        now = "2026-04-15T10:00:00Z"
        conn.execute(
            "INSERT INTO tasks (id, title, status, source, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("T1", "Test task", "en_progreso", "manual", now, now),
        )
        conn.commit()
        conn.close()

        # Fake install dir so _resolve_install_dir() succeeds.
        secrets = tmp_path / "secrets"
        secrets.mkdir()
        (secrets / "mcp.env").write_text(
            f"NIWA_DB_PATH={db_path}\n"
            f"NIWA_LLM_COMMAND=/bin/echo\n"
        )

        monkeypatch.setenv("NIWA_DB_PATH", str(db_path))
        monkeypatch.setenv("NIWA_HOME", str(tmp_path))
        monkeypatch.setenv("NIWA_BACKEND_DIR", str(BACKEND_DIR))
        return db_path

    def test_approval_required_leaves_task_in_waiting_input(self, setup_env):
        """End-to-end: call ``_execute_task_v02`` with a mocked
        routing that returns ``approval_required=True``. The task
        row must end up with status='waiting_input', not
        'pendiente'."""
        db_path = setup_env

        te = _load_executor_module()

        # Provide a fake routing_service.decide so we don't need
        # the full v0.2 DB schema. The executor imports
        # routing_service inside _execute_task_v02, so we patch
        # sys.modules before calling.
        fake_routing = MagicMock()
        fake_routing.decide.return_value = {
            "approval_required": True,
            "routing_decision_id": "rd-1",
            "approval_id": "appr-1",
            "reason_summary": "capability_exceeds_profile",
        }
        fake_runs = MagicMock()
        fake_registry = MagicMock()
        fake_registry.get_execution_registry = MagicMock(return_value=MagicMock())

        with patch.dict(sys.modules, {
            "routing_service": fake_routing,
            "runs_service": fake_runs,
            "backend_registry": fake_registry,
        }):
            # The executor uses a module-level _conn() that opens
            # NIWA_DB_PATH. Our fixture set the env var, so this
            # should open our temp DB.
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = 'T1'",
            ).fetchone()
            conn.close()

            ok, msg = te._execute_task_v02(row)

        assert ok, f"expected approval-required branch to return True, got ({ok!r}, {msg!r})"
        assert "Approval required" in msg

        # Verify DB side-effect.
        conn = sqlite3.connect(str(db_path))
        status = conn.execute(
            "SELECT status FROM tasks WHERE id = 'T1'",
        ).fetchone()[0]
        conn.close()

        assert status == "waiting_input", (
            f"task status after approval_required branch: "
            f"expected 'waiting_input', got {status!r}. "
            f"Bug 23 regression — executor violated state machine."
        )
