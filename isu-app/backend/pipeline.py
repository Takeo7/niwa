"""Pipeline / bottleneck analytics for Desk dashboard.

Exports `fetch_pipeline_data(days=7)` which returns aggregated
stage-duration metrics derived from task_events.

To wire into app.py, add:
    from pipeline import fetch_pipeline_data
and a route:
    if path == '/api/dashboard/pipeline':
        days = int(qs.get('days', ['7'])[0])
        return self._json(fetch_pipeline_data(days))
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get('DESK_DB_PATH', str(BASE_DIR / 'data' / 'desk.sqlite3')))

# Ordered pipeline stages — these mirror task status flow
STAGES = ['pendiente', 'en_progreso', 'revision', 'hecha']
STAGE_LABELS = {
    'pendiente': 'Queue',
    'en_progreso': 'Execution',
    'revision': 'Review',
    'hecha': 'Done',
}


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


def _compute_stage_durations(events):
    """Given a chronologically-sorted list of events for one task,
    return dict {stage: minutes} for time spent in each pipeline stage."""
    durations = {}
    current_status = None
    entered_at = None

    for ev in events:
        ev_type = ev['type']
        created = _parse_iso(ev['created_at'])
        if created is None:
            continue

        if ev_type == 'created':
            # Task was created — assume it enters 'pendiente' (or inbox)
            payload = {}
            if ev['payload_json']:
                try:
                    payload = json.loads(ev['payload_json'])
                except (json.JSONDecodeError, TypeError):
                    pass
            current_status = payload.get('status', 'pendiente')
            entered_at = created

        elif ev_type == 'status_changed':
            payload = {}
            if ev['payload_json']:
                try:
                    payload = json.loads(ev['payload_json'])
                except (json.JSONDecodeError, TypeError):
                    pass
            new_status = payload.get('new_status') or payload.get('to') or payload.get('status')
            if not new_status:
                continue

            # Close previous stage
            if current_status and entered_at and current_status in STAGES:
                delta = (created - entered_at).total_seconds() / 60.0
                if delta >= 0:
                    durations[current_status] = durations.get(current_status, 0) + delta

            current_status = new_status
            entered_at = created

        elif ev_type == 'completed':
            # Close current stage at completion time
            if current_status and entered_at and current_status in STAGES:
                delta = (created - entered_at).total_seconds() / 60.0
                if delta >= 0:
                    durations[current_status] = durations.get(current_status, 0) + delta
            # Mark final transition to 'hecha' if not already
            current_status = 'hecha'
            entered_at = created

    return durations


def fetch_pipeline_data(days=7):
    """Aggregate pipeline stage durations for completed tasks.

    Returns:
        {
            "days": 7,
            "task_count": 12,
            "avg_total_min": 480.5,
            "avg_queue_min": 120.3,
            "avg_execution_min": 200.1,
            "avg_review_min": 60.0,
            "bottleneck": "en_progreso",
            "stages": [
                {"key": "pendiente", "label": "Queue", "avg_min": 120.3, "pct": 25.0},
                ...
            ],
            "by_project": {
                "Desk": {"task_count": 5, "avg_total_min": ..., "stages": [...]},
                ...
            }
        }
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    conn = _db_conn()
    try:
        # Get completed tasks within the window
        rows = conn.execute('''
            SELECT t.id, t.title, COALESCE(p.name, 'Sin proyecto') as project_name
            FROM tasks t
            LEFT JOIN projects p ON t.project_id = p.id
            WHERE t.status IN ('hecha', 'archivada')
              AND t.completed_at IS NOT NULL
              AND t.completed_at >= ?
            ORDER BY t.completed_at DESC
        ''', (cutoff,)).fetchall()

        if not rows:
            return {
                'days': days,
                'task_count': 0,
                'avg_total_min': 0,
                'avg_queue_min': 0,
                'avg_execution_min': 0,
                'avg_review_min': 0,
                'bottleneck': None,
                'stages': [{'key': s, 'label': STAGE_LABELS[s], 'avg_min': 0, 'pct': 0} for s in STAGES],
                'by_project': {},
            }

        task_ids = [r['id'] for r in rows]
        task_projects = {r['id']: r['project_name'] for r in rows}

        # Fetch all events for these tasks
        placeholders = ','.join('?' * len(task_ids))
        events = conn.execute(f'''
            SELECT task_id, type, payload_json, created_at
            FROM task_events
            WHERE task_id IN ({placeholders})
              AND type IN ('created', 'status_changed', 'completed', 'updated')
            ORDER BY created_at ASC
        ''', task_ids).fetchall()

        # Group events by task
        events_by_task = {}
        for ev in events:
            tid = ev['task_id']
            if tid not in events_by_task:
                events_by_task[tid] = []
            events_by_task[tid].append(ev)

        # Compute durations per task
        all_durations = []  # list of {project, durations}
        for tid in task_ids:
            task_events = events_by_task.get(tid, [])
            if not task_events:
                continue
            durations = _compute_stage_durations(task_events)
            if durations:
                all_durations.append({
                    'project': task_projects.get(tid, 'Sin proyecto'),
                    'durations': durations,
                })

        if not all_durations:
            return {
                'days': days,
                'task_count': len(task_ids),
                'avg_total_min': 0,
                'avg_queue_min': 0,
                'avg_execution_min': 0,
                'avg_review_min': 0,
                'bottleneck': None,
                'stages': [{'key': s, 'label': STAGE_LABELS[s], 'avg_min': 0, 'pct': 0} for s in STAGES],
                'by_project': {},
            }

        # Aggregate globally
        def _avg_stage(items, stage):
            vals = [d['durations'].get(stage, 0) for d in items]
            return round(sum(vals) / len(vals), 1) if vals else 0

        n = len(all_durations)
        stage_avgs = {s: _avg_stage(all_durations, s) for s in STAGES}
        total_avg = round(sum(stage_avgs.values()), 1)

        # Bottleneck = stage with highest avg time (excluding 'hecha')
        pipeline_stages = [s for s in STAGES if s != 'hecha']
        bottleneck = max(pipeline_stages, key=lambda s: stage_avgs.get(s, 0)) if pipeline_stages else None

        # Percentages
        stages_out = []
        for s in STAGES:
            pct = round(stage_avgs[s] / total_avg * 100, 1) if total_avg > 0 else 0
            stages_out.append({
                'key': s,
                'label': STAGE_LABELS[s],
                'avg_min': stage_avgs[s],
                'pct': pct,
            })

        # By project
        projects_map = {}
        for d in all_durations:
            proj = d['project']
            if proj not in projects_map:
                projects_map[proj] = []
            projects_map[proj].append(d)

        by_project = {}
        for proj, items in projects_map.items():
            p_stage_avgs = {s: _avg_stage(items, s) for s in STAGES}
            p_total = round(sum(p_stage_avgs.values()), 1)
            p_stages = []
            for s in STAGES:
                pct = round(p_stage_avgs[s] / p_total * 100, 1) if p_total > 0 else 0
                p_stages.append({
                    'key': s,
                    'label': STAGE_LABELS[s],
                    'avg_min': p_stage_avgs[s],
                    'pct': pct,
                })
            by_project[proj] = {
                'task_count': len(items),
                'avg_total_min': p_total,
                'stages': p_stages,
            }

        return {
            'days': days,
            'task_count': n,
            'avg_total_min': total_avg,
            'avg_queue_min': stage_avgs.get('pendiente', 0),
            'avg_execution_min': stage_avgs.get('en_progreso', 0),
            'avg_review_min': stage_avgs.get('revision', 0),
            'bottleneck': bottleneck,
            'stages': stages_out,
            'by_project': by_project,
        }
    finally:
        conn.close()
