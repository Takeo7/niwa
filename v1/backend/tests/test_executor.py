"""Unit tests for the adapter-driven executor (PR-V1-07, PR-V1-08).

PR-V1-07 replaced the echo with the real adapter path; PR-V1-08 layers
``prepare_task_branch`` on top so every task runs on a
``niwa/task-<id>-<slug>`` branch. The happy-path cases now use the
``git_project`` fixture (see ``conftest.py``) — a real git repo with one
seed commit — and assert ``task.branch_name`` is persisted before the
adapter spawns. The new ``test_runs_fail_on_git_setup_error`` pins the
failure path: a non-git ``local_path`` must terminate the task ``failed``
without the adapter ever running.

The race test still spins up two threads on the same DB; it does not
launch subprocesses (the contention happens inside
``claim_next_task`` before any adapter work).
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.executor.core import claim_next_task, process_pending
from app.executor.git_workspace import build_branch_name
from app.models import Base, Project, Run, RunEvent, Task, TaskEvent


FAKE_CLI_PATH = (
    Path(__file__).parent / "fixtures" / "fake_claude_cli.py"
).resolve()


@pytest.fixture(autouse=True)
def _fake_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every test at the fake CLI with a minimal realistic script.

    PR-V1-21: the real Claude CLI always emits a closing ``assistant``
    with text before the ``result`` frame; E2 now walks back to that
    assistant so the default fake mirrors the real shape. An empty or
    result-only stream is classified as ``empty_stream``.

    Since PR-V1-11b, E3 requires ≥1 artifact inside the task cwd, so the
    default run also touches a pid-scoped file under ``tmp_path``; tests
    that wire their own ``git_project`` override ``FAKE_CLAUDE_TOUCH``
    below to land the artifact inside the repo instead.
    """

    st = os.stat(FAKE_CLI_PATH)
    os.chmod(FAKE_CLI_PATH, st.st_mode | 0o111)

    script = tmp_path / "default_script.jsonl"
    script.write_text(
        json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Done."}]},
        }) + "\n"
        + json.dumps({"type": "result", "exit_code": 0}) + "\n"
    )

    monkeypatch.setenv("NIWA_CLAUDE_CLI", str(FAKE_CLI_PATH))
    monkeypatch.setenv("FAKE_CLAUDE_SCRIPT", str(script))
    monkeypatch.setenv("FAKE_CLAUDE_EXIT", "0")


@pytest.fixture()
def engine(tmp_path: Path):
    """A file-backed SQLite engine shared across sessions in the same test.

    The race test needs multiple threads to hit the same database from
    different sessions; a file-backed DB is the simplest way to achieve that
    without juggling ``StaticPool`` semantics across threads.
    """

    db_path = tmp_path / "executor.sqlite3"
    eng = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def Session_(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture()
def session(Session_) -> Iterator[Session]:
    with Session_() as s:
        yield s


def _make_project(session: Session, local_path: str | Path = "/tmp/demo", **overrides) -> Project:
    defaults = dict(
        slug="demo",
        name="Demo",
        kind="library",
        local_path=str(local_path),
    )
    defaults.update(overrides)
    project = Project(**defaults)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def _make_task(
    session: Session,
    project: Project,
    *,
    status: str = "queued",
    title: str = "t",
) -> Task:
    task = Task(
        project_id=project.id,
        title=title,
        description="",
        status=status,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


# ---------------------------------------------------------------------------
# process_pending
# ---------------------------------------------------------------------------


def test_process_pending_nothing_to_do(session: Session) -> None:
    assert process_pending(session) == 0


def test_process_pending_single_task(
    session: Session,
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # PR-V1-11b: E3 needs ≥1 artifact inside cwd, so the fake touches a
    # file in the repo before exit.
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", str(git_project / "touch-{pid}.txt"))
    project = _make_project(session, local_path=git_project)
    task = _make_task(session, project, title="only one")

    assert process_pending(session) == 1

    session.expire_all()
    refreshed = session.get(Task, task.id)
    assert refreshed is not None
    assert refreshed.status == "done"
    assert refreshed.completed_at is not None
    assert refreshed.completed_at.tzinfo is None or isinstance(
        refreshed.completed_at, datetime
    )
    # PR-V1-08: the branch name is persisted before the adapter spawns.
    assert refreshed.branch_name == build_branch_name(task)

    runs = session.query(Run).filter(Run.task_id == task.id).all()
    assert len(runs) == 1
    run = runs[0]
    assert run.status == "completed"
    assert run.exit_code == 0
    # PR-V1-11a: the run-level outcome is ``verified`` once the verifier
    # has passed; the adapter's own outcome (``cli_ok``) is consumed
    # internally by the verifier.
    assert run.outcome == "verified"
    assert run.model == "claude-code"
    assert run.finished_at is not None


def test_process_pending_multiple_tasks(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # PR-V1-11b finding #3: the default ``git_project`` is shared across
    # tasks; once task 1 dirties the tree (required for E3 to pass) task
    # 2's ``prepare_task_branch`` would trip on the dirty state. We seed
    # a dedicated repo per task and point both the project ``local_path``
    # and ``FAKE_CLAUDE_TOUCH`` at distinct dirs so every adapter run
    # writes its artifact into its own workspace.
    import subprocess as _sp

    repos: list[Path] = []
    for idx in range(3):
        d = tmp_path / f"repo-{idx}"
        d.mkdir()
        _sp.run(["git", "init", "-b", "main"], cwd=d, check=True, capture_output=True)
        _sp.run(["git", "config", "user.email", "niwa@test.local"], cwd=d, check=True)
        _sp.run(["git", "config", "user.name", "Niwa Test"], cwd=d, check=True)
        _sp.run(["git", "config", "commit.gpgsign", "false"], cwd=d, check=True)
        (d / "README.md").write_text("seed\n")
        _sp.run(["git", "add", "README.md"], cwd=d, check=True, capture_output=True)
        _sp.run(["git", "commit", "-m", "init"], cwd=d, check=True, capture_output=True)
        repos.append(d)

    # Every task uses its own project rooted on a dedicated repo.
    first_project = _make_project(session, local_path=repos[0], slug="repo-0")
    second_project = _make_project(session, local_path=repos[1], slug="repo-1")
    third_project = _make_project(session, local_path=repos[2], slug="repo-2")
    first = _make_task(session, first_project, title="first")
    second = _make_task(session, second_project, title="second")
    third = _make_task(session, third_project, title="third")

    # The touch path is resolved relative to each run's cwd, so a single
    # ``touch-<pid>.txt`` placed via the adapter cwd lands inside each
    # repo in turn.
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", "touch-{pid}.txt")

    assert process_pending(session) == 3

    session.expire_all()
    for t_id in (first.id, second.id, third.id):
        t = session.get(Task, t_id)
        assert t is not None
        assert t.status == "done"

    # Creation order is preserved when draining — first created, first done.
    runs = (
        session.query(Run)
        .order_by(Run.id.asc())
        .all()
    )
    assert [r.task_id for r in runs] == [first.id, second.id, third.id]


def test_process_pending_skips_non_queued(session: Session) -> None:
    project = _make_project(session)
    inbox = _make_task(session, project, status="inbox", title="idle")
    running = _make_task(session, project, status="running", title="busy")
    done = _make_task(session, project, status="done", title="old")

    assert process_pending(session) == 0

    session.expire_all()
    for t_id, expected in (
        (inbox.id, "inbox"),
        (running.id, "running"),
        (done.id, "done"),
    ):
        t = session.get(Task, t_id)
        assert t is not None
        assert t.status == expected

    # No runs should have been created either.
    assert session.query(Run).count() == 0


# ---------------------------------------------------------------------------
# Event writes
# ---------------------------------------------------------------------------


def test_run_writes_expected_events(
    session: Session,
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", str(git_project / "touch-{pid}.txt"))
    project = _make_project(session, local_path=git_project)
    task = _make_task(session, project, title="events")

    assert process_pending(session) == 1

    run = session.query(Run).filter(Run.task_id == task.id).one()
    events = (
        session.query(RunEvent)
        .filter(RunEvent.run_id == run.id)
        .order_by(RunEvent.id.asc())
        .all()
    )
    # The adapter pipeline writes: started, <stream events...>, completed.
    types = [e.event_type for e in events]
    assert types[0] == "started"
    assert types[-1] == "completed"
    # The default fake script emits exactly one ``result`` line between
    # the synthetic bookends.
    assert "result" in types


def test_task_writes_status_transitions(
    session: Session,
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", str(git_project / "touch-{pid}.txt"))
    project = _make_project(session, local_path=git_project)
    task = _make_task(session, project, title="transitions")

    assert process_pending(session) == 1

    events = (
        session.query(TaskEvent)
        .filter(TaskEvent.task_id == task.id)
        .order_by(TaskEvent.id.asc())
        .all()
    )
    # Two status_changed events written by the executor:
    #   queued → running, running → done.
    status_events = [e for e in events if e.kind == "status_changed"]
    assert len(status_events) == 2
    payloads = [e.payload_json for e in status_events]
    assert '"from": "queued"' in payloads[0]
    assert '"to": "running"' in payloads[0]
    assert '"from": "running"' in payloads[1]
    assert '"to": "done"' in payloads[1]


# ---------------------------------------------------------------------------
# Race condition — two threads calling claim_next_task on the same task.
# ---------------------------------------------------------------------------


def test_claim_is_atomic_under_race(engine, Session_) -> None:
    # Seed one queued task. Each thread gets its own session on the same DB.
    with Session_() as seed:
        project = _make_project(seed)
        task = _make_task(seed, project, title="contended")
        task_id = task.id

    results: list[Task | None] = [None, None]
    errors: list[BaseException | None] = [None, None]
    barrier = threading.Barrier(2)

    def worker(index: int) -> None:
        try:
            with Session_() as s:
                barrier.wait(timeout=5)
                results[index] = claim_next_task(s)
        except BaseException as exc:  # noqa: BLE001 - re-raised via assert
            errors[index] = exc

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    # SQLite may raise ``OperationalError: database is locked`` on the loser
    # when two BEGIN IMMEDIATE collide; we treat that as "lost the race".
    # The invariant is: no more than one winner, and the task ends in
    # ``running``.
    winners = [r for r in results if r is not None]
    assert len(winners) <= 1, "two threads claimed the same task"

    # At least one side must have either won (returned the task) or recognised
    # the contention (returned None / raised OperationalError). We never
    # silently lose the task.
    from sqlalchemy.exc import OperationalError

    for err in errors:
        if err is not None:
            assert isinstance(err, OperationalError), err

    # Final state: the task is ``running`` (one of the threads did claim it).
    with Session_() as s:
        final = s.get(Task, task_id)
        assert final is not None
        assert final.status == "running"


# ---------------------------------------------------------------------------
# Git workspace failure — non-git local_path (PR-V1-08)
# ---------------------------------------------------------------------------


def test_runs_fail_on_git_setup_error(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_triage_execute: None,
) -> None:
    """A non-git ``local_path`` must fail the task before the adapter spawns."""

    # If the executor ever reached the adapter this would surface as
    # ``cli_not_found``, not the expected ``git_setup_failed``.
    monkeypatch.setenv("NIWA_CLAUDE_CLI", str(tmp_path / "does-not-exist"))
    plain = tmp_path / "no-git-here"
    plain.mkdir()
    project = _make_project(session, local_path=plain)
    task = _make_task(session, project, title="needs git")

    assert process_pending(session) == 1

    session.expire_all()
    refreshed = session.get(Task, task.id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    assert refreshed.branch_name is None

    run = session.query(Run).filter(Run.task_id == task.id).one()
    assert run.status == "failed"
    assert run.outcome == "git_setup_failed"
    assert run.exit_code is None  # adapter never spawned

    events = session.query(RunEvent).filter(RunEvent.run_id == run.id).all()
    types = [e.event_type for e in events]
    assert "result" not in types  # no CLI stream reached the DB
    error_events = [e for e in events if e.event_type == "error"]
    assert error_events, "expected an error event on git_setup_failed"
    payload = json.loads(error_events[0].payload_json or "{}")
    assert "git_setup_failed" in payload.get("reason", "")


# ---------------------------------------------------------------------------
# Triage integration (PR-V1-12b)
# ---------------------------------------------------------------------------


def test_process_pending_executes_when_triage_says_execute(
    session: Session,
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Triage "execute" → normal adapter pipeline runs to verified.

    Spies ``triage_task`` to pin that the executor actually routes through
    it before spawning the adapter; without that hop the test would still
    pass via the default fake CLI script, which is a false green.
    """

    import app.executor.core as executor_core

    real_triage = executor_core.triage_task
    calls: list[tuple[object, object]] = []

    def spy(project, task):
        calls.append((project, task))
        return real_triage(project, task)

    monkeypatch.setattr(executor_core, "triage_task", spy)

    monkeypatch.setenv(
        "FAKE_CLAUDE_TRIAGE_JSON",
        json.dumps({"decision": "execute", "subtasks": [], "rationale": "ok"}),
    )
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", str(git_project / "touch-{pid}.txt"))
    project = _make_project(session, local_path=git_project)
    task = _make_task(session, project, title="single change")

    assert process_pending(session) == 1
    assert len(calls) == 1, "triage_task must be invoked exactly once"

    session.expire_all()
    refreshed = session.get(Task, task.id)
    assert refreshed is not None
    assert refreshed.status == "done"
    assert refreshed.branch_name == build_branch_name(task)

    run = session.query(Run).filter(Run.task_id == task.id).one()
    assert run.status == "completed"
    assert run.outcome == "verified"


def test_process_pending_splits_when_triage_says_split(
    session: Session,
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Triage "split" → parent stays ``running`` during the split, then
    aggregates once every subtask has settled. N subtasks created.

    Scope note: the brief asks to assert ``status=="queued"`` on the
    subtasks, which only holds for the instant between ``_apply_split``
    and the next iteration of ``process_pending``. The real executor
    keeps draining, re-triages each subtask (fake falls back to
    ``execute`` once the marker is burned), and runs the adapter on
    them.

    PR-V1-23 note: both subtasks share ``git_project`` here, so the
    second one trips ``prepare_task_branch`` with a dirty tree and
    fails. Aggregation then promotes the parent to ``failed``. The
    ``done`` path is covered by
    ``test_parent_promoted_to_done_when_all_subtasks_done``.
    """

    monkeypatch.setenv(
        "FAKE_CLAUDE_TRIAGE_JSON",
        json.dumps(
            {"decision": "split", "subtasks": ["one", "two"], "rationale": "two areas"}
        ),
    )
    # Consume the split verdict only once; without this marker every
    # subtask we create below would be re-triaged with the same JSON
    # and recurse forever inside ``process_pending``.
    marker = git_project / ".triage-once"
    monkeypatch.setenv("FAKE_CLAUDE_TRIAGE_MARKER", str(marker))
    # Subtasks drain through the normal adapter path once triage degrades
    # to ``execute``; land artifacts inside the repo so verify passes.
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", str(git_project / "touch-{pid}.txt"))
    project = _make_project(session, local_path=git_project)
    parent = _make_task(session, project, title="big change")

    # The parent pass + two subtasks = 3 iterations of process_pending.
    assert process_pending(session) == 3

    session.expire_all()
    refreshed_parent = session.get(Task, parent.id)
    assert refreshed_parent is not None
    # Aggregation: any failed subtask → parent failed. See docstring above.
    assert refreshed_parent.status == "failed"

    # No run was created on the parent — split short-circuits the adapter.
    assert session.query(Run).filter(Run.task_id == parent.id).count() == 0

    # Two subtasks attached to the parent with the right project.
    subtasks = (
        session.query(Task)
        .filter(Task.parent_task_id == parent.id)
        .order_by(Task.id.asc())
        .all()
    )
    assert [t.title for t in subtasks] == ["one", "two"]
    assert all(t.project_id == parent.project_id for t in subtasks)

    # TaskEvent(kind="message") carries the triage_split marker (SPEC §3
    # does not allow ``triage_split`` in the enum, so the marker lives in
    # the payload — Opción B).
    message_events = (
        session.query(TaskEvent)
        .filter(TaskEvent.task_id == parent.id, TaskEvent.kind == "message")
        .all()
    )
    assert len(message_events) == 1
    payload = json.loads(message_events[0].payload_json or "{}")
    assert payload.get("event") == "triage_split"
    assert payload.get("subtask_ids") == [t.id for t in subtasks]
    assert payload.get("rationale") == "two areas"


# Safe mode finalize integration (PR-V1-13) — spy in for ``finalize_task``
# that also writes ``task.pr_url`` so we can assert the executor invokes
# it on the verified branch and the pipeline still closes the task
# ``done``.


# PR-V1-22 — resume via session_handle + user response prompt.


class _StubAdapter:
    """Captures ``__init__`` kwargs + behaves like a benign cli_ok run."""

    instances: list["_StubAdapter"] = []

    def __init__(self, cli_path, *, cwd, prompt, timeout, extra_args=None,
                 resume_handle=None):
        self.prompt = prompt
        self.resume_handle = resume_handle
        type(self).instances.append(self)

    def iter_events(self): return iter([])
    def wait(self): return 0
    def close(self): pass
    @property
    def outcome(self): return "cli_ok"
    @property
    def exit_code(self): return 0
    @property
    def session_id(self): return "session-xyz"


def _seed_resume_scenario(session: Session, git_project: Path) -> Task:
    """Task queued with prior run's session_handle + user_response event.

    Mirrors the real post-``respond_to_task`` state: the endpoint already
    cleared ``pending_question`` and re-queued the task atomically, so the
    field is not set here.
    """

    project = _make_project(session, local_path=git_project)
    task = _make_task(session, project, title="needs framework")
    session.add(Run(
        task_id=task.id, status="failed", model="claude-code",
        started_at=datetime.utcnow(), finished_at=datetime.utcnow(),
        outcome="needs_input", session_handle="prev-handle-xxx",
        artifact_root=str(git_project),
    ))
    session.add(TaskEvent(
        task_id=task.id, kind="message", message=None,
        payload_json=json.dumps(
            {"event": "user_response", "text": "Use React with Vite"}
        ),
    ))
    session.commit()
    return task


def test_resume_path_uses_prev_run_session_handle(
    session: Session, git_project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Executor picks the last run's session_handle and passes it via kwarg."""

    import app.executor.core as executor_core
    _StubAdapter.instances = []
    monkeypatch.setattr(executor_core, "ClaudeCodeAdapter", _StubAdapter)
    _seed_resume_scenario(session, git_project)

    assert process_pending(session) == 1
    assert len(_StubAdapter.instances) == 1
    assert _StubAdapter.instances[0].resume_handle == "prev-handle-xxx"


def test_resume_prompt_is_user_response_not_task_description(
    session: Session, git_project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On resume, prompt is the user's text — not title/description."""

    import app.executor.core as executor_core
    _StubAdapter.instances = []
    monkeypatch.setattr(executor_core, "ClaudeCodeAdapter", _StubAdapter)
    task = _seed_resume_scenario(session, git_project)

    assert process_pending(session) == 1
    spawned = _StubAdapter.instances[0]
    assert spawned.prompt == "Use React with Vite"
    assert task.title not in spawned.prompt


def test_process_pending_finalizes_verified_run_with_gh_stub(
    session: Session, git_project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.executor.core as executor_core
    from app.finalize import FinalizeResult

    calls: list[int] = []
    url = "https://github.com/owner/repo/pull/99"

    def fake_finalize(session, run, task, project):
        calls.append(task.id)
        task.pr_url = url
        session.commit()
        return FinalizeResult(
            committed=True,
            pushed=True,
            pr_url=url,
            pr_merged=False,
            commands_skipped=[],
        )

    monkeypatch.setattr(executor_core, "finalize_task", fake_finalize)
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", str(git_project / "touch-{pid}.txt"))
    project = _make_project(session, local_path=git_project)
    task = _make_task(session, project, title="finalize me")

    assert process_pending(session) == 1
    assert calls == [task.id]

    session.expire_all()
    refreshed = session.get(Task, task.id)
    assert refreshed is not None
    assert refreshed.status == "done"
    assert refreshed.pr_url == url

    run = session.query(Run).filter(Run.task_id == task.id).one()
    assert run.outcome == "verified"
    assert run.status == "completed"


# ---------------------------------------------------------------------------
# Parent task promotion (PR-V1-23)
# ---------------------------------------------------------------------------
#
# Before PR-V1-23 ``_apply_split`` closed the parent ``done`` immediately.
# Now the parent stays ``running`` after the split and is promoted only
# when every subtask has reached a terminal state. The four tests below
# pin the contract: one against the split path, three against
# ``_finalize`` which is where the aggregation hook lives.


def _make_parent_with_subtasks(
    session: Session,
    *,
    parent_status: str = "running",
    subtask_statuses: list[str],
) -> tuple[Task, list[Task]]:
    """Seed a parent + N subtasks with scripted statuses for promotion tests."""

    project = _make_project(session)
    parent = _make_task(session, project, status=parent_status, title="parent")
    subtasks: list[Task] = []
    for idx, status in enumerate(subtask_statuses):
        sub = Task(
            project_id=project.id,
            parent_task_id=parent.id,
            title=f"sub-{idx}",
            description="",
            status=status,
        )
        session.add(sub)
        subtasks.append(sub)
    session.commit()
    for s in subtasks:
        session.refresh(s)
    session.refresh(parent)
    return parent, subtasks


def test_parent_stays_running_after_split(session: Session) -> None:
    """``_apply_split`` must leave the parent in ``running`` — the
    terminal transition now ships via ``_maybe_promote_parent`` when
    the subtasks finish."""

    from app.executor.core import _apply_split
    from app.triage import TriageDecision

    project = _make_project(session)
    parent = _make_task(session, project, status="running", title="big change")

    decision = TriageDecision(
        kind="split",
        subtasks=["one", "two"],
        rationale="two areas",
        raw_output="",
    )
    _apply_split(session, parent, decision)

    session.expire_all()
    refreshed = session.get(Task, parent.id)
    assert refreshed is not None
    assert refreshed.status == "running"
    assert refreshed.completed_at is None

    subtasks = (
        session.query(Task)
        .filter(Task.parent_task_id == parent.id)
        .order_by(Task.id.asc())
        .all()
    )
    assert [t.status for t in subtasks] == ["queued", "queued"]
    assert [t.title for t in subtasks] == ["one", "two"]


def _finalize_subtask_as(
    session: Session, subtask: Task, outcome: str
) -> None:
    """Minimal ``_finalize`` driver: synthesize a Run and call the hook."""

    from app.executor.core import _finalize

    run = Run(
        task_id=subtask.id,
        status="running",
        model="claude-code",
        started_at=datetime.now(timezone.utc),
        artifact_root="",
    )
    session.add(run)
    session.commit()
    _finalize(session, subtask, run, outcome=outcome, exit_code=0)


def test_parent_promoted_to_done_when_all_subtasks_done(
    session: Session,
) -> None:
    """All subtasks ``done`` → parent promoted ``done`` with ``completed_at``."""

    parent, (sub_a, sub_b) = _make_parent_with_subtasks(
        session, subtask_statuses=["done", "running"],
    )
    # Finalize the second subtask through the verified path so that
    # _finalize itself flips its status to ``done`` and fires the hook.
    _finalize_subtask_as(session, sub_b, outcome="verified")

    session.expire_all()
    refreshed = session.get(Task, parent.id)
    assert refreshed is not None
    assert refreshed.status == "done"
    assert refreshed.completed_at is not None

    # A status_changed TaskEvent with reason=subtasks_terminal must be emitted
    # so downstream consumers (SSE, audit) can trace the aggregation.
    events = (
        session.query(TaskEvent)
        .filter(TaskEvent.task_id == parent.id, TaskEvent.kind == "status_changed")
        .all()
    )
    payloads = [json.loads(e.payload_json or "{}") for e in events]
    assert any(
        p.get("to") == "done" and p.get("reason") == "subtasks_terminal"
        for p in payloads
    ), payloads


def test_parent_promoted_to_failed_when_any_subtask_failed(
    session: Session,
) -> None:
    """Any ``failed`` subtask wins the aggregation even if peers are done."""

    parent, (sub_a, sub_b) = _make_parent_with_subtasks(
        session, subtask_statuses=["done", "running"],
    )
    # Drive the second subtask through the failure path.
    _finalize_subtask_as(session, sub_b, outcome="adapter_exception")

    session.expire_all()
    refreshed = session.get(Task, parent.id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    # ``completed_at`` is only set on the ``done`` branch.
    assert refreshed.completed_at is None

    # Symmetric with the ``done`` test: the promotion must emit a
    # status_changed TaskEvent with ``reason=subtasks_terminal`` so SSE
    # and audit consumers can distinguish aggregation from a direct
    # ``_finalize`` on the parent itself.
    events = (
        session.query(TaskEvent)
        .filter(TaskEvent.task_id == parent.id, TaskEvent.kind == "status_changed")
        .all()
    )
    payloads = [json.loads(e.payload_json or "{}") for e in events]
    assert any(
        p.get("to") == "failed" and p.get("reason") == "subtasks_terminal"
        for p in payloads
    ), payloads


def test_parent_stays_running_when_any_subtask_not_terminal(
    session: Session,
) -> None:
    """One subtask still non-terminal → parent stays ``running`` (no promo)."""

    parent, (sub_a, sub_b) = _make_parent_with_subtasks(
        session, subtask_statuses=["running", "running"],
    )
    _finalize_subtask_as(session, sub_a, outcome="verified")

    session.expire_all()
    refreshed = session.get(Task, parent.id)
    assert refreshed is not None
    assert refreshed.status == "running"
    assert refreshed.completed_at is None

    # No status_changed event for the parent should fire while children pend.
    events = (
        session.query(TaskEvent)
        .filter(TaskEvent.task_id == parent.id, TaskEvent.kind == "status_changed")
        .all()
    )
    assert not events, [e.payload_json for e in events]
