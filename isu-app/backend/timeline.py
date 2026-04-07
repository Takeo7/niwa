"""
Timeline computation for task stage durations.

Provides fetch_task_timelines(task_ids) which computes how long each task
spent in each status, based on task_events rows.

NOTE: To wire this into the Desk server, a route must be added to app.py
(protected file — requires manual intervention):

    if path == '/api/tasks/timelines':
        ids_param = (qs.get('ids') or [''])[0]
        from timeline import fetch_task_timelines
        return self._json(fetch_task_timelines(ids_param, db_conn))
"""

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def fetch_task_timelines(ids_param, db_conn_fn):
    """
    Compute stage durations for the given task IDs.

    Args:
        ids_param: Comma-separated string of task IDs (e.g. "abc,def,ghi")
        db_conn_fn: Callable that returns a sqlite3 connection with row_factory=Row

    Returns:
        dict mapping task_id -> list of timeline segments:
        {
          "task-1": [
            {"status": "pendiente", "duration_minutes": 120, "started_at": "...", "is_current": false},
            {"status": "en_progreso", "duration_minutes": 45, "started_at": "...", "is_current": true},
          ]
        }
    """
    if not ids_param or not ids_param.strip():
        return {}

    raw_ids = [tid.strip() for tid in ids_param.split(',') if tid.strip()]
    if not raw_ids:
        return {}

    placeholders = ','.join('?' for _ in raw_ids)
    query = (
        f"SELECT task_id, type, payload_json, created_at "
        f"FROM task_events "
        f"WHERE task_id IN ({placeholders}) "
        f"AND type IN ('status_changed', 'completed', 'created', 'updated') "
        f"ORDER BY task_id, created_at ASC"
    )

    with db_conn_fn() as conn:
        rows = conn.execute(query, raw_ids).fetchall()

    # Also fetch current status for each task to mark the live segment
    current_status = {}
    with db_conn_fn() as conn:
        status_rows = conn.execute(
            f"SELECT id, status, created_at FROM tasks WHERE id IN ({placeholders})",
            raw_ids,
        ).fetchall()
        for r in status_rows:
            current_status[r['id']] = r['status']

    # Group events by task_id
    events_by_task = {}
    for row in rows:
        tid = row['task_id']
        events_by_task.setdefault(tid, []).append(row)

    now = datetime.now(timezone.utc)
    result = {}

    for tid in raw_ids:
        events = events_by_task.get(tid, [])
        if not events:
            continue

        segments = []
        current_seg_status = None
        current_seg_start = None

        for ev in events:
            ev_time = _parse_dt(ev['created_at'])
            if ev_time is None:
                logger.warning("Skipping event with unparseable timestamp for task %s: %s", tid, ev['created_at'])
                continue
            ev_type = ev['type']
            payload = _parse_payload(ev['payload_json'])

            if ev_type == 'created':
                # Task was created — start in its initial status
                new_status = payload.get('status', 'inbox')
                current_seg_status = new_status
                current_seg_start = ev_time

            elif ev_type in ('status_changed', 'updated'):
                new_status = (
                    payload.get('changes', {}).get('status')
                    or payload.get('new_status')
                    or payload.get('to')
                    or payload.get('status')
                )

                if not new_status:
                    # 'updated' events without a status change are irrelevant
                    continue

                # When task resets to 'pendiente', clear previous segments
                # so the timeline starts fresh from this point
                if new_status == 'pendiente':
                    segments = []

                if current_seg_status and current_seg_start:
                    duration = (ev_time - current_seg_start).total_seconds() / 60.0
                    segments.append({
                        'status': current_seg_status,
                        'duration_minutes': round(duration, 1),
                        'started_at': current_seg_start.isoformat(),
                        'is_current': False,
                    })
                current_seg_status = new_status
                current_seg_start = ev_time

            elif ev_type == 'completed':
                if current_seg_status and current_seg_start:
                    duration = (ev_time - current_seg_start).total_seconds() / 60.0
                    segments.append({
                        'status': current_seg_status,
                        'duration_minutes': round(duration, 1),
                        'started_at': current_seg_start.isoformat(),
                        'is_current': False,
                    })
                current_seg_status = 'hecha'
                current_seg_start = ev_time

        # Close the last open segment
        if current_seg_status and current_seg_start:
            task_cur = current_status.get(tid)
            is_terminal = task_cur in ('hecha', 'archivada')
            duration = (now - current_seg_start).total_seconds() / 60.0
            segments.append({
                'status': current_seg_status,
                'duration_minutes': round(duration, 1),
                'started_at': current_seg_start.isoformat(),
                'is_current': not is_terminal,
            })

        if segments:
            result[tid] = segments

    return result


def _parse_dt(s):
    """Parse an ISO datetime string, tolerating missing timezone. Returns None on failure."""
    if not s:
        return None
    s = s.replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _parse_payload(raw):
    """Safely parse JSON payload."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
