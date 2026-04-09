#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone, date, timedelta

logger = logging.getLogger(__name__)
import tasks_helpers
import tasks_service
import health_service
import scheduler
import notifier

_scheduler: scheduler.SchedulerThread | None = None
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get('NIWA_DB_PATH', str(BASE_DIR / 'data' / 'niwa.sqlite3')))
SCHEMA_PATH = BASE_DIR / 'db' / 'schema.sql'
HOST = os.environ.get('NIWA_APP_HOST', '0.0.0.0')
PORT = int(os.environ.get('NIWA_APP_PORT', '8080'))
NIWA_APP_USERNAME = os.environ.get('NIWA_APP_USERNAME', 'admin')
NIWA_APP_PASSWORD = os.environ.get('NIWA_APP_PASSWORD', 'change-me')
NIWA_APP_AUTH_REQUIRED = os.environ.get('NIWA_APP_AUTH_REQUIRED', '1') != '0'
NIWA_APP_SESSION_SECRET = os.environ.get('NIWA_APP_SESSION_SECRET', 'niwa-dev-secret-change-me')
NIWA_APP_SESSION_COOKIE = os.environ.get('NIWA_APP_SESSION_COOKIE', 'niwa_session')
NIWA_APP_SESSION_TTL_HOURS = int(os.environ.get('NIWA_APP_SESSION_TTL_HOURS', '168'))
# Cookie Domain attribute. Empty (default) = host-only cookie, works on any domain.
# Set to e.g. ".example.com" only for multi-subdomain SSO across the same parent.
NIWA_APP_COOKIE_DOMAIN = os.environ.get('NIWA_APP_COOKIE_DOMAIN', '').strip()
_COOKIE_DOMAIN_ATTR = f'Domain={NIWA_APP_COOKIE_DOMAIN}; ' if NIWA_APP_COOKIE_DOMAIN else ''
LOGIN_RATE_LIMIT_ATTEMPTS = int(os.environ.get('NIWA_APP_LOGIN_ATTEMPTS', '5'))
LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get('NIWA_APP_LOGIN_WINDOW_SECONDS', '900'))
NIWA_APP_PUBLIC_BASE_URL = os.environ.get('NIWA_APP_PUBLIC_BASE_URL', f'http://127.0.0.1:{PORT}')
_OPENCLAW_HOME = Path(os.environ.get('OPENCLAW_HOME', '/instance/.openclaw'))
OPENCLAW_CONFIG_PATH = _OPENCLAW_HOME / 'openclaw.json'
OPENCLAW_AGENTS_DIR = _OPENCLAW_HOME / 'agents'
AGENT_METADATA_PATH = BASE_DIR / 'config' / 'agents.json'
WORKSPACE_AGENTS_STATE_PATH = _OPENCLAW_HOME / 'workspace' / 'runtime' / 'agents-state.json'
WORKSPACE_DELEGATIONS_PATH = _OPENCLAW_HOME / 'workspace' / 'runtime' / 'delegations.json'

DEFAULT_KANBAN_COLUMNS = [
    ('col-pendiente', 'pendiente', 'Pendiente', 0, '#85adff', 0),
    ('col-en-progreso', 'en_progreso', 'En curso', 1, '#9bffce', 0),
    ('col-bloqueada', 'bloqueada', 'Bloqueada', 2, '#dc2626', 0),
    ('col-hecha', 'hecha', 'Hecha', 3, '#888888', 1),
    ('col-archivada', 'archivada', 'Archivada', 4, '#7c3aed', 1),
]

LOGIN_PAGE_HTML = r'''<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Login · Niwa</title>
  <style>
    :root{--bg:#0f172a;--card:#111827;--line:#243041;--text:#e5e7eb;--soft:#94a3b8;--accent:#2563eb;--accent2:#1d4ed8;--danger:#dc2626}
    *{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;font-family:Inter,system-ui,sans-serif;background:radial-gradient(circle at top,#1e293b 0%,#0f172a 55%,#020617 100%);color:var(--text)}
    .card{width:min(420px,calc(100vw - 32px));background:rgba(17,24,39,.96);border:1px solid var(--line);border-radius:22px;padding:28px;box-shadow:0 24px 60px rgba(0,0,0,.35)}
    .brand{font-size:28px;font-weight:800;letter-spacing:-.04em}.brand span{color:#86a8ff}.sub{margin-top:8px;color:var(--soft);font-size:14px;line-height:1.6}
    form{margin-top:24px;display:grid;gap:14px}.field{display:grid;gap:7px}.field label{font-size:12px;font-weight:700;color:#cbd5e1;text-transform:uppercase;letter-spacing:.06em}
    .field input{width:100%;padding:13px 14px;border-radius:14px;border:1px solid var(--line);background:#0b1220;color:var(--text);font:inherit}
    .field input:focus{outline:2px solid rgba(37,99,235,.22);border-color:var(--accent)}
    button{margin-top:4px;padding:13px 16px;border:none;border-radius:14px;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;font:inherit;font-weight:800;cursor:pointer}
    .error{margin-top:16px;padding:12px 14px;border-radius:14px;background:rgba(220,38,38,.14);border:1px solid rgba(248,113,113,.35);color:#fecaca;font-size:13px;line-height:1.5}
    .note{margin-top:18px;color:var(--soft);font-size:12px;line-height:1.6}
  </style>
</head>
<body>
  <div class="card">
    <div class="brand">Niwa</div>
    <div class="sub">Acceso protegido. Inicia sesión para abrir Niwa.</div>
    {error_html}
    <form method="post" action="/login">
      <div class="field">
        <label>Usuario</label>
        <input name="username" autocomplete="username" required />
      </div>
      <div class="field">
        <label>Contraseña</label>
        <input type="password" name="password" autocomplete="current-password" required />
      </div>
      <button type="submit">Entrar</button>
    </form>
    <div class="note">Configurable con NIWA_APP_USERNAME, NIWA_APP_PASSWORD y NIWA_APP_SESSION_SECRET.</div>
  </div>
</body>
</html>'''


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sign_session_payload(payload: str) -> str:
    return hmac.new(NIWA_APP_SESSION_SECRET.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()


def build_session_token(username: str) -> str:
    expires_at = int((datetime.now(timezone.utc) + timedelta(hours=NIWA_APP_SESSION_TTL_HOURS)).timestamp())
    nonce = secrets.token_hex(16)
    payload = f'{username}|{expires_at}|{nonce}'
    return f'{payload}|{_sign_session_payload(payload)}'


def verify_session_token(token: str) -> bool:
    try:
        username, expires_at, nonce, signature = token.split('|', 3)
        payload = f'{username}|{expires_at}|{nonce}'
    except ValueError:
        return False
    if username != NIWA_APP_USERNAME:
        return False
    expected = _sign_session_payload(payload)
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        if int(expires_at) < int(datetime.now(timezone.utc).timestamp()):
            return False
    except ValueError:
        return False
    return True


def render_login_page(error_message=''):
    error_html = f'<div class="error">{error_message}</div>' if error_message else ''
    return LOGIN_PAGE_HTML.replace('{error_html}', error_html)


def parse_cookies(handler):
    cookie = SimpleCookie()
    raw = handler.headers.get('Cookie')
    if raw:
        cookie.load(raw)
    return cookie


def is_authenticated(handler) -> bool:
    if not NIWA_APP_AUTH_REQUIRED:
        return True
    cookies = parse_cookies(handler)
    morsel = cookies.get(NIWA_APP_SESSION_COOKIE)
    return bool(morsel and verify_session_token(morsel.value))


def client_ip(handler) -> str:
    forwarded = handler.headers.get('X-Forwarded-For', '').split(',')[0].strip()
    if forwarded:
        return forwarded
    return handler.client_address[0] if handler.client_address else 'unknown'


def db_conn():
    # WAL mode lets the executor (separate process) and the web app write
    # concurrently without blocking each other. busy_timeout=10s makes the
    # rare contention non-fatal. Both PRAGMAs are idempotent.
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
    except sqlite3.OperationalError:
        pass
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db_conn() as conn:
        # Single source of truth: db/schema.sql.
        # Tables that used to be defined inline (kanban_columns, login_attempts, notes)
        # now live in schema.sql with the up-to-date enums (incl 'revision' status,
        # 'sistema' area, english priority aliases) and the Phase 5 typed-notes columns.
        conn.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
        ts = now_iso()
        for column_id, status, label, position, color, is_terminal in DEFAULT_KANBAN_COLUMNS:
            conn.execute(
                "INSERT OR IGNORE INTO kanban_columns (id, status, label, position, color, is_terminal, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (column_id, status, label, position, color, is_terminal, ts, ts),
            )
        conn.commit()


def seed_if_empty():
    """No-op for the portable Niwa pack. Projects and tasks are added via the
    setup wizard or the web app — there's no demo data."""
    return


def is_login_blocked(key: str) -> bool:
    with db_conn() as conn:
        row = conn.execute('SELECT blocked_until FROM login_attempts WHERE key=?', (key,)).fetchone()
        if not row or not row['blocked_until']:
            return False
        return row['blocked_until'] > now_iso()


def register_login_attempt(key: str, success: bool):
    ts = now_iso()
    with db_conn() as conn:
        row = conn.execute('SELECT attempts, last_attempt_at FROM login_attempts WHERE key=?', (key,)).fetchone()
        if success:
            conn.execute('DELETE FROM login_attempts WHERE key=?', (key,))
            conn.commit()
            return
        attempts = 1
        if row and row['last_attempt_at'] and (datetime.fromisoformat(ts) - datetime.fromisoformat(row['last_attempt_at'])).total_seconds() <= LOGIN_RATE_LIMIT_WINDOW_SECONDS:
            attempts = row['attempts'] + 1
        blocked_until = None
        if attempts >= LOGIN_RATE_LIMIT_ATTEMPTS:
            blocked_until = (datetime.now(timezone.utc) + timedelta(seconds=LOGIN_RATE_LIMIT_WINDOW_SECONDS)).replace(microsecond=0).isoformat()
            attempts = 0
        conn.execute(
            'INSERT INTO login_attempts (key, attempts, last_attempt_at, blocked_until) VALUES (?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET attempts=excluded.attempts, last_attempt_at=excluded.last_attempt_at, blocked_until=excluded.blocked_until',
            (key, attempts, ts, blocked_until),
        )
        conn.commit()




def fetch_my_day():
    day = date.today().isoformat()
    with db_conn() as conn:
        rows = conn.execute(
            'SELECT t.*, p.name as project_name FROM day_focus_tasks d JOIN tasks t ON t.id=d.task_id LEFT JOIN projects p ON p.id=t.project_id WHERE d.day=? ORDER BY d.position ASC',
            (day,),
        ).fetchall()
        summary_row = conn.execute('SELECT summary FROM day_focus WHERE day=?', (day,)).fetchone()
        return {'day': day, 'summary': summary_row['summary'] if summary_row else '', 'tasks': [dict(r) for r in rows]}


def fetch_projects():
    with db_conn() as conn:
        rows = conn.execute(
            '''SELECT p.*,
                      COUNT(CASE WHEN t.status NOT IN ('hecha','archivada') THEN 1 END) as open_tasks,
                      COUNT(CASE WHEN t.status = 'hecha' THEN 1 END) as done_tasks,
                      COUNT(t.id) as total_tasks
               FROM projects p LEFT JOIN tasks t ON t.project_id=p.id
               WHERE p.active=1 GROUP BY p.id ORDER BY p.name ASC'''
        ).fetchall()
        return [dict(r) for r in rows]


def fetch_stats():
    with db_conn() as conn:
        total = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
        open_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE status NOT IN ('hecha','archivada')").fetchone()[0]
        done_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='hecha'").fetchone()[0]
        done_today = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='hecha' AND date(completed_at)=date('now')").fetchone()[0]
        overdue = conn.execute("SELECT COUNT(*) FROM tasks WHERE due_at IS NOT NULL AND date(due_at)<date('now') AND status NOT IN ('hecha','archivada')").fetchone()[0]
        by_status = {}
        for row in conn.execute("SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status").fetchall():
            by_status[row['status']] = row['cnt']
        by_priority = {}
        for row in conn.execute("SELECT priority, COUNT(*) as c FROM tasks WHERE status NOT IN ('hecha','archivada') GROUP BY priority").fetchall():
            by_priority[row['priority'] or 'sin_prioridad'] = row['c']
        cbd_rows = conn.execute(
            "SELECT date(completed_at) as day, COUNT(*) as count FROM tasks "
            "WHERE status='hecha' AND completed_at IS NOT NULL AND date(completed_at) >= date('now', '-14 days') "
            "GROUP BY date(completed_at) ORDER BY day"
        ).fetchall()
        completions_by_day = [{'day': r['day'], 'count': r['count']} for r in cbd_rows]
    return {
        'total': total, 'open': open_count, 'done': done_count, 'done_today': done_today, 'overdue': overdue,
        'by_status': by_status, 'by_priority': by_priority, 'completions_by_day': completions_by_day,
    }


def fetch_kanban_columns(include_terminal=True):
    query = 'SELECT * FROM kanban_columns'
    params = []
    if not include_terminal:
        query += ' WHERE is_terminal=0'
    query += ' ORDER BY position ASC, label ASC'
    with db_conn() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def _safe_path_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()
    except Exception:
        return ''


def compute_live_state():
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT
                MAX(updated_at) AS tasks_updated_at,
                (SELECT MAX(updated_at) FROM day_focus) AS day_focus_updated_at,
                (SELECT MAX(created_at) FROM day_focus_tasks) AS day_focus_tasks_created_at,
                (SELECT MAX(updated_at) FROM kanban_columns) AS columns_updated_at
            FROM tasks
            """
        ).fetchone()
    values = [
        row['tasks_updated_at'] if row else '',
        row['day_focus_updated_at'] if row else '',
        row['day_focus_tasks_created_at'] if row else '',
        row['columns_updated_at'] if row else '',
        _safe_path_mtime(WORKSPACE_AGENTS_STATE_PATH),
        _safe_path_mtime(WORKSPACE_DELEGATIONS_PATH),
        _safe_path_mtime(OPENCLAW_CONFIG_PATH),
        _safe_path_mtime(AGENT_METADATA_PATH),
    ]
    latest = max((value for value in values if value), default='')
    token = hashlib.sha256('|'.join(v or '' for v in values).encode('utf-8')).hexdigest()[:16]
    return {'token': token, 'updated_at': latest, 'computed_at': now_iso()}


def fetch_flows_overview():
    rules = {}
    try:
        rules = json.loads((BASE_DIR.parent / 'config' / 'orchestrator-rules.json').read_text(encoding='utf-8'))
    except Exception:
        rules = {}

    routing = rules.get('routing', {}) if isinstance(rules, dict) else {}
    flow_items = []
    for route_name, route in routing.items():
        if not isinstance(route, dict):
            continue
        allowed = route.get('allowedAssignees', []) if isinstance(route.get('allowedAssignees', []), list) else []
        preferred = route.get('preferredAssignees', []) if isinstance(route.get('preferredAssignees', []), list) else []
        explicit_override = route.get('explicitAssigneeOverrides', True)
        aliases = route.get('aliases', {}) if isinstance(route.get('aliases'), dict) else {}
        flow_items.append({
            'id': route_name,
            'type': 'routing',
            'title': route.get('label') or f'Routing {route_name}',
            'summary': route.get('description') or 'Enrutado operativo de agentes.',
            'allowed_assignees': allowed,
            'preferred_assignees': preferred,
            'explicit_assignee_overrides': explicit_override,
            'alias_count': len(aliases),
        })

    return {'flows': flow_items, 'updated_at': now_iso()}


def dashboard_data():
    tasks = fetch_tasks()
    urgent = [t for t in tasks if t['urgent'] and t['status'] not in ('hecha', 'archivada')]
    today = fetch_tasks(today_only=True)
    by_area = {
        'personal': len([t for t in tasks if t['area'] == 'personal' and t['status'] not in ('hecha', 'archivada')]),
        'empresa': len([t for t in tasks if t['area'] == 'empresa' and t['status'] not in ('hecha', 'archivada')]),
        'proyecto': len([t for t in tasks if t['area'] == 'proyecto' and t['status'] not in ('hecha', 'archivada')]),
    }
    my_day = fetch_my_day()
    my_day_task_ids = [t['id'] for t in my_day['tasks']]
    return {
        'urgent': urgent[:8],
        'today': today[:10],
        'projects': fetch_projects(),
        'my_day': my_day,
        'my_day_task_ids': my_day_task_ids,
        'kanban_columns': fetch_kanban_columns(include_terminal=True),
        'counts': {
            'inbox': 0,  # deprecated, merged into pendiente
            'pending': len([t for t in tasks if t['status'] == 'pendiente']),
            'review': len([t for t in tasks if t['status'] == 'en_progreso']),
            'blocked': len([t for t in tasks if t['status'] == 'bloqueada']),
            'total': len([t for t in tasks if t['status'] not in ('hecha', 'archivada')]),
        },
        'by_area': by_area,
    }


def add_task_to_my_day(task_id):
    day = date.today().isoformat()
    ts = datetime.now(timezone.utc).isoformat()
    with db_conn() as conn:
        # Ensure day_focus row exists
        conn.execute('INSERT OR IGNORE INTO day_focus (day, summary, created_at, updated_at) VALUES (?, ?, ?, ?)', (day, '', ts, ts))
        # Get next position
        row = conn.execute('SELECT COALESCE(MAX(position),0)+1 as next_pos FROM day_focus_tasks WHERE day=?', (day,)).fetchone()
        next_pos = row['next_pos'] if row else 0
        conn.execute('INSERT OR IGNORE INTO day_focus_tasks (day, task_id, position) VALUES (?, ?, ?)', (day, task_id, next_pos))
        conn.commit()


def remove_task_from_my_day(task_id):
    day = date.today().isoformat()
    with db_conn() as conn:
        conn.execute('DELETE FROM day_focus_tasks WHERE day=? AND task_id=?', (day, task_id))
        conn.commit()


def is_task_in_my_day(task_id):
    day = date.today().isoformat()
    with db_conn() as conn:
        row = conn.execute('SELECT 1 FROM day_focus_tasks WHERE day=? AND task_id=?', (day, task_id)).fetchone()
        return row is not None



def load_agent_metadata():
    if AGENT_METADATA_PATH.exists():
        return json.loads(AGENT_METADATA_PATH.read_text(encoding='utf-8'))
    return {}


def extract_last_user_task(session_file: str) -> str:
    try:
        lines = Path(session_file).read_text(encoding='utf-8').splitlines()
        for line in reversed(lines):
            item = json.loads(line)
            msg = item.get('message', {})
            if msg.get('role') == 'user':
                parts = msg.get('content') or []
                texts = [p.get('text', '') for p in parts if isinstance(p, dict) and p.get('type') == 'text']
                text = ' '.join(texts).strip()
                if '\n\n' in text:
                    text = text.split('\n\n')[-1].strip()
                text = text.replace('\n', ' ')
                return (text[:140] + '…') if len(text) > 140 else text
    except Exception:
        return ''
    return ''


def _load_workspace_agents_state():
    """Load shared agent state from workspace runtime file (primary source)."""
    if WORKSPACE_AGENTS_STATE_PATH.exists():
        try:
            data = json.loads(WORKSPACE_AGENTS_STATE_PATH.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                return data.get('agents', {})
        except Exception:
            pass
    return {}


def _load_active_delegations():
    """Load active delegations from the orchestrator's runtime file.

    Returns a dict keyed by agent_id (lowercase) with the most recent
    active delegation (status in pending/working/blocked) for that agent.
    """
    if not WORKSPACE_DELEGATIONS_PATH.exists():
        return {}
    try:
        data = json.loads(WORKSPACE_DELEGATIONS_PATH.read_text(encoding='utf-8'))
        delegations = data.get('delegations', []) if isinstance(data, dict) else []
    except Exception:
        return {}
    active_statuses = {'pending', 'working', 'blocked'}
    by_agent = {}
    for d in delegations:
        if not isinstance(d, dict):
            continue
        agent = (d.get('assigned_to') or d.get('assignee') or d.get('agent') or '').lower()
        if not agent:
            continue
        st = (d.get('status') or '').lower()
        if st not in active_statuses:
            continue
        existing = by_agent.get(agent)
        if existing is None:
            by_agent[agent] = d
        else:
            new_ts = d.get('updated_at') or d.get('created_at') or ''
            old_ts = existing.get('updated_at') or existing.get('created_at') or ''
            if new_ts > old_ts:
                by_agent[agent] = d
    return by_agent


def fetch_agents_status():
    config = json.loads(OPENCLAW_CONFIG_PATH.read_text(encoding='utf-8')) if OPENCLAW_CONFIG_PATH.exists() else {}
    metadata = load_agent_metadata()
    workspace_state = _load_workspace_agents_state()
    active_delegations = _load_active_delegations()
    configured = config.get('agents', {}).get('list', []) if isinstance(config, dict) else []
    if configured:
        agent_rows = configured
    else:
        agent_rows = [{'id': agent_id, 'name': info.get('name', agent_id), 'model': ''} for agent_id, info in metadata.items()]
    agents = []
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    for item in agent_rows:
        agent_id = item.get('id')
        info = metadata.get(agent_id, {})
        ws = workspace_state.get(agent_id, {}) if isinstance(workspace_state, dict) else {}
        deleg = active_delegations.get(agent_id.lower())
        status = 'idle'
        current_task = ''
        last_seen = None
        # Top priority: active delegation from orchestrator
        if deleg and isinstance(deleg, dict):
            raw_st = (deleg.get('status') or '').lower()
            status = raw_st if raw_st in ('pending', 'working', 'blocked') else 'idle'
            current_task = deleg.get('task') or deleg.get('description') or deleg.get('title') or ''
            deleg_ts = deleg.get('updated_at') or deleg.get('created_at') or ''
            if deleg_ts:
                last_seen = deleg_ts
        # Secondary source: workspace shared state file
        elif ws and isinstance(ws, dict):
            status = ws.get('status', 'idle')
            current_task = ws.get('current_task', '')
            updated_at = ws.get('updated_at', '')
            if updated_at:
                last_seen = updated_at
        else:
            # Fallback: infer from session files
            session_path = OPENCLAW_AGENTS_DIR / agent_id / 'sessions' / 'sessions.json'
            if session_path.exists():
                try:
                    data = json.loads(session_path.read_text(encoding='utf-8'))
                    if isinstance(data, dict) and 'sessions' in data and isinstance(data['sessions'], list):
                        entries = data['sessions']
                    elif isinstance(data, dict):
                        entries = [v for v in data.values() if isinstance(v, dict)]
                    elif isinstance(data, list):
                        entries = [v for v in data if isinstance(v, dict)]
                    else:
                        entries = []
                    latest = None
                    latest_ts = 0
                    for entry in entries:
                        if isinstance(entry, dict):
                            ts = int(entry.get('updatedAt') or 0)
                            if ts > latest_ts:
                                latest_ts = ts
                                latest = entry
                    if latest and latest_ts:
                        last_seen = datetime.fromtimestamp(latest_ts / 1000, tz=timezone.utc).replace(microsecond=0).isoformat()
                        if now_ms - latest_ts <= 15 * 60 * 1000:
                            status = 'working'
                            current_task = extract_last_user_task(latest.get('sessionFile', '')) or 'Sesión activa reciente'
                except Exception:
                    pass
        agents.append({
            'id': agent_id,
            'name': info.get('name') or item.get('name') or agent_id,
            'role': info.get('role') or ('Asistente principal' if agent_id == 'main' else 'Agente'),
            'description': info.get('description', ''),
            'status': status,
            'current_task': current_task,
            'last_seen': last_seen,
            'model': (item.get('model') or {}).get('primary') if isinstance(item.get('model'), dict) else item.get('model', ''),
            'reports_to': info.get('reports_to') or item.get('reports_to') or ('main' if agent_id != 'main' else None),
        })
    # Build org summary
    total = len(agents)
    working = sum(1 for a in agents if a['status'] == 'working')
    pending = sum(1 for a in agents if a['status'] == 'pending')
    blocked = sum(1 for a in agents if a['status'] == 'blocked')
    idle = sum(1 for a in agents if a['status'] == 'idle')
    return {
        'agents': agents,
        'summary': {
            'total': total,
            'working': working,
            'pending': pending,
            'blocked': blocked,
            'idle': idle,
        },
    }


CRON_JOBS_PATH = _OPENCLAW_HOME / 'cron' / 'jobs.json'
GATEWAY_LOG_PATH = BASE_DIR / 'data' / 'gateway.log'
SANDBOX_CRON_LOG_PATH = BASE_DIR / 'data' / 'sandbox-cron.log'
SETTINGS_JSON_PATH = BASE_DIR / 'data' / 'settings.json'
_INSTANCE_HOME = Path(os.environ.get('YUME_BASE', '/instance'))
BRIDGE_LOG_PATH = _INSTANCE_HOME / 'logs' / 'bridge.log'
EXECUTOR_LOG_PATH = _INSTANCE_HOME / 'logs' / 'task-executor.log'
WATCHDOG_LOG_PATH = _INSTANCE_HOME / 'logs' / 'task-watchdog.log'
CLOUDFLARED_CONFIG_PATH = Path.home() / '.cloudflared' / 'config.yml'
UPLOADS_DIR = BASE_DIR / 'data' / 'project-uploads'

tasks_helpers._make_deps(db_conn, now_iso, WORKSPACE_DELEGATIONS_PATH)
tasks_service._make_deps(db_conn, now_iso, UPLOADS_DIR)
health_service._make_deps(db_conn)
from tasks_helpers import (
    record_task_event, load_delegations_index, enrich_tasks_with_agent_info,
)
from tasks_service import (
    fetch_tasks, get_task, create_task, update_task, delete_task,
    fetch_task_timelines, fetch_task_pipeline,
    fetch_task_labels, add_task_label, remove_task_label,
    fetch_task_attachments, save_task_attachment, delete_task_attachment,
)


# ── Notes CRUD ──

def fetch_notes(project_id=None, search=None):
    query = 'SELECT n.*, p.name as project_name FROM notes n LEFT JOIN projects p ON p.id=n.project_id WHERE 1=1'
    params = []
    if project_id:
        query += ' AND n.project_id=?'
        params.append(project_id)
    if search:
        query += ' AND (n.title LIKE ? OR n.content LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%'])
    query += ' ORDER BY n.updated_at DESC'
    with db_conn() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_note(note_id):
    with db_conn() as conn:
        row = conn.execute('SELECT n.*, p.name as project_name FROM notes n LEFT JOIN projects p ON p.id=n.project_id WHERE n.id=?', (note_id,)).fetchone()
        return dict(row) if row else None


def create_note(payload):
    note_id = str(uuid.uuid4())
    ts = now_iso()
    tags = payload.get('tags')
    if isinstance(tags, list):
        tags = json.dumps(tags)
    with db_conn() as conn:
        conn.execute(
            'INSERT INTO notes (id, title, content, project_id, tags, created_at, updated_at) VALUES (?,?,?,?,?,?,?)',
            (note_id, payload.get('title', '').strip() or 'Sin título', payload.get('content', ''),
             payload.get('project_id') or None, tags, ts, ts),
        )
        conn.commit()
    return note_id


def update_note(note_id, payload):
    allowed = {'title', 'content', 'project_id', 'tags'}
    sets, params = [], []
    for k, v in payload.items():
        if k in allowed:
            if k == 'tags' and isinstance(v, list):
                v = json.dumps(v)
            sets.append(f'{k}=?')
            params.append(v)
    if not sets:
        return
    existing = get_note(note_id)
    if not existing:
        raise ValueError('note_not_found')
    sets.append('updated_at=?')
    params.append(now_iso())
    params.append(note_id)
    with db_conn() as conn:
        conn.execute(f'UPDATE notes SET {", ".join(sets)} WHERE id=?', params)
        conn.commit()


def delete_note(note_id):
    with db_conn() as conn:
        conn.execute('DELETE FROM notes WHERE id=?', (note_id,))
        conn.commit()


def fetch_activity(limit=50):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT e.*, t.title as task_title FROM task_events e LEFT JOIN tasks t ON t.id=e.task_id ORDER BY e.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        items = []
        for r in rows:
            item = dict(r)
            try:
                item['payload'] = json.loads(item.get('payload_json') or '{}')
            except Exception:
                item['payload'] = {}
            items.append(item)
        return items


def fetch_security():
    try:
        log_path = BASE_DIR / 'data' / 'sandbox-enforcer.log'
        lines = log_path.read_text(encoding='utf-8', errors='ignore').strip().split('\n') if log_path.exists() else []
        threats = []
        for line in lines[-50:]:
            if 'BLOCK' in line.upper() or 'WARN' in line.upper() or 'THREAT' in line.upper():
                threats.append({'line': line.strip(), 'severity': 'high' if 'BLOCK' in line.upper() else 'medium'})
        total_issues = len(threats)
        risk = 'low' if total_issues == 0 else ('medium' if total_issues < 5 else 'high')
        return {
            'summary': {'risk_level': risk, 'total_issues': total_issues},
            'risk_level': risk, 'threats': threats[-20:], 'scanned_at': now_iso(),
            'total_log_lines': len(lines), 'total_issues': total_issues,
            'network': [], 'vulnerabilities': [], 'timeline': [],
        }
    except Exception as e:
        return {'summary': {'risk_level': 'unknown', 'total_issues': 0}, 'risk_level': 'unknown', 'threats': [], 'error': str(e)}


fetch_health = health_service.fetch_health


def fetch_logs(source='all', limit=200, **_kw):
    lines = []
    log_sources = {
        'gateway': GATEWAY_LOG_PATH,
        'sync': SANDBOX_CRON_LOG_PATH,
        'bridge': BRIDGE_LOG_PATH,
        'executor': EXECUTOR_LOG_PATH,
        'watchdog': WATCHDOG_LOG_PATH,
    }
    try:
        for src_name, src_path in log_sources.items():
            if source in ('all', src_name) and src_path.exists():
                text = src_path.read_text(encoding='utf-8', errors='ignore').strip()
                if text:
                    for line in text.split('\n')[-limit:]:
                        lines.append({'source': src_name, 'line': line})
    except Exception:
        pass
    lines.sort(key=lambda x: x['line'], reverse=True)
    return lines[:limit]


def fetch_crons():
    if not CRON_JOBS_PATH.exists():
        return []
    try:
        data = json.loads(CRON_JOBS_PATH.read_text(encoding='utf-8'))
        jobs = data.get('jobs', []) if isinstance(data, dict) else []
        result = []
        for j in jobs:
            state = j.get('state', {})
            meta = j.get('meta', {})
            delivery = j.get('delivery', {})
            item = {
                'id': j['id'], 'name': j.get('name', j['id']), 'enabled': j.get('enabled', False), 'description': j.get('description', ''),
                'schedule': j.get('schedule', {}),
                'last_status': state.get('lastStatus', ''),
                'last_duration_ms': state.get('lastDurationMs'),
                'last_run': state.get('lastRunAtMs'),
                'next_run': state.get('nextRunAtMs'),
                'consecutive_errors': state.get('consecutiveErrors', 0),
                'agent': j.get('agentId', ''),
                'has_script': bool(meta.get('script')),
                'has_skill': bool(meta.get('skill')),
                'delivery_channel': delivery.get('channel', ''),
                'delivery_muted': not delivery.get('bestEffort', True),
                'delivery_format': delivery.get('format', 'text'),
                'nodes': [],
            }
            # Build nodes for detail view
            if meta.get('script'):
                item['nodes'].append({'type': 'script', 'label': Path(meta['script']).name})
            if j.get('agentId'):
                item['nodes'].append({'type': 'agent', 'label': j['agentId']})
            if delivery.get('channel'):
                item['nodes'].append({'type': 'delivery', 'label': f"{delivery['channel']}:{delivery.get('to', '')}"})
            result.append(item)
        return result
    except Exception:
        return []


def fetch_config():
    result = {}
    try:
        agents_path = BASE_DIR / 'config' / 'agents.json'
        if agents_path.exists():
            result['agents'] = {'path': str(agents_path), 'data': json.loads(agents_path.read_text(encoding='utf-8'))}
    except Exception:
        pass
    try:
        sandbox_path = BASE_DIR / 'config' / 'sandbox.json'
        if sandbox_path.exists():
            result['sandbox'] = {'path': str(sandbox_path), 'data': json.loads(sandbox_path.read_text(encoding='utf-8'))}
    except Exception:
        pass
    return result


def fetch_settings():
    settings = {}
    try:
        if SETTINGS_JSON_PATH.exists():
            settings = json.loads(SETTINGS_JSON_PATH.read_text(encoding='utf-8'))
    except Exception:
        pass
    with db_conn() as conn:
        for row in conn.execute('SELECT key, value FROM settings').fetchall():
            settings[row['key']] = row['value']
    return settings


def save_setting(key, value):
    settings = {}
    if SETTINGS_JSON_PATH.exists():
        try:
            settings = json.loads(SETTINGS_JSON_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    settings[key] = value
    SETTINGS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_JSON_PATH.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding='utf-8')
    return settings


# ── Integrations config (Telegram, LLM, Executor, Webhook) ──
# Env vars are the install-time defaults; settings table holds runtime overrides.
_INTEGRATION_KEYS = {
    'telegram_bot_token': 'NIWA_TELEGRAM_BOT_TOKEN',
    'telegram_chat_id': 'NIWA_TELEGRAM_CHAT_ID',
    'webhook_url': 'NIWA_WEBHOOK_URL',
    'llm_provider': 'NIWA_LLM_PROVIDER',
    'llm_command': 'NIWA_LLM_COMMAND',
    'llm_api_key': 'NIWA_LLM_API_KEY',
    'llm_auth_method': 'NIWA_LLM_AUTH_METHOD',
    'executor_enabled': 'NIWA_EXECUTOR_ENABLED',
    'executor_poll_seconds': 'NIWA_EXECUTOR_POLL_SECONDS',
    'executor_timeout_seconds': 'NIWA_EXECUTOR_TIMEOUT_SECONDS',
}
# Keys whose values should be masked in GET responses
_SENSITIVE_KEYS = {'telegram_bot_token', 'llm_api_key'}


def fetch_integrations():
    """Return current integration config: env defaults overlaid with settings."""
    settings = fetch_settings()
    result = {}
    for key, env_var in _INTEGRATION_KEYS.items():
        val = settings.get(f'int.{key}') or os.environ.get(env_var, '')
        if key in _SENSITIVE_KEYS and val:
            result[key] = val[:8] + '...' + val[-4:] if len(val) > 12 else '****'
            result[f'{key}_set'] = True
        else:
            result[key] = val
    return result


def save_integrations(payload):
    """Save integration settings to the settings store."""
    saved = {}
    _NUMERIC = {'executor_poll_seconds': (5, 3600), 'executor_timeout_seconds': (60, 7200)}
    for key in _INTEGRATION_KEYS:
        if key not in payload:
            continue
        val = str(payload[key]).strip()
        if key in _NUMERIC:
            try:
                lo, hi = _NUMERIC[key]
                val = str(max(lo, min(hi, int(val))))
            except (ValueError, TypeError):
                continue
        save_setting(f'int.{key}', val)
        saved[key] = val
    # Update notifier module's live values so changes take effect immediately
    try:
        if 'telegram_bot_token' in saved:
            notifier.TELEGRAM_BOT_TOKEN = saved['telegram_bot_token']
        if 'telegram_chat_id' in saved:
            notifier.TELEGRAM_CHAT_ID = saved['telegram_chat_id']
        if 'webhook_url' in saved:
            notifier.GENERIC_WEBHOOK_URL = saved['webhook_url']
    except Exception:
        pass
    return saved


def test_telegram():
    """Send a test message via Telegram using current config."""
    settings = fetch_settings()
    token = settings.get('int.telegram_bot_token') or os.environ.get('NIWA_TELEGRAM_BOT_TOKEN', '')
    chat_id = settings.get('int.telegram_chat_id') or os.environ.get('NIWA_TELEGRAM_CHAT_ID', '')
    if not token:
        return {'ok': False, 'error': 'Bot token is empty — enter it above and save first'}
    if not chat_id:
        return {'ok': False, 'error': 'Chat ID is empty — enter it above and save first'}
    # Try sending with detailed error capture
    import urllib.request, urllib.error
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": "Niwa test message", "parse_mode": "Markdown"}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        return {'ok': True}
    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = json.loads(e.read().decode()).get('description', '')
        except Exception:
            pass
        return {'ok': False, 'error': f'Telegram API error {e.code}: {body}' if body else f'HTTP {e.code}'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def apply_setup_token(token: str) -> dict:
    """Store a Claude setup token as CLAUDE_CODE_OAUTH_TOKEN for the executor to use."""
    if not token or not token.strip():
        return {'ok': False, 'error': 'Token is empty'}
    token = token.strip()
    if not token.startswith('sk-ant-'):
        return {'ok': False, 'error': 'Invalid token format — should start with sk-ant-oat01-'}
    # Store it in settings so the executor can read it
    save_setting('int.llm_setup_token', token)
    return {'ok': True, 'message': 'Token saved — the executor will use it as CLAUDE_CODE_OAUTH_TOKEN'}


def check_llm_status() -> dict:
    """Check if the configured LLM CLI is installed and authenticated."""
    import subprocess as _sp
    settings = fetch_settings()
    provider = settings.get('int.llm_provider') or os.environ.get('NIWA_LLM_PROVIDER', '')
    auth_method = settings.get('int.llm_auth_method') or os.environ.get('NIWA_LLM_AUTH_METHOD', 'api_key')
    api_key = settings.get('int.llm_api_key') or os.environ.get('NIWA_LLM_API_KEY', '')
    command = settings.get('int.llm_command') or os.environ.get('NIWA_LLM_COMMAND', '')

    result = {'provider': provider, 'auth_method': auth_method, 'command': command,
              'api_key_set': bool(api_key), 'cli_installed': False, 'authenticated': False}

    if not provider:
        result['status'] = 'not_configured'
        return result

    # Check CLI installed
    binary = {'claude': 'claude', 'llm': 'llm', 'gemini': 'gemini'}.get(provider, command.split()[0] if command else '')
    if binary:
        which = _sp.run(['which', binary], capture_output=True, text=True).stdout.strip()
        result['cli_installed'] = bool(which)
        result['cli_path'] = which

    # Check auth
    if auth_method == 'api_key' and api_key:
        result['authenticated'] = True
        result['status'] = 'ready' if result['cli_installed'] else 'cli_missing'
    elif auth_method == 'setup_token':
        # Claude with setup token — check if ~/.claude.json exists
        claude_config = Path.home() / '.claude.json'
        result['authenticated'] = claude_config.exists()
        result['status'] = 'ready' if (result['cli_installed'] and result['authenticated']) else 'needs_auth'
    elif auth_method == 'oauth':
        claude_config = Path.home() / '.claude.json'
        result['authenticated'] = claude_config.exists()
        result['status'] = 'ready' if (result['cli_installed'] and result['authenticated']) else 'needs_oauth'
    else:
        result['status'] = 'unknown'

    return result


def search_tasks(q, limit=30):
    q = q.strip()
    if not q:
        return []
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT t.*, p.name as project_name FROM tasks t LEFT JOIN projects p ON p.id=t.project_id WHERE t.title LIKE ? OR t.description LIKE ? OR t.notes LIKE ? ORDER BY t.updated_at DESC LIMIT ?",
            (f'%{q}%', f'%{q}%', f'%{q}%', limit),
        ).fetchall()
        return [dict(r) for r in rows]


def _parse_dt(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def fetch_kpis():
    result = {'per_phase': {}, 'overall': {}, 'time_series': {}}
    with db_conn() as conn:
        tbl = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_metrics'").fetchone()
        if not tbl:
            return result

        # Per-phase stats (including new phases: verify, visual, coverage)
        for phase in ('triage', 'execute', 'review', 'deploy', 'verify', 'visual', 'coverage'):
            rows = conn.execute(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successes, "
                "AVG(duration_seconds) as avg_duration, "
                "SUM(CASE WHEN hit_limit=1 THEN 1 ELSE 0 END) as limit_hits, "
                "MAX(max_turns) as max_turns "
                "FROM task_metrics WHERE phase=?", (phase,)
            ).fetchone()
            total = rows['total'] or 0
            if total == 0:
                continue
            successes = rows['successes'] or 0
            result['per_phase'][phase] = {
                'total_runs': total,
                'success_rate': round(successes / total * 100, 1) if total else 0,
                'avg_duration': round(rows['avg_duration'] or 0, 1),
                'limit_hit_rate': round((rows['limit_hits'] or 0) / total * 100, 1) if total else 0,
            }
            errs = conn.execute(
                "SELECT task_id, error_message, timestamp FROM task_metrics "
                "WHERE phase=? AND success=0 AND error_message IS NOT NULL AND error_message!='' "
                "ORDER BY timestamp DESC LIMIT 5", (phase,)
            ).fetchall()
            result['per_phase'][phase]['recent_errors'] = [
                {'task_id': e['task_id'], 'error': (e['error_message'] or '')[:200], 'at': e['timestamp']} for e in errs
            ]

        # Overall
        today_done = conn.execute(
            "SELECT COUNT(DISTINCT task_id) FROM task_metrics WHERE success=1 AND date(timestamp)=date('now')"
        ).fetchone()[0]
        today_blocked = conn.execute(
            "SELECT COUNT(DISTINCT task_id) FROM task_metrics WHERE success=0 AND date(timestamp)=date('now')"
        ).fetchone()[0]
        avg_pipe = conn.execute(
            "SELECT task_id, SUM(duration_seconds) as total_dur FROM task_metrics GROUP BY task_id"
        ).fetchall()
        avg_pipeline_dur = round(sum(r['total_dur'] for r in avg_pipe) / len(avg_pipe), 1) if avg_pipe else 0
        result['overall'] = {
            'tasks_completed_today': today_done,
            'tasks_blocked_today': today_blocked,
            'avg_pipeline_duration_s': avg_pipeline_dur,
        }

        # Time series (14 days)
        for key, where in [('completions', "success=1 AND phase IN ('review','deploy')"),
                           ('blocks', "success=0"),
                           ('limit_hits', "hit_limit=1")]:
            rows = conn.execute(
                f"SELECT date(timestamp) as day, COUNT(DISTINCT task_id) as cnt "
                f"FROM task_metrics WHERE {where} "
                f"AND date(timestamp) >= date('now','-14 days') GROUP BY day ORDER BY day"
            ).fetchall()
            result['time_series'][key] = [{'day': r['day'], 'count': r['cnt']} for r in rows]

    return result


def fetch_pipeline(days=7):
    cutoff = f'-{days} days'
    with db_conn() as conn:
        tasks_rows = conn.execute(
            "SELECT t.id, t.title, t.project_id, t.created_at, t.completed_at, p.name as project_name "
            "FROM tasks t LEFT JOIN projects p ON p.id=t.project_id "
            "WHERE t.status='hecha' AND t.completed_at IS NOT NULL AND date(t.completed_at) >= date('now', ?)",
            (cutoff,)
        ).fetchall()
        task_ids = [r['id'] for r in tasks_rows]
        if not task_ids:
            return {'task_count': 0, 'days': days, 'bottleneck': None,
                    'avg_total_min': 0, 'avg_queue_min': 0, 'avg_execution_min': 0, 'avg_review_min': 0,
                    'stages': [], 'by_project': {}}
        placeholders = ','.join('?' * len(task_ids))
        events = conn.execute(
            f"SELECT task_id, type, payload_json, created_at FROM task_events WHERE task_id IN ({placeholders}) ORDER BY created_at",
            task_ids
        ).fetchall()
    task_events_map = {}
    for e in events:
        task_events_map.setdefault(e['task_id'], []).append(dict(e))
    stage_keys = ['pendiente', 'en_progreso', 'revision']
    all_durations = {s: [] for s in stage_keys}
    project_data = {}
    for t in tasks_rows:
        tid = t['id']
        t_created = _parse_dt(t['created_at'])
        t_completed = _parse_dt(t['completed_at'])
        if not t_created or not t_completed:
            continue
        evts = task_events_map.get(tid, [])
        timeline = [{'status': 'pendiente', 'at': t_created}]
        for ev in evts:
            ev_time = _parse_dt(ev['created_at'])
            if not ev_time:
                continue
            try:
                p = json.loads(ev['payload_json'] or '{}')
            except Exception:
                p = {}
            if ev['type'] == 'status_changed':
                new_status = p.get('changes', {}).get('status') or p.get('new', '')
                if new_status:
                    timeline.append({'status': new_status, 'at': ev_time})
            elif ev['type'] == 'completed':
                timeline.append({'status': 'hecha', 'at': ev_time})
        timeline.append({'status': '_end', 'at': t_completed})
        timeline.sort(key=lambda x: x['at'])
        stage_times = {}
        for i in range(len(timeline) - 1):
            st = timeline[i]['status']
            dur = max(0, (timeline[i + 1]['at'] - timeline[i]['at']).total_seconds() / 60)
            stage_times[st] = stage_times.get(st, 0) + dur
        queue_min = stage_times.get('pendiente', 0)
        exec_min = stage_times.get('en_progreso', 0)
        review_min = stage_times.get('revision', 0)
        all_durations['pendiente'].append(queue_min)
        all_durations['en_progreso'].append(exec_min)
        all_durations['revision'].append(review_min)
        pname = t['project_name'] or 'Sin proyecto'
        if pname not in project_data:
            project_data[pname] = {s: [] for s in stage_keys}
            project_data[pname]['_count'] = 0
        project_data[pname]['_count'] += 1
        project_data[pname]['pendiente'].append(queue_min)
        project_data[pname]['en_progreso'].append(exec_min)
        project_data[pname]['revision'].append(review_min)
    def avg(lst):
        return sum(lst) / len(lst) if lst else 0
    avg_q = avg(all_durations['pendiente'])
    avg_e = avg(all_durations['en_progreso'])
    avg_r = avg(all_durations['revision'])
    avg_total = avg_q + avg_e + avg_r
    bottleneck = max(stage_keys, key=lambda s: avg(all_durations[s])) if avg_total > 0 else None
    def make_stages(q, e, r):
        total = q + e + r
        if total == 0:
            return []
        return [
            {'key': 'pendiente', 'label': 'Queue', 'avg_min': round(q, 1), 'pct': round(q / total * 100)},
            {'key': 'en_progreso', 'label': 'Execution', 'avg_min': round(e, 1), 'pct': round(e / total * 100)},
            {'key': 'revision', 'label': 'Review', 'avg_min': round(r, 1), 'pct': round(r / total * 100)},
        ]
    by_project = {}
    for pname, pd in project_data.items():
        pq, pe, pr = avg(pd['pendiente']), avg(pd['en_progreso']), avg(pd['revision'])
        by_project[pname] = {
            'task_count': pd['_count'], 'avg_total_min': round(pq + pe + pr, 1),
            'stages': make_stages(pq, pe, pr),
        }
    return {
        'task_count': len(tasks_rows), 'days': days, 'bottleneck': bottleneck,
        'avg_total_min': round(avg_total, 1), 'avg_queue_min': round(avg_q, 1),
        'avg_execution_min': round(avg_e, 1), 'avg_review_min': round(avg_r, 1),
        'stages': make_stages(avg_q, avg_e, avg_r), 'by_project': by_project,
    }


def toggle_cron(job_id):
    try:
        data = json.loads(CRON_JOBS_PATH.read_text(encoding='utf-8'))
        for j in data.get('jobs', []):
            if j['id'] == job_id:
                j['enabled'] = not j.get('enabled', False)
                CRON_JOBS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
                return {'ok': True, 'enabled': j['enabled']}
        return {'error': 'job_not_found'}
    except Exception as e:
        return {'error': str(e)}


def toggle_cron_delivery(job_id, action='mute'):
    try:
        data = json.loads(CRON_JOBS_PATH.read_text(encoding='utf-8'))
        for j in data.get('jobs', []):
            if j['id'] == job_id:
                delivery = j.setdefault('delivery', {})
                if action == 'mute':
                    delivery['bestEffort'] = not delivery.get('bestEffort', True)
                    CRON_JOBS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
                    return {'ok': True, 'muted': not delivery['bestEffort']}
                elif action == 'format':
                    current = delivery.get('format', 'text')
                    cycle = {'text': 'audio', 'audio': 'both', 'both': 'text'}
                    delivery['format'] = cycle.get(current, 'audio')
                    CRON_JOBS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
                    return {'ok': True, 'format': delivery['format']}
        return {'error': 'job_not_found'}
    except Exception as e:
        return {'error': str(e)}


_INDEX_HTML_CACHE = {'html': None, 'mtime': 0}


def get_index_html():
    index_path = BASE_DIR / 'frontend' / 'index.html'
    try:
        mtime = index_path.stat().st_mtime
    except Exception:
        return '<h1>index.html not found</h1>'
    if _INDEX_HTML_CACHE['html'] is not None and _INDEX_HTML_CACHE['mtime'] == mtime:
        return _INDEX_HTML_CACHE['html']
    html = index_path.read_text(encoding='utf-8')
    _INDEX_HTML_CACHE['html'] = html
    _INDEX_HTML_CACHE['mtime'] = mtime
    return html


_PLACEHOLDER_REMOVED = True  # INDEX_HTML removed — served from frontend/index.html

class Handler(BaseHTTPRequestHandler):
    def _json(self, data, status=200, headers=None):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html, status=200, headers=None):
        body = html.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location, headers=None):
        self.send_response(302)
        self.send_header('Location', location)
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()

    def _read_form_or_json(self):
        length = int(self.headers.get('Content-Length', '0'))
        raw = self.rfile.read(length) if length else b''
        ctype = self.headers.get('Content-Type', '')
        if 'application/json' in ctype:
            try:
                return json.loads(raw.decode('utf-8') or '{}')
            except (json.JSONDecodeError, ValueError):
                return {}
        if 'application/x-www-form-urlencoded' in ctype:
            parsed = parse_qs(raw.decode('utf-8'))
            return {k: v[0] if isinstance(v, list) and v else '' for k, v in parsed.items()}
        if not raw:
            return {}
        try:
            return json.loads(raw.decode('utf-8') or '{}')
        except Exception:
            parsed = parse_qs(raw.decode('utf-8'))
            return {k: v[0] if isinstance(v, list) and v else '' for k, v in parsed.items()}

    def _require_auth(self):
        if is_authenticated(self):
            return False
        path = urlparse(self.path).path
        if path.startswith('/api/'):
            self._json({'error': 'unauthorized'}, 401)
        else:
            self._redirect('/login')
        return True

    _MIME_MAP = {
        '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript',
        '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.svg': 'image/svg+xml',
        '.ico': 'image/x-icon', '.woff': 'font/woff', '.woff2': 'font/woff2',
        '.ttf': 'font/ttf', '.pdf': 'application/pdf', '.txt': 'text/plain',
        '.webp': 'image/webp', '.mp4': 'video/mp4', '.webm': 'video/webm',
    }

    def _serve_static(self, rel_path):
        static_dir = BASE_DIR / 'frontend' / 'static'
        target = (static_dir / rel_path).resolve()
        frontend_dir = BASE_DIR / 'frontend'
        if not str(target).startswith(str(frontend_dir.resolve())):
            return self._json({'error': 'forbidden'}, 403)
        if not target.is_file():
            return self._json({'error': 'not_found'}, 404)
        ext = target.suffix.lower()
        mime = self._MIME_MAP.get(ext, 'application/octet-stream')
        body = target.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def _serve_task_attachment(self, task_id, filename):
        safe_name = Path(filename).name
        target = (UPLOADS_DIR / task_id / safe_name).resolve()
        if not str(target).startswith(str(UPLOADS_DIR.resolve())):
            return self._json({'error': 'forbidden'}, 403)
        if not target.is_file():
            return self._json({'error': 'not_found'}, 404)
        ext = target.suffix.lower()
        mime = self._MIME_MAP.get(ext, 'application/octet-stream')
        body = target.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Content-Disposition', f'inline; filename="{safe_name}"')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path == '/health':
            return self._json({'ok': True})
        if path == '/login':
            if is_authenticated(self):
                return self._redirect('/')
            return self._html(render_login_page())
        if path == '/logout':
            return self._redirect('/login', headers={'Set-Cookie': f'{NIWA_APP_SESSION_COOKIE}=; Path=/; {_COOKIE_DOMAIN_ATTR}HttpOnly; SameSite=Lax; Max-Age=0'})
        if path.startswith('/static/'):
            rel = path[len('/static/'):]
            return self._serve_static(rel)
        if path in ('/', '/index.html'):
            if self._require_auth():
                return
            return self._html(get_index_html())
        if path == '/auth/check':
            if is_authenticated(self):
                return self._json({'ok': True})
            # ForwardAuth: Traefik passes 401 body to client — HTML redirect to login
            self.send_response(401)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            _login_url = f'{NIWA_APP_PUBLIC_BASE_URL.rstrip("/")}/login'
            _redirect_html = f'<!DOCTYPE html><html><head><meta http-equiv="refresh" content="0;url={_login_url}"></head><body>Redirecting to login...</body></html>'
            self.wfile.write(_redirect_html.encode('utf-8'))
            return
        if path.startswith('/api/') and self._require_auth():
            return
        if path == '/api/dashboard':
            return self._json(dashboard_data())
        if path == '/api/tasks':
            include_done = qs.get('include_done', ['0'])[0] == '1'
            status = qs.get('status', [None])[0]
            area = qs.get('area', [None])[0]
            project_id = qs.get('project_id', [None])[0]
            tasks = fetch_tasks(include_done=include_done, status=status, area=area)
            if project_id:
                tasks = [t for t in tasks if t.get('project_id') == project_id]
            return self._json(tasks)
        if path == '/api/docs':
            docs = {}
            import pathlib as _pl_docs
            _docs_dir = _pl_docs.Path(__file__).resolve().parent.parent
            for name in ['ARCHITECTURE', 'ERROR-STANDARD', 'REFACTOR-PLAN', 'API']:
                _doc_path = _docs_dir / f'{name}.md'
                if _doc_path.exists():
                    docs[name.lower()] = _doc_path.read_text(encoding='utf-8', errors='ignore')
            return self._json(docs)
        if path == '/api/my-day':
            return self._json(fetch_my_day())
        if path == '/api/projects':
            return self._json(fetch_projects())
        if path == '/api/kanban-columns':
            include_terminal = qs.get('include_terminal', ['1'])[0] == '1'
            return self._json(fetch_kanban_columns(include_terminal=include_terminal))
        if path == '/api/agents-status':
            return self._json(fetch_agents_status())
        if path == '/api/flows':
            return self._json(fetch_flows_overview())
        if path == '/api/live-state':
            return self._json(compute_live_state())
        if path == '/api/kpis':
            return self._json(fetch_kpis())
        if path == '/api/metrics':
            import time as _mtime
            _metrics = {}
            # Self-check only — the portable Niwa app doesn't know about other services.
            # If you want to monitor other endpoints, set ISU_HEALTH_SERVICES env var
            # (parsed by health_service.py).
            _t0 = _mtime.time()
            try:
                urllib.request.urlopen('http://localhost:8080/health', timeout=5)
                _metrics['niwa-app'] = {'status':'up','latency_ms':round((_mtime.time()-_t0)*1000)}
            except Exception:
                _metrics['niwa-app'] = {'status':'down','latency_ms':-1}
            with db_conn() as _mc:
                _metrics['tasks_today'] = _mc.execute("SELECT count(*) FROM tasks WHERE status='hecha' AND date(completed_at)=date('now')").fetchone()[0]
                _metrics['tasks_pending'] = _mc.execute("SELECT count(*) FROM tasks WHERE status='pendiente'").fetchone()[0]
                _metrics['tasks_blocked'] = _mc.execute("SELECT count(*) FROM tasks WHERE status='bloqueada'").fetchone()[0]
            return self._json(_metrics)
        if path == '/api/health/full':
            return self._json(fetch_health())
        if path == '/api/stats':
            return self._json(fetch_stats())
        if path == '/api/activity':
            limit = int((qs.get('limit') or ['50'])[0])
            return self._json(fetch_activity(limit=limit))
        if path == '/api/security':
            return self._json(fetch_security())
        if path == '/api/logs':
            source = (qs.get('source') or ['gateway'])[0]
            lines_count = int((qs.get('lines') or ['100'])[0])
            return self._json(fetch_logs(source=source, limit=lines_count))
        if path == '/api/routines':
            return self._json(scheduler.list_routines(db_conn))
        if re.match(r'^/api/routines/[^/]+$', path) and path.count('/') == 3:
            routine_id = path.split('/')[3]
            routine = scheduler.get_routine(db_conn, routine_id)
            if not routine:
                return self._json({'error': 'not_found'}, 404)
            return self._json(routine)
        if path == '/api/crons':
            return self._json(fetch_crons())
        if path == '/api/config':
            return self._json(fetch_config())
        if path == '/api/settings':
            return self._json(fetch_settings())
        if path == '/api/settings/integrations':
            return self._json(fetch_integrations())
        if path == '/api/settings/llm-status':
            return self._json(check_llm_status())
        if path == '/api/tasks/history':
            from history import fetch_task_history
            params = {
                'project_id': (qs.get('project_id') or [None])[0],
                'from': (qs.get('from') or [None])[0],
                'to': (qs.get('to') or [None])[0],
                'source': (qs.get('source') or [None])[0],
                'search': (qs.get('search') or [None])[0],
                'page': int((qs.get('page') or ['1'])[0]),
                'limit': int((qs.get('limit') or ['50'])[0]),
                'sort': (qs.get('sort') or ['completed_at'])[0],
                'order': (qs.get('order') or ['desc'])[0],
            }
            return self._json(fetch_task_history(params, db_conn))
        if path == '/api/search':
            q = (qs.get('q') or [''])[0]
            return self._json(search_tasks(q))
        if path == '/api/dashboard/pipeline':
            days = int(qs.get('days', ['7'])[0])
            return self._json(fetch_pipeline(days=days))
        if path == '/api/tasks/timelines':
            ids_str = qs.get('ids', [''])[0]
            task_ids = [x.strip() for x in ids_str.split(',') if x.strip()]
            return self._json(fetch_task_timelines(task_ids))
        if re.match(r'^/api/tasks/[^/]+$', path) and path.count('/') == 3:
            task_id = path.split('/')[3]
            task = get_task(task_id)
            if not task:
                return self._json({'error': 'not_found'}, 404)
            return self._json(task)
        if re.match(r'^/api/tasks/[^/]+/pipeline$', path):
            task_id = path.split('/')[3]
            result = fetch_task_pipeline(task_id)
            if 'error' in result:
                return self._json(result, 404)
            return self._json(result)
        if re.match(r'^/api/tasks/[^/]+/labels$', path):
            task_id = path.split('/')[3]
            return self._json(fetch_task_labels(task_id))
        if re.match(r'^/api/tasks/[^/]+/attachments$', path):
            task_id = path.split('/')[3]
            return self._json(fetch_task_attachments(task_id))
        if re.match(r'^/api/tasks/[^/]+/attachments/[^/]+$', path):
            parts = path.split('/')
            task_id, filename = parts[3], parts[5]
            return self._serve_task_attachment(task_id, filename)
        if path == '/api/notes':
            project_id = (qs.get('project_id') or [None])[0]
            search = (qs.get('search') or [None])[0]
            return self._json(fetch_notes(project_id=project_id, search=search))
        if re.match(r'^/api/notes/[^/]+$', path) and path.count('/') == 3:
            note_id = path.split('/')[3]
            note = get_note(note_id)
            if not note:
                return self._json({'error': 'not_found'}, 404)
            return self._json(note)
        return self._json({'error': 'not_found'}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        # Handle multipart uploads BEFORE reading body as form/json
        if re.match(r'^/api/tasks/[^/]+/attachments$', path):
            if self._require_auth():
                return
            task_id = path.split('/')[3]
            ctype = self.headers.get('Content-Type', '')
            if 'multipart/form-data' in ctype:
                import cgi
                length = int(self.headers.get('Content-Length', '0'))
                environ = {
                    'REQUEST_METHOD': 'POST',
                    'CONTENT_TYPE': ctype,
                    'CONTENT_LENGTH': str(length),
                }
                form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=environ)
                file_item = form['file'] if 'file' in form else None
                if file_item is None or not getattr(file_item, 'filename', None):
                    return self._json({'error': 'file required'}, 400)
                saved = save_task_attachment(task_id, file_item.filename, file_item.file.read())
                all_attachments = fetch_task_attachments(task_id)
                return self._json({'ok': True, 'filename': saved, 'attachments': all_attachments}, 201)
            return self._json({'error': 'multipart required'}, 400)
        payload = self._read_form_or_json()
        if path == '/login':
            key = client_ip(self)
            if is_login_blocked(key):
                return self._html(render_login_page('Demasiados intentos. Espera unos minutos y vuelve a probar.'), 429)
            username = (payload.get('username') or '').strip()
            password = payload.get('password') or ''
            if hmac.compare_digest(username, NIWA_APP_USERNAME) and hmac.compare_digest(password, NIWA_APP_PASSWORD):
                register_login_attempt(key, True)
                token = build_session_token(username)
                return self._redirect('/', headers={'Set-Cookie': f'{NIWA_APP_SESSION_COOKIE}={token}; Path=/; {_COOKIE_DOMAIN_ATTR}HttpOnly; SameSite=Lax; Max-Age={NIWA_APP_SESSION_TTL_HOURS * 3600}'})
            register_login_attempt(key, False)
            return self._html(render_login_page('Usuario o contraseña incorrectos.'), 401)
        if path.startswith('/api/') and self._require_auth():
            return
        if path == '/api/tasks':
            task_id = create_task(payload)
            return self._json({'ok': True, 'id': task_id}, 201)
        if path == '/api/my-day/tasks':
            task_id = payload.get('task_id')
            if not task_id:
                return self._json({'error': 'task_id required'}, 400)
            add_task_to_my_day(task_id)
            return self._json({'ok': True}, 201)
        if path == '/api/crons/toggle':
            job_id = payload.get('id') or payload.get('job_id', '')
            return self._json(toggle_cron(job_id))
        if path == '/api/crons/toggle-notify':
            job_id = payload.get('id', '')
            return self._json(toggle_cron_delivery(job_id, 'mute'))
        if path == '/api/crons/toggle-format':
            job_id = payload.get('id', '')
            return self._json(toggle_cron_delivery(job_id, 'format'))
        if path == '/api/settings':
            for k, v in payload.items():
                save_setting(k, v)
            return self._json({'ok': True})
        if path == '/api/settings/integrations':
            saved = save_integrations(payload)
            return self._json({'ok': True, 'saved': list(saved.keys())})
        if path == '/api/settings/llm/setup-token':
            token = payload.get('token', '')
            return self._json(apply_setup_token(token))
        if path == '/api/system/restart':
            # Restart the app container — docker will auto-restart it
            import threading
            def _delayed_exit():
                import time; time.sleep(1)
                os._exit(0)
            threading.Thread(target=_delayed_exit, daemon=True).start()
            return self._json({'ok': True, 'message': 'Restarting...'})
        if path == '/api/settings/integrations/test-telegram':
            return self._json(test_telegram())
        if path == '/api/security/scan':
            return self._json(fetch_security())
        if path == '/api/trigger/idle-review':
            return self._json({'ok': True, 'message': 'idle-review trigger queued'})
        if re.match(r'^/api/tasks/[^/]+/reject$', path):
            task_id = path.split('/')[3]
            reason = payload.get('reason', 'Sin motivo especificado')
            with db_conn() as conn:
                task = conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
                if not task:
                    return self._json({'error': 'task_not_found'}, 404)
                old_notes = task['notes'] or ''
                new_notes = old_notes + f'\n[rejected] {reason}' if old_notes else f'[rejected] {reason}'
                conn.execute(
                    "UPDATE tasks SET status='pendiente', assigned_to_claude=0, completed_at=NULL, notes=?, updated_at=? WHERE id=?",
                    (new_notes, now_iso(), task_id),
                )
                record_task_event(conn, task_id, 'status_changed', {'changes': {'status': 'pendiente'}, 'old_status': 'hecha', 'source': 'user_reject', 'reason': reason})
            return self._json({'ok': True})
        if re.match(r'^/api/tasks/[^/]+/labels$', path):
            task_id = path.split('/')[3]
            label = payload.get('label', '').strip()
            if not label:
                return self._json({'error': 'label required'}, 400)
            add_task_label(task_id, label)
            return self._json({'ok': True}, 201)
        if path == '/api/notes':
            note_id = create_note(payload)
            return self._json({'ok': True, 'id': note_id}, 201)
        if path == '/api/routines':
            rid = scheduler.create_routine(db_conn, payload)
            return self._json({'ok': True, 'id': rid}, 201)
        if path == '/api/routines/toggle':
            rid = payload.get('id', '')
            new_state = scheduler.toggle_routine(db_conn, rid)
            if new_state is None:
                return self._json({'error': 'not_found'}, 404)
            return self._json({'ok': True, 'enabled': new_state})
        if path == '/api/routines/run':
            rid = payload.get('id', '')
            routine = scheduler.get_routine(db_conn, rid)
            if not routine:
                return self._json({'error': 'not_found'}, 404)
            if _scheduler:
                import threading as _thr
                _thr.Thread(target=_scheduler._execute_routine, args=(routine,), daemon=True).start()
            return self._json({'ok': True, 'message': f'Routine {rid} queued'})
        return self._json({'error': 'not_found'}, 404)

    def do_PATCH(self):
        path = urlparse(self.path).path
        if self._require_auth():
            return
        payload = self._read_form_or_json()
        if path.startswith('/api/tasks/') and path.count('/') == 3:
            task_id = path.split('/')[3]
            try:
                update_task(task_id, payload)
            except ValueError as exc:
                if str(exc) == 'task_not_found':
                    return self._json({'error': 'task_not_found'}, 404)
                raise
            return self._json({'ok': True})
        if path.startswith('/api/notes/') and path.count('/') == 3:
            note_id = path.split('/')[3]
            try:
                update_note(note_id, payload)
            except ValueError as exc:
                if str(exc) == 'note_not_found':
                    return self._json({'error': 'not_found'}, 404)
                raise
            return self._json({'ok': True})
        if path.startswith('/api/routines/') and path.count('/') == 3:
            routine_id = path.split('/')[3]
            scheduler.update_routine(db_conn, routine_id, payload)
            return self._json({'ok': True})
        return self._json({'error': 'not_found'}, 404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        if self._require_auth():
            return
        if re.match(r'^/api/tasks/[^/]+/labels/[^/]+$', path):
            parts = path.split('/')
            task_id, label = parts[3], urllib.parse.unquote(parts[5])
            remove_task_label(task_id, label)
            return self._json({'ok': True})
        if re.match(r'^/api/tasks/[^/]+/attachments/[^/]+$', path):
            parts = path.split('/')
            task_id, filename = parts[3], urllib.parse.unquote(parts[5])
            delete_task_attachment(task_id, filename)
            return self._json({'ok': True})
        if path.startswith('/api/tasks/') and path.count('/') == 3:
            task_id = path.split('/')[3]
            delete_task(task_id)
            return self._json({'ok': True})
        if path.startswith('/api/my-day/tasks/'):
            task_id = path.split('/')[-1]
            remove_task_from_my_day(task_id)
            return self._json({'ok': True})
        if path.startswith('/api/notes/') and path.count('/') == 3:
            note_id = path.split('/')[3]
            delete_note(note_id)
            return self._json({'ok': True})
        if path.startswith('/api/routines/') and path.count('/') == 3:
            routine_id = path.split('/')[3]
            scheduler.delete_routine(db_conn, routine_id)
            return self._json({'ok': True})
        return self._json({'error': 'not_found'}, 404)

    def log_message(self, format, *args):
        return


if __name__ == '__main__':
    init_db()
    seed_if_empty()
    # Scheduler: init routines table, seed built-ins, start daemon thread
    scheduler.init_routines_table(db_conn)
    seeded = scheduler.seed_builtin_routines(db_conn)
    if seeded:
        logger.info('Seeded %d built-in routines', seeded)
    _scheduler = scheduler.SchedulerThread(db_conn, BASE_DIR.parent)
    _scheduler.start()
    logger.info('Scheduler started (daemon thread)')
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    logger.info(f'Niwa app listening on {HOST}:{PORT}')
    server.serve_forever()
