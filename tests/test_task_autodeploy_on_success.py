"""Tests for PR-C1 — auto-deploy on task completion.

When ``tasks_service.update_task`` transitions a task to ``status='hecha'``
and the task has a non-null ``project_id``, the service must invoke
``hosting.deploy_project(project_id)`` as a best-effort side-effect.

Contract:

- Triggered only on transition TO ``'hecha'``; other status changes never
  call the hook.
- Skipped if the task has no ``project_id``.
- Skipped if env var ``NIWA_DEPLOY_ON_TASK_SUCCESS`` is set to ``"0"``,
  ``"false"`` or ``"no"`` (case-insensitive).
- If ``deploy_project`` raises, the status transition has already been
  committed — the update must not re-raise. The failure is recorded as a
  ``task_events`` row (type ``'alerted'``) so the UI timeline shows it.
- The JOIN in ``get_task`` now exposes ``deployment_url`` pulled from
  ``projects.url`` (it is the value that ``deploy_project`` writes there
  on success).
"""
from __future__ import annotations

import json
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
def tmp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    # Default: flag ON (matches v1 behaviour). Individual tests override
    # via monkeypatch.setenv when they need the opposite.
    monkeypatch.delenv("NIWA_DEPLOY_ON_TASK_SUCCESS", raising=False)
    try:
        with sqlite3.connect(path) as conn:
            conn.executescript((DB_DIR / "schema.sql").read_text())
            conn.execute(
                "INSERT INTO projects (id, slug, name, area, "
                "description, active, created_at, updated_at, "
                "directory, url) VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("proj-1", "p", "P", "proyecto", "", 1,
                 "2026-04-19T00:00:00Z", "2026-04-19T00:00:00Z",
                 "/tmp/niwa-fixture-dir", ""),
            )
            conn.commit()

        sys.modules.pop("tasks_service", None)
        sys.modules.pop("tasks_helpers", None)
        import tasks_helpers  # noqa: E402
        import tasks_service  # noqa: E402

        def _db_conn():
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            return c

        def _now_iso():
            return "2026-04-19T00:00:00Z"

        # ``update_task`` calls ``load_delegations_index`` via the
        # helpers module, which needs its own dep-injection so the
        # Path it probes is real (not None).
        delegations_path = Path(path).parent / "delegations.json"
        tasks_helpers._make_deps(_db_conn, _now_iso, delegations_path)
        tasks_service._make_deps(_db_conn, _now_iso, Path(path).parent)
        yield tasks_service, path
    finally:
        os.unlink(path)


def _seed_task(path, *, task_id="t-1", status="en_progreso",
               project_id="proj-1"):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, area, project_id, status, "
            "priority, source, created_at, updated_at) VALUES "
            "(?,?,?,?,?,?,?,?,?)",
            (task_id, "Build a thing", "proyecto", project_id, status,
             "media", "niwa-app",
             "2026-04-19T00:00:00Z", "2026-04-19T00:00:00Z"),
        )
        conn.commit()


class _DeploySpy:
    """Replacement for ``hosting.deploy_project`` that records calls
    without touching the real DB or writing a Caddyfile."""

    def __init__(self, *, raise_with=None, url="http://localhost:8880/p/"):
        self.calls: list[tuple] = []
        self.kwargs: list[dict] = []
        self._raise = raise_with
        self._url = url

    def __call__(self, project_id, slug="", directory=""):
        self.calls.append((project_id, slug, directory))
        self.kwargs.append({"project_id": project_id, "slug": slug,
                            "directory": directory})
        if self._raise is not None:
            raise self._raise
        return {"url": self._url, "slug": slug or "p",
                "directory": directory or "", "status": "active"}


def _spy(tasks_service, monkeypatch, **kwargs) -> _DeploySpy:
    spy = _DeploySpy(**kwargs)
    # The hook calls ``hosting.deploy_project`` via the imported module.
    # Patch the attribute on the module object so any lookup through
    # ``tasks_service.hosting`` finds the spy.
    assert hasattr(tasks_service, "hosting"), (
        "tasks_service must import hosting at module level so the "
        "hook can be wired and monkeypatched in tests."
    )
    monkeypatch.setattr(tasks_service.hosting, "deploy_project", spy)
    return spy


class TestAutoDeployHook:

    def test_update_to_hecha_with_project_id_triggers_deploy(
        self, tmp_db, monkeypatch,
    ):
        tasks_service, path = tmp_db
        _seed_task(path, project_id="proj-1")
        spy = _spy(tasks_service, monkeypatch)

        tasks_service.update_task("t-1", {"status": "hecha"})

        assert len(spy.calls) == 1, (
            f"expected exactly one deploy call, got {spy.calls!r}"
        )
        assert spy.calls[0][0] == "proj-1"

    def test_update_to_hecha_without_project_id_skips_deploy(
        self, tmp_db, monkeypatch,
    ):
        tasks_service, path = tmp_db
        _seed_task(path, project_id=None)
        spy = _spy(tasks_service, monkeypatch)

        tasks_service.update_task("t-1", {"status": "hecha"})

        assert spy.calls == [], (
            "tasks without project_id cannot be deployed — the hook "
            "must be a no-op for them."
        )

    def test_transition_to_non_hecha_does_not_trigger(
        self, tmp_db, monkeypatch,
    ):
        tasks_service, path = tmp_db
        _seed_task(path, status="en_progreso", project_id="proj-1")
        spy = _spy(tasks_service, monkeypatch)

        tasks_service.update_task("t-1", {"status": "revision"})

        assert spy.calls == []

    def test_env_flag_off_skips_deploy(self, tmp_db, monkeypatch):
        tasks_service, path = tmp_db
        _seed_task(path, project_id="proj-1")
        spy = _spy(tasks_service, monkeypatch)

        monkeypatch.setenv("NIWA_DEPLOY_ON_TASK_SUCCESS", "0")
        tasks_service.update_task("t-1", {"status": "hecha"})

        assert spy.calls == []

    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "No"])
    def test_env_flag_off_accepts_common_falsey_values(
        self, tmp_db, monkeypatch, value,
    ):
        tasks_service, path = tmp_db
        _seed_task(path, task_id=f"t-{value}", project_id="proj-1")
        spy = _spy(tasks_service, monkeypatch)

        monkeypatch.setenv("NIWA_DEPLOY_ON_TASK_SUCCESS", value)
        tasks_service.update_task(f"t-{value}", {"status": "hecha"})

        assert spy.calls == [], (
            f"env value {value!r} must be treated as OFF"
        )

    def test_deploy_failure_does_not_break_status_transition(
        self, tmp_db, monkeypatch,
    ):
        tasks_service, path = tmp_db
        _seed_task(path, project_id="proj-1")
        _spy(tasks_service, monkeypatch,
             raise_with=ValueError("Directory not found"))

        # Must NOT re-raise: the status transition is already committed
        # at the point the hook fires, and deploy failure is operational,
        # not a task failure.
        tasks_service.update_task("t-1", {"status": "hecha"})

        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT status FROM tasks WHERE id='t-1'"
            ).fetchone()
            assert row["status"] == "hecha", (
                "the transition must survive a deploy failure"
            )
            # An 'alerted' event must carry the error message so the
            # timeline shows what went wrong.
            events = conn.execute(
                "SELECT type, payload_json FROM task_events "
                "WHERE task_id='t-1' AND type='alerted'"
            ).fetchall()
            assert events, (
                "a deploy failure must produce an 'alerted' task_event "
                "so the timeline shows it"
            )
            payload = json.loads(events[-1]["payload_json"] or "{}")
            combined = json.dumps(payload)
            assert "Directory not found" in combined, (
                "the error message must be preserved in the event payload"
            )

    def test_deploy_success_does_not_create_alert_event(
        self, tmp_db, monkeypatch,
    ):
        tasks_service, path = tmp_db
        _seed_task(path, project_id="proj-1")
        _spy(tasks_service, monkeypatch)

        tasks_service.update_task("t-1", {"status": "hecha"})

        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            alerts = conn.execute(
                "SELECT id FROM task_events "
                "WHERE task_id='t-1' AND type='alerted'"
            ).fetchall()
            assert alerts == [], (
                "a successful deploy must not pollute the timeline "
                "with alert events"
            )


class TestGetTaskDeploymentUrl:

    def test_get_task_exposes_deployment_url_from_project(
        self, tmp_db,
    ):
        tasks_service, path = tmp_db
        _seed_task(path, status="hecha", project_id="proj-1")
        with sqlite3.connect(path) as conn:
            conn.execute(
                "UPDATE projects SET url=? WHERE id='proj-1'",
                ("http://p.example.com:8880/",),
            )
            conn.commit()

        task = tasks_service.get_task("t-1")

        assert task is not None
        assert task.get("deployment_url") == "http://p.example.com:8880/"

    def test_get_task_deployment_url_none_when_no_project(
        self, tmp_db,
    ):
        tasks_service, path = tmp_db
        _seed_task(path, project_id=None)

        task = tasks_service.get_task("t-1")

        assert task is not None
        assert task.get("deployment_url") in (None, ""), (
            "tasks without a project cannot have a deployment url"
        )

    def test_get_task_deployment_url_empty_when_project_not_deployed(
        self, tmp_db,
    ):
        """A project with an empty ``url`` column (never deployed) must
        not surface a misleading non-empty string — just the schema
        default (empty string or NULL)."""
        tasks_service, path = tmp_db
        _seed_task(path, project_id="proj-1")

        task = tasks_service.get_task("t-1")

        assert task is not None
        # schema stored '' in the fixture → the field must reflect that
        # honestly rather than fabricate a URL.
        assert task.get("deployment_url") in (None, "")
