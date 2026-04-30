"""Cleanup service — purge old records for retention (Phase 8, QA-09)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import Run, Task
from ..models.api_token import ApiToken
from ..models.audit_event import AuditEvent
from ..models.niwa_session import NiwaSession


@dataclass
class CleanupReport:
    sessions_expired: int
    tokens_revoked_purged: int
    audit_events_purged: int
    runs_purged: int
    tasks_purged: int


def cleanup(
    db: Session,
    *,
    audit_days: int = 90,
    runs_days: int = 30,
    tasks_days: int = 30,
    dry_run: bool = False,
) -> CleanupReport:
    """Delete records older than thresholds.

    Tasks are only purged if their status is in {done, failed, cancelled}.
    """
    now = datetime.now(timezone.utc)

    sessions_q = db.query(NiwaSession).filter(NiwaSession.expires_at < now)
    sessions_count = sessions_q.count()

    tokens_q = db.query(ApiToken).filter(ApiToken.revoked_at.is_not(None))
    tokens_count = tokens_q.count()

    audit_cutoff = now - timedelta(days=audit_days)
    audit_q = db.query(AuditEvent).filter(AuditEvent.created_at < audit_cutoff)
    audit_count = audit_q.count()

    runs_cutoff = now - timedelta(days=runs_days)
    runs_q = db.query(Run).filter(
        Run.finished_at.is_not(None), Run.finished_at < runs_cutoff
    )
    runs_count = runs_q.count()

    tasks_cutoff = now - timedelta(days=tasks_days)
    tasks_q = db.query(Task).filter(
        Task.status.in_(("done", "failed", "cancelled")),
        Task.updated_at < tasks_cutoff,
    )
    tasks_count = tasks_q.count()

    if not dry_run:
        sessions_q.delete(synchronize_session=False)
        tokens_q.delete(synchronize_session=False)
        audit_q.delete(synchronize_session=False)
        runs_q.delete(synchronize_session=False)
        tasks_q.delete(synchronize_session=False)
        db.commit()

    return CleanupReport(
        sessions_expired=sessions_count,
        tokens_revoked_purged=tokens_count,
        audit_events_purged=audit_count,
        runs_purged=runs_count,
        tasks_purged=tasks_count,
    )
