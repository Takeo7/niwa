"""Task helper functions: delegations, agent enrichment, event recording."""
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Set by _make_deps() from app.py
_db_conn = None
_now_iso = None
_WORKSPACE_DELEGATIONS_PATH = None


def _make_deps(db_conn, now_iso, workspace_delegations_path):
    global _db_conn, _now_iso, _WORKSPACE_DELEGATIONS_PATH
    _db_conn = db_conn
    _now_iso = now_iso
    _WORKSPACE_DELEGATIONS_PATH = workspace_delegations_path


def _extract_task_id(text: str) -> str | None:
    if not text:
        return None
    match = re.search(r'task\s+([0-9a-fA-F-]{36})', text, re.IGNORECASE)
    return match.group(1) if match else None


def load_delegations_index():
    if not _WORKSPACE_DELEGATIONS_PATH.exists():
        return {}
    try:
        data = json.loads(_WORKSPACE_DELEGATIONS_PATH.read_text(encoding='utf-8'))
        delegations = data.get('delegations', []) if isinstance(data, dict) else []
    except Exception:
        logger.warning("load_delegations_index: failed to read delegations file", exc_info=True)
        return {}
    by_task = {}
    for item in delegations:
        if not isinstance(item, dict):
            continue
        task_ref = _extract_task_id(item.get('task') or item.get('current_task') or item.get('description') or '')
        if not task_ref:
            continue
        agent = item.get('assigned_to') or item.get('assignee') or item.get('agent') or ''
        current = by_task.get(task_ref)
        item_ts = item.get('updated_at') or item.get('started_at') or item.get('created_at') or ''
        current_ts = (current or {}).get('updated_at') or (current or {}).get('started_at') or (current or {}).get('created_at') or ''
        if current is None or item_ts >= current_ts:
            by_task[task_ref] = {
                'agent_id': agent.lower() if isinstance(agent, str) else '',
                'agent_name': agent,
                'status': item.get('status') or '',
                'updated_at': item.get('updated_at') or item.get('started_at') or item.get('created_at') or '',
                'task': item.get('task') or item.get('current_task') or '',
            }
    return by_task


def fetch_task_agent_history(conn, task_id):
    rows = conn.execute(
        "SELECT type, payload_json, created_at FROM task_events WHERE task_id=? AND type IN ('updated','completed','status_changed') ORDER BY created_at DESC",
        (task_id,),
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row['payload_json'] or '{}')
        except Exception:
            logger.warning("fetch_task_agent_history: invalid JSON in payload_json for task %s", task_id, exc_info=True)
            payload = {}
        agent_id = payload.get('agent_id') or ''
        agent_name = payload.get('agent_name') or agent_id
        if agent_id or agent_name:
            return {
                'agent_id': agent_id,
                'agent_name': agent_name,
                'event_type': row['type'],
                'recorded_at': row['created_at'],
            }
    return None


def enrich_tasks_with_agent_info(tasks):
    delegation_by_task = load_delegations_index()
    if not tasks:
        return tasks
    with _db_conn() as conn:
        for task in tasks:
            task['active_agent'] = None
            task['completed_by_agent'] = None
            active = delegation_by_task.get(task.get('id'))
            if active and (active.get('agent_id') or active.get('agent_name')):
                task['active_agent'] = active
            history = fetch_task_agent_history(conn, task.get('id'))
            if history:
                task['completed_by_agent'] = history
    return tasks


def record_task_event(conn, task_id, event_type, payload):
    conn.execute(
        'INSERT INTO task_events (id, task_id, type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)',
        (str(uuid.uuid4()), task_id, event_type, json.dumps(payload, ensure_ascii=False), _now_iso()),
    )


