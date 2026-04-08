"""Health and monitoring functions extracted from app.py."""
import json as _json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Set by _make_deps() from app.py
_db_conn = None


def _load_health_list(env_var: str) -> list:
    """Parse a JSON env var into a list. Returns [] if unset/invalid."""
    raw = os.environ.get(env_var, '').strip()
    if not raw:
        return []
    try:
        parsed = _json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except _json.JSONDecodeError:
        return []


# ISU_HEALTH_SERVICES env var: JSON array of [name, url, container_name_or_null]
# e.g. '[["Pumicon","http://host:3000","pumicon"],["n8n","http://host:5678","n8n"]]'
_HEALTH_SERVICES = _load_health_list('ISU_HEALTH_SERVICES')

# ISU_HEALTH_TUNNELS env var: JSON array of [hostname, url]
# e.g. '[["app.example.com","https://app.example.com/health"]]'
_HEALTH_TUNNELS = _load_health_list('ISU_HEALTH_TUNNELS')


def _make_deps(db_conn):
    global _db_conn
    _db_conn = db_conn


def fetch_health():
    result = {
        'services': [], 'workers': [], 'tunnel': [],
        'system': {}, 'tasks': {}, 'last_healthcheck': None,
    }

    _host = 'host.docker.internal' if os.path.exists('/.dockerenv') else 'localhost'
    _in_docker = os.path.exists('/.dockerenv')

    _check_services(result, _host)
    _check_tunnels(result)
    _check_workers(result, _host, _in_docker)
    _check_system(result)
    _check_task_pipeline(result)
    _check_git_repos(result, _in_docker)
    _check_backups(result, _in_docker)
    _check_last_healthcheck(result)

    result['checked_at'] = datetime.now(timezone.utc).isoformat()
    return result


def _check_services(result, host):
    # Services are configured via ISU_HEALTH_SERVICES env var.
    # Format: JSON array of [name, url_template, container_name_or_null]
    # url_template may include {host} which is substituted with the host arg.
    # Empty list = no external services to check (only the Niwa app's own health endpoint).
    services = [
        (name, url.replace('{host}', host) if isinstance(url, str) else url, container)
        for name, url, container in _HEALTH_SERVICES
        if isinstance(name, str) and isinstance(url, str)
    ]
    for svc_name, svc_url, container_name in services:
        entry = {'name': svc_name, 'url': svc_url, 'container': container_name}
        t0 = time.time()
        try:
            resp = urllib.request.urlopen(svc_url, timeout=5)
            entry['http_status'] = resp.status
            entry['latency_ms'] = round((time.time() - t0) * 1000)
            entry['ok'] = True
        except urllib.error.HTTPError as he:
            entry['http_status'] = he.code
            entry['latency_ms'] = round((time.time() - t0) * 1000)
            entry['ok'] = he.code < 500
        except Exception:
            entry['http_status'] = 0
            entry['latency_ms'] = -1
            entry['ok'] = False
        if container_name:
            try:
                out = subprocess.run(
                    ['docker', 'inspect', '--format',
                     '{{.State.Status}}|{{.State.StartedAt}}', container_name],
                    capture_output=True, text=True, timeout=5)
                if out.returncode == 0:
                    parts = out.stdout.strip().split('|')
                    entry['container_status'] = parts[0]
                    entry['started_at'] = parts[1] if len(parts) > 1 else ''
                else:
                    entry['container_status'] = 'not_found'
            except Exception:
                entry['container_status'] = 'unknown'
        result['services'].append(entry)


def _check_tunnels(result):
    # Tunnels are configured via ISU_HEALTH_TUNNELS env var (JSON array of [hostname, url]).
    # Empty list = no external tunnels to check.
    tunnels = [
        (host, url) for host, url in _HEALTH_TUNNELS
        if isinstance(host, str) and isinstance(url, str)
    ]
    for hostname, url in tunnels:
        t0 = time.time()
        try:
            resp = urllib.request.urlopen(url, timeout=8)
            result['tunnel'].append({
                'hostname': hostname, 'ok': True,
                'http_status': resp.status,
                'latency_ms': round((time.time() - t0) * 1000),
            })
        except urllib.error.HTTPError as he:
            result['tunnel'].append({
                'hostname': hostname, 'ok': he.code < 500,
                'http_status': he.code,
                'latency_ms': round((time.time() - t0) * 1000),
            })
        except Exception:
            result['tunnel'].append({
                'hostname': hostname, 'ok': False,
                'http_status': 0, 'latency_ms': -1,
            })


def _check_workers(result, host, in_docker):
    workers = [
        ('Niwa Task Executor', 'task-executor'),
        ('Cloudflare Tunnel', 'cloudflared'),
    ]
    for wname, pattern in workers:
        try:
            if in_docker:
                if pattern == 'openclaw gateway':
                    try:
                        urllib.request.urlopen(f'http://{host}:18700/health', timeout=3)
                        running, pid = True, ''
                    except Exception:
                        running, pid = False, None
                elif pattern == 'claude-bridge':
                    try:
                        urllib.request.urlopen(f'http://{host}:18800', timeout=3)
                        running, pid = True, ''
                    except urllib.error.HTTPError:
                        running, pid = True, ''
                    except Exception:
                        running, pid = False, None
                elif pattern == 'cloudflared':
                    running = any(t.get('ok') for t in result['tunnel'])
                    pid = '' if running else None
                else:
                    running, pid = True, ''
            else:
                out = subprocess.run(
                    ['pgrep', '-f', pattern],
                    capture_output=True, text=True, timeout=5)
                running = out.returncode == 0 and bool(out.stdout.strip())
                pid = out.stdout.strip().split('\n')[0] if running else None
        except Exception:
            running = False
            pid = None
        result['workers'].append({'name': wname, 'running': running, 'pid': pid})


def _check_system(result):
    try:
        st = os.statvfs('/')
        total_gb = (st.f_frsize * st.f_blocks) / (1024 ** 3)
        avail_gb = (st.f_frsize * st.f_bavail) / (1024 ** 3)
        result['system']['disk_total_gb'] = round(total_gb, 1)
        result['system']['disk_avail_gb'] = round(avail_gb, 1)
        result['system']['disk_pct'] = round((1 - avail_gb / total_gb) * 100, 1) if total_gb else 0
    except Exception:
        logger.warning("dashboard: failed to read disk stats", exc_info=True)
    try:
        out = subprocess.run(['uptime'], capture_output=True, text=True, timeout=5)
        result['system']['uptime'] = out.stdout.strip() if out.returncode == 0 else ''
    except Exception:
        logger.warning("dashboard: failed to run uptime", exc_info=True)


def _check_task_pipeline(result):
    try:
        with _db_conn() as conn:
            result['tasks']['pending'] = conn.execute(
                "SELECT count(*) FROM tasks WHERE status='pendiente'").fetchone()[0]
            result['tasks']['in_progress'] = conn.execute(
                "SELECT count(*) FROM tasks WHERE status='en_progreso'").fetchone()[0]
            result['tasks']['blocked'] = conn.execute(
                "SELECT count(*) FROM tasks WHERE status='bloqueada'").fetchone()[0]
            result['tasks']['done_today'] = conn.execute(
                "SELECT count(*) FROM tasks WHERE status='hecha' AND date(completed_at)=date('now')").fetchone()[0]
            result['tasks']['total_done'] = conn.execute(
                "SELECT count(*) FROM tasks WHERE status='hecha'").fetchone()[0]
    except Exception:
        pass


def _check_git_repos(result, in_docker):
    """Read project list from the projects table (column `directory`) and check git status."""
    result['git'] = []
    repos = []
    try:
        with _db_conn() as conn:
            for row in conn.execute(
                "SELECT name, directory FROM projects WHERE active = 1 AND directory IS NOT NULL AND directory != ''"
            ):
                repos.append((row['name'], row['directory']))
    except Exception:
        pass
    if not repos:
        return
    for rname, rpath in repos:
        entry = {'name': rname}
        if not os.path.isdir(rpath):
            entry['dirty_files'] = -1
            entry['has_remote'] = False
            entry['last_commit'] = 'dir not accessible'
            result['git'].append(entry)
            continue
        try:
            dirty = subprocess.run(
                ['git', 'status', '--porcelain'], cwd=rpath,
                capture_output=True, text=True, timeout=5)
            entry['dirty_files'] = (
                len([l for l in dirty.stdout.strip().split('\n') if l.strip()])
                if dirty.returncode == 0 and dirty.stdout.strip() else 0
            )
            remote = subprocess.run(
                ['git', 'remote', 'get-url', 'origin'], cwd=rpath,
                capture_output=True, text=True, timeout=5)
            entry['has_remote'] = remote.returncode == 0
            head = subprocess.run(
                ['git', 'log', '--oneline', '-1'], cwd=rpath,
                capture_output=True, text=True, timeout=5)
            entry['last_commit'] = head.stdout.strip()[:60] if head.returncode == 0 else ''
        except Exception:
            entry['dirty_files'] = -1
            entry['has_remote'] = False
            entry['last_commit'] = ''
        result['git'].append(entry)


def _check_backups(result, in_docker):
    try:
        backup_dir = Path(
            os.environ.get('BACKUP_DIR') or
            ('/instance/backups' if in_docker else str(Path.home() / 'backups'))
        )
        backups = sorted(backup_dir.glob('backup-*.tar.gz'), reverse=True)
        result['system']['last_backup'] = backups[0].name if backups else 'none'
        result['system']['last_backup_size'] = backups[0].stat().st_size if backups else 0
    except Exception:
        pass


def _check_last_healthcheck(result):
    try:
        with _db_conn() as conn:
            row = conn.execute(
                "SELECT * FROM healthchecks ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if row:
                result['last_healthcheck'] = dict(row)
    except Exception:
        pass
