"""Tests for cleanup service (Phase 8, QA-09)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Project, Task
from app.models.api_token import ApiToken
from app.models.audit_event import AuditEvent
from app.models.niwa_session import NiwaSession
from app.services.cleanup import cleanup


@pytest.fixture()
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    SessionMaker = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    s = SessionMaker()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def test_cleanup_empty(db_session) -> None:
    report = cleanup(db_session)
    assert report.sessions_expired == 0
    assert report.tokens_revoked_purged == 0
    assert report.audit_events_purged == 0
    assert report.runs_purged == 0
    assert report.tasks_purged == 0


def test_cleanup_purges_expired_sessions(db_session) -> None:
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.add(NiwaSession(token_hash="x" * 64, expires_at=past))
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.add(NiwaSession(token_hash="y" * 64, expires_at=future))
    db_session.commit()

    report = cleanup(db_session)
    assert report.sessions_expired == 1
    remaining = db_session.query(NiwaSession).all()
    assert len(remaining) == 1


def test_cleanup_purges_revoked_tokens(db_session) -> None:
    now = datetime.now(timezone.utc)
    db_session.add(
        ApiToken(name="t1", token_hash="a" * 64, scopes="read", revoked_at=now)
    )
    db_session.add(ApiToken(name="t2", token_hash="b" * 64, scopes="read"))
    db_session.commit()

    report = cleanup(db_session)
    assert report.tokens_revoked_purged == 1
    assert db_session.query(ApiToken).count() == 1


def test_cleanup_purges_old_audit_events(db_session) -> None:
    # Manually insert an old event by setting created_at.
    old = AuditEvent(actor_type="user", action="login.success")
    old.created_at = datetime.now(timezone.utc) - timedelta(days=100)
    db_session.add(old)

    recent = AuditEvent(actor_type="user", action="login.success")
    db_session.add(recent)
    db_session.commit()

    report = cleanup(db_session, audit_days=90)
    assert report.audit_events_purged == 1
    assert db_session.query(AuditEvent).count() == 1


def test_cleanup_dry_run_does_not_delete(db_session) -> None:
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.add(NiwaSession(token_hash="z" * 64, expires_at=past))
    db_session.commit()

    report = cleanup(db_session, dry_run=True)
    assert report.sessions_expired == 1
    assert db_session.query(NiwaSession).count() == 1
