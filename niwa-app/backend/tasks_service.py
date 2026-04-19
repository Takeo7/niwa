"""Task CRUD and query functions extracted from app.py."""
import json
import logging
import os
import uuid
from datetime import datetime, timezone, date
from pathlib import Path

import hosting
from tasks_helpers import (
    load_delegations_index, enrich_tasks_with_agent_info,
    record_task_event, close_parent_if_children_done,
)
from state_machines import assert_task_transition

logger = logging.getLogger(__name__)

# Set by _make_deps() from app.py — must be called before using any function in this module.
# These module-level mutable globals avoid circular imports but make testing harder.
# Consider refactoring to a class or explicit parameter passing if testability becomes a concern.
_db_conn = None
_now_iso = None
_UPLOADS_DIR = None


def _make_deps(db_conn, now_iso, uploads_dir):
    global _db_conn, _now_iso, _UPLOADS_DIR
    _db_conn = db_conn
    _now_iso = now_iso
    _UPLOADS_DIR = uploads_dir


def get_task(task_id):
    with _db_conn() as conn:
        # PR-52: JOIN projects so the detail endpoint also carries
        # project_slug/project_name. ``SELECT *`` isn't enough here
        # because we need columns from a second table.
        # PR-B4b: correlated subqueries expose planner-tier child
        # counts so the UI can render a ``↳ N/M`` badge without a
        # second round-trip. Both counters default to 0 when the
        # task has no children — the UI hides the badge on that.
        row = conn.execute(
            "SELECT t.*, p.slug AS project_slug, p.name AS project_name, "
            "       p.url AS deployment_url, "
            "       (SELECT COUNT(*) FROM tasks c "
            "          WHERE c.parent_task_id = t.id) AS child_count_total, "
            "       (SELECT COUNT(*) FROM tasks c "
            "          WHERE c.parent_task_id = t.id "
            "            AND c.status = 'hecha') AS child_count_done "
            "FROM tasks t LEFT JOIN projects p ON p.id = t.project_id "
            "WHERE t.id=?",
            (task_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        # PR-36: include the latest executor output so the UI can
        # show what Claude actually did. The output is stored in
        # task_events (type='comment', author='executor') by
        # _finish_task in bin/task-executor.py.
        event = conn.execute(
            "SELECT payload_json FROM task_events "
            "WHERE task_id=? AND type='comment' "
            "ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        if event and event['payload_json']:
            try:
                payload = json.loads(event['payload_json'])
                output = payload.get('output', '')
                if output:
                    import re as _re
                    output = _re.sub(
                        r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07'
                        r'|\x1b\[\??[0-9;]*[a-zA-Z]|\x1b[<>][\w]',
                        '', output,
                    ).strip()
                    result['executor_output'] = output
            except (json.JSONDecodeError, KeyError):
                pass
        # PR-39: surface the latest run so the UI can warn when it
        # failed (Feature 4 in docs/BUGS-FOUND.md). Minimal shape for
        # the banner — full run object at /api/tasks/<id>/runs.
        #
        # Snapshots (capability_snapshot_json, budget_snapshot_json,
        # observed_usage_signals_json) are deliberately EXCLUDED —
        # they can carry host paths, env vars, account budget limits
        # or prompt snippets that have no place in the task endpoint.
        # The SELECT below whitelists columns, not ``SELECT *``, so
        # a schema addition can't silently leak.
        #
        # backend_profile_slug comes via LEFT JOIN so the banner can
        # say "Claude Sonnet failed with auth_required" instead of
        # just the opaque error_code.
        run_row = conn.execute(
            "SELECT br.id, br.status, br.outcome, br.error_code, "
            "       br.finished_at, br.relation_type, "
            "       bp.slug AS backend_profile_slug, "
            "       bp.display_name AS backend_profile_display_name "
            "FROM backend_runs br "
            "LEFT JOIN backend_profiles bp "
            "       ON bp.id = br.backend_profile_id "
            "WHERE br.task_id=? "
            "ORDER BY br.created_at DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        if run_row:
            result['last_run'] = {
                'id': run_row['id'],
                'status': run_row['status'],
                'outcome': run_row['outcome'],
                'error_code': run_row['error_code'],
                'finished_at': run_row['finished_at'],
                'relation_type': run_row['relation_type'],
                'backend_profile_slug': run_row['backend_profile_slug'],
                'backend_profile_display_name':
                    run_row['backend_profile_display_name'],
            }
        else:
            result['last_run'] = None
        return result


def fetch_tasks(area=None, status=None, today_only=False, include_done=False, project_id=None):
    # PR-52: expose project_slug so the UI can link from task → project
    # without a second round-trip. project_name was already exposed.
    # PR-B4b: correlated subqueries for planner-tier child counters.
    # With ``LIMIT 500`` and the usual tasks table size the O(N) cost
    # is immaterial; if this ever shows up in profiling, swap for a
    # ``LEFT JOIN (SELECT parent_task_id, ...)`` aggregate.
    query = (
        "SELECT t.*, p.name as project_name, p.slug as project_slug, "
        "       (SELECT COUNT(*) FROM tasks c "
        "          WHERE c.parent_task_id = t.id) AS child_count_total, "
        "       (SELECT COUNT(*) FROM tasks c "
        "          WHERE c.parent_task_id = t.id "
        "            AND c.status = 'hecha') AS child_count_done "
        "FROM tasks t LEFT JOIN projects p ON p.id=t.project_id "
        "WHERE t.source != 'chat'"
    )
    params = []
    if project_id:
        query += ' AND t.project_id=?'
        params.append(project_id)
    if area:
        query += ' AND t.area=?'
        params.append(area)
    if status:
        query += ' AND t.status=?'
        params.append(status)
    if not include_done and not status:
        query += ' AND t.status NOT IN ("hecha","archivada")'
    if today_only:
        query += ' AND (t.urgent=1 OR t.scheduled_for=? OR (t.due_at IS NOT NULL AND date(t.due_at)<=date(?)))'
        params.extend([date.today().isoformat(), date.today().isoformat()])
    query += ' ORDER BY t.urgent DESC, CASE t.priority WHEN "critica" THEN 4 WHEN "alta" THEN 3 WHEN "media" THEN 2 ELSE 1 END DESC, COALESCE(t.due_at, t.scheduled_for, t.created_at) ASC LIMIT 500'
    with _db_conn() as conn:
        tasks = [dict(r) for r in conn.execute(query, params).fetchall()]
    return enrich_tasks_with_agent_info(tasks)


def create_task(payload):
    task_id = str(uuid.uuid4())
    ts = _now_iso()
    # Normalize fields that have a CHECK constraint in schema.sql.  The UI
    # sends empty strings for unset selects (e.g. the area dropdown in
    # TaskForm when the user doesn't pick one) which would otherwise
    # violate the CHECK and blow up mid-INSERT — the ThreadingHTTPServer
    # then closes the socket and the browser surfaces it as a cryptic
    # "network lost" rather than a clean 4xx.  Coerce empty/None to the
    # schema defaults so the INSERT always lands on a valid value.
    area = (payload.get('area') or 'proyecto').strip() or 'proyecto'
    status = (payload.get('status') or 'pendiente').strip() or 'pendiente'
    priority = (payload.get('priority') or 'media').strip() or 'media'
    title = (payload.get('title') or '').strip() or 'Nueva tarea'
    # PR-B4b: accept ``decompose`` so the TaskForm checkbox opts the
    # task into the planner tier at creation time. Anything truthy
    # coerces to 1; absent / falsy keeps the schema default of 0.
    decompose = 1 if payload.get('decompose') else 0
    with _db_conn() as conn:
        conn.execute(
            'INSERT INTO tasks (id,title,description,area,project_id,status,priority,urgent,scheduled_for,due_at,source,notes,assigned_to_yume,assigned_to_claude,parent_task_id,decompose,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (
                task_id,
                title,
                payload.get('description', ''),
                area,
                payload.get('project_id') or None,
                status,
                priority,
                1 if payload.get('urgent') else 0,
                payload.get('scheduled_for') or None,
                payload.get('due_at') or None,
                'niwa-app',
                payload.get('notes', ''),
                1 if payload.get('assigned_to_yume') else 0,
                1 if payload.get('assigned_to_claude') else 0,
                payload.get('parent_task_id') or None,  # PR-55
                decompose,
                ts,
                ts,
            ),
        )
        conn.commit()
    return task_id


def update_task(task_id, payload):
    allowed = {'status', 'urgent', 'priority', 'scheduled_for', 'due_at', 'notes', 'title', 'description', 'area', 'project_id', 'parent_task_id', 'assigned_to_yume', 'assigned_to_claude'}
    sets, params = [], []
    status_value = payload.get('status') if 'status' in payload else None
    for k, v in payload.items():
        if k in allowed:
            if k in ('urgent', 'assigned_to_yume', 'assigned_to_claude'):
                v = 1 if v else 0
            sets.append(f'{k}=?')
            params.append(v)
    if status_value:
        sets.append('completed_at=?')
        params.append(_now_iso() if status_value == 'hecha' else None)
    if not sets:
        return
    current_task = get_task(task_id)
    if not current_task:
        raise ValueError('task_not_found')
    if status_value:
        assert_task_transition(current_task['status'], status_value)
    merged_task = dict(current_task)
    merged_task.update({k: payload.get(k) for k in allowed if k in payload})
    updated_at = _now_iso()
    sets.append('updated_at=?')
    params.append(updated_at)
    params.append(task_id)
    delegation_by_task = load_delegations_index()
    active_agent = delegation_by_task.get(task_id) or {}
    event_payload = {
        'changes': {k: payload.get(k) for k in allowed if k in payload},
        'agent_id': active_agent.get('agent_id') or '',
        'agent_name': active_agent.get('agent_name') or '',
        'agent_status': active_agent.get('status') or '',
    }
    parent_id = current_task.get('parent_task_id')
    with _db_conn() as conn:
        conn.execute(f'UPDATE tasks SET {", ".join(sets)} WHERE id=?', params)
        record_task_event(conn, task_id, 'completed' if status_value == 'hecha' else 'updated', event_payload)
        # PR-B4b: when a child finishes, close the parent if this was
        # the last open sibling. Runs inside the same transaction so
        # the child's hecha row and the parent's closure commit
        # atomically; callers always see a consistent pair.
        if status_value == 'hecha' and parent_id:
            close_parent_if_children_done(conn, parent_id, _now_iso())
        conn.commit()
    # PR-C1: auto-deploy once the transition is durable. The hook runs
    # OUTSIDE the write transaction so deploy's own DB work (Caddy
    # config, deployments table) can't deadlock against the tasks
    # update, and so that a deploy failure can't roll back the status
    # change we already committed above.
    if status_value == 'hecha' and current_task.get('project_id'):
        _maybe_autodeploy(task_id, current_task['project_id'])


def _autodeploy_enabled() -> bool:
    """Env-gated kill switch for the auto-deploy hook.

    Default is ON (matches the v1 MVP happy-path). Accepts the usual
    falsey spellings so an operator can disable it without touching
    code during an incident."""
    raw = os.environ.get('NIWA_DEPLOY_ON_TASK_SUCCESS', '').strip().lower()
    return raw not in {'0', 'false', 'no'}


def _maybe_autodeploy(task_id: str, project_id: str) -> None:
    """Best-effort deploy-on-completion. Swallows and records failures
    so a broken hosting layer never rolls back a legitimate status
    transition. The timeline surfaces the error for the operator."""
    if not _autodeploy_enabled():
        return
    try:
        hosting.deploy_project(project_id)
    except Exception as exc:
        logger.exception(
            'auto-deploy failed for task=%s project=%s', task_id, project_id,
        )
        try:
            with _db_conn() as conn:
                record_task_event(conn, task_id, 'alerted', {
                    'source': 'autodeploy',
                    'project_id': project_id,
                    'error': str(exc),
                })
                conn.commit()
        except Exception:
            logger.exception(
                'failed to record autodeploy alert for task=%s', task_id,
            )


def delete_task(task_id):
    with _db_conn() as conn:
        conn.execute('DELETE FROM tasks WHERE id=?', (task_id,))
        conn.commit()


def fetch_task_timelines(task_ids):
    if not task_ids:
        return {}
    placeholders = ','.join('?' * len(task_ids))
    with _db_conn() as conn:
        rows = conn.execute(
            f'SELECT task_id, type, payload_json, created_at FROM task_events WHERE task_id IN ({placeholders}) ORDER BY created_at',
            task_ids
        ).fetchall()
    result = {tid: [] for tid in task_ids}
    for r in rows:
        try:
            payload = json.loads(r['payload_json'] or '{}')
        except Exception:
            payload = {}
        result[r['task_id']].append({
            'type': r['type'], 'payload': payload, 'at': r['created_at'],
        })
    return result


def fetch_task_pipeline(task_id):
    """Return pipeline steps for a task from task_metrics + notes."""
    PHASE_ORDER = ['triage', 'execute', 'review', 'deploy', 'verify', 'visual', 'coverage']
    PHASE_LABELS = {'triage': 'Triage', 'execute': 'Ejecución', 'review': 'Revisión',
                    'deploy': 'Deploy', 'verify': 'Verificación', 'visual': 'Visual Check', 'coverage': 'Coverage'}
    result = {'task_id': task_id, 'steps': [], 'summary': {}}
    with _db_conn() as conn:
        metrics = conn.execute(
            "SELECT phase, success, duration_seconds, error_message, timestamp "
            "FROM task_metrics WHERE task_id=? ORDER BY timestamp", (task_id,)
        ).fetchall()
        task = conn.execute("SELECT status, notes, created_at, completed_at FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            return {'error': 'not_found'}
        seen_phases = set()
        for m in metrics:
            phase = m['phase']
            seen_phases.add(phase)
            result['steps'].append({
                'phase': phase,
                'label': PHASE_LABELS.get(phase, phase),
                'success': bool(m['success']),
                'duration_s': round(m['duration_seconds'], 1),
                'error': (m['error_message'] or '')[:200] if not m['success'] else '',
                'timestamp': m['timestamp'],
            })
        for phase in PHASE_ORDER:
            if phase not in seen_phases:
                result['steps'].append({
                    'phase': phase,
                    'label': PHASE_LABELS.get(phase, phase),
                    'success': None,
                    'duration_s': 0,
                    'error': '',
                    'timestamp': '',
                })
        total_duration = sum(m['duration_seconds'] for m in metrics)
        success_count = sum(1 for m in metrics if m['success'])
        fail_count = sum(1 for m in metrics if not m['success'])
        result['summary'] = {
            'status': task['status'],
            'total_duration_s': round(total_duration, 1),
            'steps_passed': success_count,
            'steps_failed': fail_count,
            'created_at': task['created_at'],
            'completed_at': task['completed_at'],
        }
    return result


def fetch_task_labels(task_id):
    with _db_conn() as conn:
        rows = conn.execute("SELECT label FROM task_labels WHERE task_id=?", (task_id,)).fetchall()
        return [r['label'] for r in rows]


def add_task_label(task_id, label):
    with _db_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO task_labels (task_id, label) VALUES (?, ?)", (task_id, label))
        conn.commit()


def remove_task_label(task_id, label):
    with _db_conn() as conn:
        conn.execute("DELETE FROM task_labels WHERE task_id=? AND label=?", (task_id, label))
        conn.commit()


def fetch_task_attachments(task_id):
    task_dir = _UPLOADS_DIR / task_id
    if not task_dir.exists():
        return []
    items = []
    for f in sorted(task_dir.iterdir()):
        if f.is_file():
            items.append({
                'filename': f.name,
                'size': f.stat().st_size,
                'uploaded_at': datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat(),
            })
    return items


def save_task_attachment(task_id, filename, data):
    task_dir = _UPLOADS_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    (task_dir / safe_name).write_bytes(data)
    return safe_name


def delete_task_attachment(task_id, filename):
    safe_name = Path(filename).name
    target = _UPLOADS_DIR / task_id / safe_name
    if target.exists():
        target.unlink()
        return True
    return False
