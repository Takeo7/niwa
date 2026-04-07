#!/usr/bin/env python3
"""
Stats and enhanced project queries for Desk.

Provides fetch_stats() and fetch_projects_extended() that can be used
by the API layer or called standalone for diagnostics.
"""
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get('DESK_DB_PATH', str(BASE_DIR / 'data' / 'desk.sqlite3')))


def _db_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def fetch_stats():
    """Return aggregate task statistics including completions by day (last 14 days)."""
    with _db_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM tasks WHERE status NOT IN ('hecha','archivada')").fetchone()[0]
        done = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='hecha'").fetchone()[0]
        by_status = {}
        for row in conn.execute("SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status").fetchall():
            by_status[row['status']] = row['cnt']
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).replace(microsecond=0).isoformat()
        completions = conn.execute(
            "SELECT date(completed_at) as day, COUNT(*) as cnt FROM tasks WHERE completed_at >= ? GROUP BY date(completed_at) ORDER BY day",
            (cutoff,),
        ).fetchall()
        completions_by_day = [{'day': r['day'], 'count': r['cnt']} for r in completions]
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        overdue = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE due_at < ? AND status NOT IN ('hecha','archivada')",
            (today,),
        ).fetchone()[0]
        done_today = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status='hecha' AND date(completed_at)=?",
            (today,),
        ).fetchone()[0]
    return {'open': total, 'done': done, 'overdue': overdue, 'done_today': done_today, 'by_status': by_status, 'completions_by_day': completions_by_day}


def fetch_projects_extended():
    """Return active projects with open_tasks, done_tasks, and total_tasks counts."""
    with _db_conn() as conn:
        rows = conn.execute(
            '''SELECT p.*,
                      COUNT(CASE WHEN t.status NOT IN ('hecha','archivada') THEN 1 END) as open_tasks,
                      COUNT(CASE WHEN t.status = 'hecha' THEN 1 END) as done_tasks,
                      COUNT(t.id) as total_tasks
               FROM projects p LEFT JOIN tasks t ON t.project_id=p.id
               WHERE p.active=1 GROUP BY p.id ORDER BY p.name ASC'''
        ).fetchall()
        return [dict(r) for r in rows]


if __name__ == '__main__':
    import json
    print('=== Stats ===')
    print(json.dumps(fetch_stats(), indent=2))
    print('\n=== Projects (extended) ===')
    print(json.dumps(fetch_projects_extended(), indent=2))
