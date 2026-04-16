"""Tests for ``approval_service.resolve_approval``'s task transition (PR-29, Bug 23).

Companion to ``tests/test_task_executor_approval_state.py``.

The executor side transitions the task from ``en_progreso`` to
``waiting_input`` when routing reports ``approval_required``. This
file pins the inverse transition: when the operator resolves the
approval as ``approved``, the task must go back to ``pendiente`` so
the executor re-claims it.

Original PR-29 placed the inverse transition in the HTTP handler
in ``app.py``. Review surfaced that the assistant-tool path
(``assistant_service.tool_approval_respond``, reachable via the
HTTP endpoint ``POST /api/assistant/tools/approval_respond`` and
via MCP) bypassed the handler and called ``resolve_approval``
directly — so that path still orphaned tasks in ``waiting_input``.
Fix: move the transition INSIDE ``resolve_approval`` itself so
every caller benefits. These tests pin that contract.

Tests:
- approve on waiting_input task → task becomes pendiente.
- approve on task not in waiting_input → task unchanged.
- reject on waiting_input task → task unchanged.
- idempotent approve (second call) → task stays in pendiente.
- approval via ``tool_approval_respond`` (assistant path) also
  triggers the transition.
- state_machines.assert_task_transition is enforced.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
BACKEND_DIR = REPO_ROOT / "niwa-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Fresh sqlite with the full v0.2 schema + migrations."""
    import glob
    db = tmp_path / "niwa.sqlite3"
    schema_sql = (REPO_ROOT / "niwa-app" / "db" / "schema.sql").read_text()
    conn = sqlite3.connect(str(db))
    conn.executescript(schema_sql)
    migrations_dir = REPO_ROOT / "niwa-app" / "db" / "migrations"
    import setup
    for mfile in sorted(glob.glob(str(migrations_dir / "*.sql"))):
        setup._apply_sql_idempotent(conn, Path(mfile).read_text())
    conn.commit()
    conn.close()

    monkeypatch.setenv("NIWA_DB_PATH", str(db))
    monkeypatch.setenv("NIWA_APP_AUTH_REQUIRED", "0")
    return db


def _seed_task_and_approval(db_path: Path, *, task_status: str):
    import uuid

    task_id = str(uuid.uuid4())
    approval_id = str(uuid.uuid4())
    now = "2026-04-15T10:00:00Z"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT INTO tasks (id, title, status, source, created_at, updated_at) "
        "VALUES (?, ?, ?, 'manual', ?, ?)",
        (task_id, "Test task", task_status, now, now),
    )
    conn.execute(
        "INSERT INTO approvals "
        "(id, task_id, backend_run_id, approval_type, reason, "
        " risk_level, status, requested_at) "
        "VALUES (?, ?, NULL, 'capability', 'test', 'medium', "
        " 'pending', ?)",
        (approval_id, task_id, now),
    )
    conn.commit()
    conn.close()
    return task_id, approval_id


def _task_status(db_path: Path, task_id: str) -> str | None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT status FROM tasks WHERE id = ?", (task_id,),
    ).fetchone()
    conn.close()
    return row["status"] if row else None


class TestResolveApprovalTransitionsTask:
    """Direct exercise of the contract point — ``resolve_approval``
    itself does the task transition now. Every path that lands here
    inherits the fix."""

    def test_approve_on_waiting_input_transitions_task_to_pendiente(
        self, db_path,
    ):
        task_id, approval_id = _seed_task_and_approval(
            db_path, task_status="waiting_input",
        )
        import approval_service

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        approval_service.resolve_approval(
            approval_id, "approved", "test_user", conn,
        )
        conn.close()

        assert _task_status(db_path, task_id) == "pendiente", (
            "approve on waiting_input task must transition to "
            "pendiente (Bug 23 fix — inverse transition must live "
            "inside resolve_approval so every caller gets it)"
        )

    def test_approve_does_not_touch_task_in_other_states(self, db_path):
        """Defensive: if the task is archivada / pendiente /
        en_progreso when the approval is resolved, don't force-move
        it."""
        for initial in ("archivada", "pendiente", "en_progreso"):
            task_id, approval_id = _seed_task_and_approval(
                db_path, task_status=initial,
            )
            import approval_service

            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            approval_service.resolve_approval(
                approval_id, "approved", "test_user", conn,
            )
            conn.close()

            assert _task_status(db_path, task_id) == initial, (
                f"approve on task in {initial!r} must not force-"
                f"transition — expected {initial!r} unchanged, got "
                f"{_task_status(db_path, task_id)!r}"
            )

    def test_reject_leaves_task_alone(self, db_path):
        task_id, approval_id = _seed_task_and_approval(
            db_path, task_status="waiting_input",
        )
        import approval_service

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        approval_service.resolve_approval(
            approval_id, "rejected", "test_user", conn,
        )
        conn.close()

        assert _task_status(db_path, task_id) == "waiting_input", (
            "reject must NOT transition the task — operator decides "
            "what to do next (archive, retry, manual re-queue)"
        )

    def test_idempotent_approve_is_safe(self, db_path):
        """Second approve is an idempotent no-op in approval_service
        (returns the existing row early, before hitting the new
        transition block). Task stays wherever the first call left
        it."""
        task_id, approval_id = _seed_task_and_approval(
            db_path, task_status="waiting_input",
        )
        import approval_service

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        approval_service.resolve_approval(
            approval_id, "approved", "test_user", conn,
        )
        # Second call — approval_service short-circuits.
        approval_service.resolve_approval(
            approval_id, "approved", "test_user", conn,
        )
        conn.close()

        assert _task_status(db_path, task_id) == "pendiente"


class TestAssistantToolApprovalRespondPath:
    """Pin that the ``assistant_service.tool_approval_respond``
    path (used by OpenClaw via MCP and by the HTTP endpoint
    ``POST /api/assistant/tools/approval_respond``) ALSO gets the
    transition. This was the bug the review caught: the original
    PR-29 fix only covered the direct HTTP handler."""

    def test_tool_approval_respond_approved_transitions_task(self, db_path):
        task_id, approval_id = _seed_task_and_approval(
            db_path, task_status="waiting_input",
        )
        import assistant_service

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = assistant_service.tool_approval_respond(
            conn,
            project_id=None,
            params={"approval_id": approval_id, "decision": "approved"},
        )
        conn.close()

        assert "error" not in result, (
            f"tool_approval_respond errored: {result!r}"
        )
        assert _task_status(db_path, task_id) == "pendiente", (
            "tool_approval_respond (assistant path) must also "
            "transition the task — previous implementation bypassed "
            "the transition and left tasks orphaned in waiting_input."
        )

    def test_tool_approval_respond_rejected_leaves_task_alone(self, db_path):
        task_id, approval_id = _seed_task_and_approval(
            db_path, task_status="waiting_input",
        )
        import assistant_service

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        assistant_service.tool_approval_respond(
            conn,
            project_id=None,
            params={"approval_id": approval_id, "decision": "rejected"},
        )
        conn.close()

        assert _task_status(db_path, task_id) == "waiting_input"


class TestStateMachineValidationEnforced:
    """If a future refactor weakens state_machines (e.g. removes
    ``waiting_input → pendiente``), ``resolve_approval`` must fail
    loud instead of silently skipping or corrupting state."""

    def test_waiting_input_to_pendiente_remains_allowed(self):
        import state_machines

        assert state_machines.can_transition_task(
            "waiting_input", "pendiente",
        ), (
            "state_machines.TASK_TRANSITIONS must allow "
            "waiting_input → pendiente for resolve_approval's "
            "inverse transition to succeed. If this changes, "
            "resolve_approval will raise InvalidTransitionError "
            "on every approve — which is loud enough to catch, "
            "but we want to pin the expectation here too."
        )

    def test_assert_task_transition_is_imported_in_resolve(self):
        """Pin the import line — a refactor that drops the
        validator would silently allow any invalid state to slip
        through (the transition check itself would become
        ``if task_row[...] == 'waiting_input': UPDATE ... WHERE
        status = 'waiting_input'`` without the explicit assert)."""
        src = (
            REPO_ROOT / "niwa-app" / "backend" / "approval_service.py"
        ).read_text()
        assert "from state_machines import assert_task_transition" in src, (
            "resolve_approval must import assert_task_transition — "
            "without it the state machine compliance check is silent"
        )
        assert 'assert_task_transition("waiting_input", "pendiente")' in src, (
            "resolve_approval must call "
            'assert_task_transition("waiting_input", "pendiente") '
            "before the task UPDATE"
        )


class TestHandlerNoLongerHasDuplicateBlock:
    """The HTTP handler in ``app.py`` used to duplicate the
    transition logic. After PR-29's refactor (based on review
    feedback), it should defer to ``resolve_approval``. If this
    test ever fails, someone re-introduced the duplication."""

    def test_app_py_handler_does_not_duplicate_transition(self):
        src = (
            REPO_ROOT / "niwa-app" / "backend" / "app.py"
        ).read_text()
        # Extract the resolve handler block.
        start = src.index("api/approvals/[^/]+/resolve")
        # Find the enclosing dispatch stanza — take 80 lines from
        # here as a rough window.
        window = src[start:start + 4000]
        # The duplicate transition used to do a SELECT/UPDATE on
        # tasks inside the handler. That should no longer be there.
        assert "state_machines.assert_task_transition" not in window, (
            "app.py handler still contains a direct call to "
            "state_machines.assert_task_transition — the transition "
            "logic must live in approval_service.resolve_approval "
            "so every caller benefits (assistant tool path, MCP, "
            "etc.). Remove the duplicate."
        )
        assert "UPDATE tasks SET status = 'pendiente'" not in window, (
            "app.py handler still contains a direct 'UPDATE tasks' "
            "for the approve path — that logic moved to "
            "approval_service.resolve_approval."
        )
