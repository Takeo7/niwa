"""Task history module — query completed/archived tasks with filtering, pagination, and stats.

Provides fetch_task_history(params, db_conn_fn) for retrieving historical task data
with optional filters, sorting, and aggregate statistics.

NOTE: To wire this into the Desk server, add a route in app.py
(protected file — requires manual intervention):

    if path == '/api/tasks/history':
        from history import fetch_task_history
        params = {
            'project_id': (qs.get('project_id') or [None])[0],
            'from': (qs.get('from') or [None])[0],
            'to': (qs.get('to') or [None])[0],
            'source': (qs.get('source') or [None])[0],
            'search': (qs.get('search') or [None])[0],
            'page': int((qs.get('page') or ['1'])[0]),
            'limit': int((qs.get('limit') or ['20'])[0]),
            'sort': (qs.get('sort') or ['completed_at'])[0],
            'order': (qs.get('order') or ['desc'])[0],
        }
        return self._json(fetch_task_history(params, lambda: _db_conn()))
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get('DESK_DB_PATH', str(BASE_DIR / 'data' / 'desk.sqlite3')))

ALLOWED_SORT = {'completed_at', 'created_at', 'title', 'duration_hours'}
ALLOWED_ORDER = {'asc', 'desc'}


def _db_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _parse_iso(s):
    """Parse ISO-8601 timestamp to datetime (handles Z and +00:00)."""
    if not s:
        return None
    s = s.replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _duration_hours(created_at, completed_at):
    """Compute hours between created_at and completed_at ISO strings."""
    start = _parse_iso(created_at)
    end = _parse_iso(completed_at)
    if not start or not end:
        return None
    # Normalize both to UTC-aware or both naive
    if start.tzinfo and not end.tzinfo:
        end = end.replace(tzinfo=timezone.utc)
    elif end.tzinfo and not start.tzinfo:
        start = start.replace(tzinfo=timezone.utc)
    delta = (end - start).total_seconds() / 3600.0
    return round(delta, 2) if delta >= 0 else None


def fetch_task_history(params, db_conn_fn=None):
    """Query completed/archived tasks with filters, pagination, and stats.

    Args:
        params: dict with optional keys:
            project_id  — filter by project
            from        — completed_at >= this ISO date
            to          — completed_at <= this ISO date
            source      — exact match on tasks.source
            search      — LIKE match on title or description
            page        — page number (1-based, default 1)
            limit       — items per page (default 20, max 100)
            sort        — column to sort by (completed_at|created_at|title|duration_hours)
            order       — asc or desc (default desc)
        db_conn_fn: callable returning a sqlite3 connection with row_factory=Row

    Returns:
        {
          "items": [...],
          "total": 42,
          "page": 1,
          "stats": {
            "total_completed": 42,
            "first_time_success_rate": 0.76,
            "avg_pipeline_hours": 12.5,
            "most_active_project": "Desk"
          }
        }
    """
    conn_fn = db_conn_fn or _db_conn

    project_id = params.get('project_id')
    date_from = params.get('from')
    date_to = params.get('to')
    source = params.get('source')
    search = params.get('search')
    page = max(1, int(params.get('page') or 1))
    limit = min(100, max(1, int(params.get('limit') or 20)))
    sort = params.get('sort', 'completed_at')
    order = params.get('order', 'desc')

    if sort not in ALLOWED_SORT:
        sort = 'completed_at'
    if order not in ALLOWED_ORDER:
        order = 'desc'

    # Build WHERE clauses and bind values
    where = ["t.status IN ('hecha', 'archivada')"]
    bind = []

    if project_id:
        where.append("t.project_id = ?")
        bind.append(project_id)
    if date_from:
        where.append("t.completed_at >= ?")
        bind.append(date_from)
    if date_to:
        where.append("t.completed_at <= ?")
        bind.append(date_to)
    if source:
        where.append("t.source = ?")
        bind.append(source)
    if search:
        where.append("(t.title LIKE ? OR t.description LIKE ?)")
        pattern = f"%{search}%"
        bind.extend([pattern, pattern])

    where_sql = " AND ".join(where)

    with conn_fn() as conn:
        # Total count for pagination
        count_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM tasks t WHERE {where_sql}", bind
        ).fetchone()
        total = count_row['cnt'] if count_row else 0

        # Fetch paginated items with project name and event counts
        # duration_hours is computed in Python; sort by it requires post-processing
        sort_by_duration = sort == 'duration_hours'
        sql_sort = 'completed_at' if sort_by_duration else sort
        order_sql = order.upper()

        # Subquery for attempt count (status_changed events) and review count per task
        items_sql = f"""
            SELECT t.id, t.title, t.description, t.status, t.priority,
                   t.source, t.created_at, t.completed_at, t.project_id,
                   COALESCE(p.name, 'Sin proyecto') AS project_name,
                   (SELECT COUNT(*) FROM task_events e
                    WHERE e.task_id = t.id AND e.type = 'status_changed') AS attempts,
                   (SELECT COUNT(*) FROM task_events e
                    WHERE e.task_id = t.id AND e.type = 'status_changed'
                    AND e.payload_json LIKE '%revision%') AS reviews
            FROM tasks t
            LEFT JOIN projects p ON t.project_id = p.id
            WHERE {where_sql}
            ORDER BY t.{sql_sort} {order_sql}
        """

        if not sort_by_duration:
            items_sql += f" LIMIT ? OFFSET ?"
            items_bind = bind + [limit, (page - 1) * limit]
        else:
            items_bind = bind

        rows = conn.execute(items_sql, items_bind).fetchall()

        items = []
        for r in rows:
            duration = _duration_hours(r['created_at'], r['completed_at'])
            items.append({
                'id': r['id'],
                'title': r['title'],
                'description': r['description'],
                'status': r['status'],
                'priority': r['priority'],
                'source': r['source'],
                'project_id': r['project_id'],
                'project_name': r['project_name'],
                'created_at': r['created_at'],
                'completed_at': r['completed_at'],
                'duration_hours': duration,
                'attempts': r['attempts'],
                'reviews': r['reviews'],
            })

        # If sorting by duration_hours, sort in Python and paginate
        if sort_by_duration:
            reverse = order == 'desc'
            items.sort(key=lambda x: x['duration_hours'] or 0, reverse=reverse)
            start = (page - 1) * limit
            items = items[start:start + limit]

        # Stats over the full filtered set (not just current page)
        stats = _compute_stats(conn, where_sql, bind)

    return {
        'items': items,
        'total': total,
        'page': page,
        'stats': stats,
    }


def _compute_stats(conn, where_sql, bind):
    """Compute aggregate stats over the full filtered task set."""
    # Total completed
    row = conn.execute(
        f"SELECT COUNT(*) as cnt FROM tasks t WHERE {where_sql}", bind
    ).fetchone()
    total_completed = row['cnt'] if row else 0

    if total_completed == 0:
        return {
            'total_completed': 0, 'first_time_success_rate': 0,
            'avg_pipeline_hours': 0, 'most_active_project': None,
            'total': 0, 'success': 0, 'failed': 0, 'avg_duration': 0,
        }

    # Avg pipeline hours: avg(completed_at - created_at) using julianday
    avg_row = conn.execute(f"""
        SELECT AVG(
            (julianday(t.completed_at) - julianday(t.created_at)) * 24
        ) as avg_hours
        FROM tasks t
        WHERE {where_sql} AND t.completed_at IS NOT NULL AND t.created_at IS NOT NULL
    """, bind).fetchone()
    avg_pipeline_hours = round(avg_row['avg_hours'], 2) if avg_row and avg_row['avg_hours'] else 0

    # First-time success rate: tasks that went to 'hecha' without being
    # sent back to 'pendiente' (i.e. no status_changed event resetting them)
    # A task is first-time success if it has <= 1 status_changed event to 'hecha'/'revision'
    # and no event sending it back to 'pendiente' after being in progress
    reset_count_row = conn.execute(f"""
        SELECT COUNT(DISTINCT t.id) as reset_cnt
        FROM tasks t
        JOIN task_events e ON e.task_id = t.id
        WHERE {where_sql}
          AND e.type = 'status_changed'
          AND e.payload_json LIKE '%pendiente%'
          AND e.created_at > (
              SELECT MIN(e2.created_at) FROM task_events e2
              WHERE e2.task_id = t.id AND e2.type = 'status_changed'
          )
    """, bind).fetchone()
    reset_count = reset_count_row['reset_cnt'] if reset_count_row else 0
    first_time_success_rate = round((total_completed - reset_count) / total_completed, 2)

    # Most active project
    proj_row = conn.execute(f"""
        SELECT COALESCE(p.name, 'Sin proyecto') as project_name, COUNT(*) as cnt
        FROM tasks t
        LEFT JOIN projects p ON t.project_id = p.id
        WHERE {where_sql}
        GROUP BY COALESCE(p.name, 'Sin proyecto')
        ORDER BY cnt DESC
        LIMIT 1
    """, bind).fetchone()
    most_active_project = proj_row['project_name'] if proj_row else None

    _success_count = total_completed - reset_count if total_completed > reset_count else total_completed
    _failed_count = reset_count
    _avg_dur_min = round(avg_pipeline_hours * 60, 1)

    return {
        'total_completed': total_completed,
        'first_time_success_rate': first_time_success_rate,
        'avg_pipeline_hours': avg_pipeline_hours,
        'most_active_project': most_active_project,
        # Keys the frontend expects
        'total': total_completed,
        'success': _success_count,
        'failed': _failed_count,
        'avg_duration': _avg_dur_min,
    }
