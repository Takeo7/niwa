"""E3 + E4 — artifact scanning unit tests (PR-V1-11b).

* E3 ``check_artifacts_in_cwd`` runs ``git status --porcelain`` and
  passes iff at least one line of change is reported.
* E4 ``check_no_artifacts_outside_cwd`` walks the ``run_events`` stream
  looking for write-class ``tool_use`` payloads whose absolute
  ``file_path`` escapes the task cwd.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Project, Run, RunEvent, Task
from app.verification import artifacts as artifacts_mod
from app.verification.artifacts import (
    check_artifacts_in_cwd,
    check_no_artifacts_outside_cwd,
)


def _has_locale(name: str) -> bool:
    """True iff ``locale -a`` lists ``name`` (case-insensitive match)."""

    try:
        proc = subprocess.run(
            ["locale", "-a"], capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return False
    target = name.lower().replace("-", "")
    for line in proc.stdout.splitlines():
        if line.strip().lower().replace("-", "") == target:
            return True
    return False


@pytest.fixture()
def session(tmp_path: Path) -> Iterator[Session]:
    eng = create_engine(f"sqlite:///{tmp_path / 'art.sqlite3'}", future=True)
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng, autoflush=False, autocommit=False, future=True)() as s:
        yield s
    eng.dispose()


def _seed_run(session: Session, cwd: Path) -> Run:
    project = Project(slug="p", name="P", kind="library", local_path=str(cwd))
    session.add(project)
    session.commit()
    task = Task(project_id=project.id, title="t", description="", status="running")
    session.add(task)
    session.commit()
    run = Run(task_id=task.id, status="running", model="claude-code", artifact_root=str(cwd))
    session.add(run)
    session.commit()
    return run


def test_dirty_cwd_passes_e3(git_project: Path) -> None:
    # Modify a tracked file so ``git status --porcelain`` reports ≥1 line.
    (git_project / "README.md").write_text("seed\ndirty\n")

    evidence: dict = {}
    assert check_artifacts_in_cwd(git_project, evidence) is True
    assert evidence["artifacts_count"] >= 1
    assert evidence.get("git_available") is True


def test_clean_cwd_fails_no_artifacts(git_project: Path) -> None:
    # ``git_project`` is seeded with one committed file and a clean tree.
    evidence: dict = {}
    assert check_artifacts_in_cwd(git_project, evidence) is False
    assert evidence["artifacts_count"] == 0
    assert evidence.get("error_code") == "no_artifacts"


def test_absolute_path_outside_cwd_fails(session: Session, git_project: Path) -> None:
    run = _seed_run(session, git_project)
    session.add(
        RunEvent(
            run_id=run.id,
            event_type="tool_use",
            payload_json=json.dumps(
                {"name": "Write", "input": {"file_path": "/tmp/leak.txt"}}
            ),
        )
    )
    session.commit()

    evidence: dict = {}
    assert check_no_artifacts_outside_cwd(session, run, git_project, evidence) is False
    assert evidence["artifacts_outside_cwd"] is True
    assert evidence["offending_paths"] == ["/tmp/leak.txt"]
    assert evidence["tool_use_writes_scanned"] == 1
    assert evidence["tool_use_writes_absolute"] == 1


def test_non_git_cwd_skips_e3_under_localized_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skip-gracefully branch must not depend on English git stderr.

    Repro of the v1.1 smoke red: when ``git`` runs under a localized LANG,
    stderr reads e.g. ``"fatal: no es un repositorio git ..."`` and the
    English ``"not a git repository"`` substring check misses, so the
    function falls through to ``error_code='no_artifacts'`` instead of the
    graceful skip. Forcing ``LANG=C`` in the subprocess ``env`` is the
    fix; this test guards the contract regardless of host locale by
    monkeypatching ``subprocess.run`` directly.
    """

    plain = tmp_path / "not-a-repo"
    plain.mkdir()

    def fake_run(cmd, *_a, **_k):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(
            returncode=128,
            cmd=cmd,
            output="",
            stderr=(
                "fatal: no es un repositorio git "
                "(ni ninguno de los directorios superiores): .git\n"
            ),
        )

    monkeypatch.setattr(artifacts_mod.subprocess, "run", fake_run)

    evidence: dict = {}
    assert check_artifacts_in_cwd(plain, evidence) is True
    assert evidence.get("git_available") is False
    assert evidence.get("error_code") is None


@pytest.mark.skipif(
    not _has_locale("es_ES.UTF-8"),
    reason="es_ES.UTF-8 locale not generated in this sandbox",
)
def test_check_artifacts_real_subprocess_under_localized_lang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wiring guard: the ``env`` override must propagate to the real
    ``git status --porcelain`` invocation, not just the detection branch.
    Without this, a future refactor that drops ``env=`` would still pass
    the monkeypatched test above.
    """

    monkeypatch.setenv("LANG", "es_ES.UTF-8")
    monkeypatch.setenv("LC_ALL", "es_ES.UTF-8")
    monkeypatch.setenv("LANGUAGE", "es")
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    evidence: dict = {}
    assert check_artifacts_in_cwd(plain, evidence) is True
    assert evidence.get("error_code") is None
    assert evidence.get("git_available") is False


def test_non_git_cwd_skips_e3_gracefully(tmp_path: Path) -> None:
    """A project dir that is not a git repo must degrade gracefully.

    The brief accepts this as a pass: ``git_available = False`` and no
    ``error_code`` set — 11c will gate tests on ``git_available`` instead
    of re-running the porcelain check.
    """

    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    evidence: dict = {}
    assert check_artifacts_in_cwd(plain, evidence) is True
    assert evidence.get("git_available") is False


def test_missing_cwd_fails_hard(tmp_path: Path) -> None:
    """A cwd that doesn't exist is an executor/operator bug, not a skip.

    Before the fix-up, ``subprocess.run`` raised ``FileNotFoundError``
    for both "``git`` not installed" and "``cwd`` missing", and the
    skip branch silently turned a broken cwd into a pass. Now a missing
    directory fails hard with ``error_code="cwd_missing"``.
    """

    missing = tmp_path / "does-not-exist"
    evidence: dict = {}
    assert check_artifacts_in_cwd(missing, evidence) is False
    assert evidence.get("cwd_exists") is False
    assert evidence.get("error_code") == "cwd_missing"
    assert evidence.get("git_available") is False


def test_embedded_tool_use_outside_cwd_fails(
    session: Session, git_project: Path
) -> None:
    """E4 must inspect ``tool_use`` blocks embedded in ``assistant``
    messages — the canonical shape the real Claude CLI emits per v0.2
    ``FIX-20260420``. Before the fix-up, E4 only scanned top-level
    ``event_type="tool_use"`` rows, so real streams passed vacuously.
    """

    run = _seed_run(session, git_project)
    session.add(
        RunEvent(
            run_id=run.id,
            event_type="assistant",
            payload_json=json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "OK"},
                            {
                                "type": "tool_use",
                                "name": "Write",
                                "input": {"file_path": "/tmp/leak.txt"},
                            },
                        ]
                    },
                }
            ),
        )
    )
    session.commit()

    evidence: dict = {}
    assert check_no_artifacts_outside_cwd(session, run, git_project, evidence) is False
    assert evidence["artifacts_outside_cwd"] is True
    assert evidence["offending_paths"] == ["/tmp/leak.txt"]
    assert evidence["tool_use_writes_scanned"] == 1
    assert evidence["tool_use_writes_absolute"] == 1
