"""Health and monitoring functions extracted from app.py."""
import json as _json
import logging
import os
import shutil
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
                if pattern == 'cloudflared':
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


# ─── Readiness (PR-A5) ───────────────────────────────────────────────
#
# fetch_readiness() aggregates the local prerequisites for running a
# task end-to-end. It deliberately does NOT make outbound calls:
# the widget polls this endpoint periodically and hitting Anthropic /
# OpenAI on every poll would burn subscription tokens per user.
# "reachable" therefore means "we have credentials, a model and a CLI
# command locally — a run has a chance to start". A real network
# probe is out of scope for PR-A5.

# Slug → service key used to build settings keys (``svc.llm.<key>.*``).
# Unknown slugs fall through to ``auth_mode='api_key'`` /
# ``has_credential=False``.
_BACKEND_SERVICE_KEY = {
    'claude_code': 'anthropic',
    'codex': 'openai',
}

# Which oauth_tokens.provider row backs an ``auth_mode=oauth`` flow
# for each service.  Only openai is wired in v0.2.
_SERVICE_OAUTH_PROVIDER = {
    'openai': 'openai',
}


def _is_docker_ok():
    if os.path.exists('/.dockerenv'):
        return True
    try:
        import shutil
        return shutil.which('docker') is not None
    except Exception:
        return False


def _check_admin():
    """Admin credentials OK when password is set and not the default.

    Reads env vars dynamically (not the app module cache) so tests can
    monkeypatch via ``monkeypatch.setenv`` without reloading ``app``.
    """
    username = os.environ.get('NIWA_APP_USERNAME', 'admin')
    password = os.environ.get('NIWA_APP_PASSWORD', 'change-me')
    if not username:
        return False, 'NIWA_APP_USERNAME is empty'
    if not password or password == 'change-me':
        return False, 'using default credentials (change NIWA_APP_PASSWORD)'
    return True, f'admin user: {username}'


def _read_settings_and_state():
    """Fetch settings, backend_profiles and oauth providers in one pass.

    Returns ``(settings_dict, profiles_list, oauth_providers_set,
    db_ok)``. Any exception degrades to empty data + ``db_ok=False``.
    """
    try:
        with _db_conn() as conn:
            settings = {
                row['key']: row['value']
                for row in conn.execute('SELECT key, value FROM settings')
            }
            profiles = [
                dict(r) for r in conn.execute(
                    "SELECT slug, display_name, enabled, default_model "
                    "FROM backend_profiles ORDER BY priority DESC, slug ASC"
                )
            ]
            oauth_providers = {
                r['provider'] for r in conn.execute(
                    'SELECT provider FROM oauth_tokens'
                )
            }
        return settings, profiles, oauth_providers, True
    except Exception:
        logger.exception('readiness: failed to read db state')
        return {}, [], set(), False


def _llm_command_set(settings):
    """True when any LLM CLI command is configured locally.

    ``settings.value`` is nullable in the DB, so the dict may hold
    ``None`` for an explicitly-cleared key — normalize via ``or ''``.
    """
    if (settings.get('int.llm_command') or '').strip():
        return True
    return bool(os.environ.get('NIWA_LLM_COMMAND', '').strip())


def _summarize_backend(profile, settings, oauth_providers, command_ok):
    slug = profile['slug']
    service_key = _BACKEND_SERVICE_KEY.get(slug)
    enabled = bool(profile['enabled'])
    default_model = profile['default_model']
    model_present = bool(default_model)

    if service_key is None:
        auth_mode = 'api_key'
        has_credential = False
    else:
        auth_mode = (
            settings.get(f'svc.llm.{service_key}.auth_method') or 'api_key'
        )
        if auth_mode == 'api_key':
            has_credential = bool(
                (settings.get(f'svc.llm.{service_key}.api_key') or '').strip()
            )
        elif auth_mode == 'setup_token':
            has_credential = bool(
                (settings.get(f'svc.llm.{service_key}.setup_token') or '').strip()
            )
        elif auth_mode == 'oauth':
            oauth_key = _SERVICE_OAUTH_PROVIDER.get(service_key)
            has_credential = bool(oauth_key and oauth_key in oauth_providers)
        else:
            has_credential = False

    reachable = bool(
        enabled and has_credential and model_present and command_ok
    )

    summary = {
        'slug': slug,
        'display_name': profile.get('display_name') or slug,
        'enabled': enabled,
        'has_credential': has_credential,
        'auth_mode': auth_mode,
        'model_present': model_present,
        'default_model': default_model,
        'reachable': reachable,
    }

    # FIX-20260419 (Bug 33): expose a live CLI probe alongside the
    # static creds/model snapshot for the Claude backend. Only runs
    # for ``claude_code`` — Codex has its own surface in PR-A7.
    if slug == 'claude_code':
        try:
            binary = (
                (settings.get('int.llm_command') or '').strip()
                or os.environ.get('NIWA_LLM_COMMAND', '').strip()
                or None
            )
            raw_probe = probe_claude_cli(explicit_binary=binary)
            summary['claude_probe'] = classify_claude_probe(
                raw_probe, has_credential=has_credential,
            )
        except Exception:
            logger.exception('readiness: claude probe failed')
            summary['claude_probe'] = {
                'status': 'error',
                'detail': 'probe failed unexpectedly; see server logs',
                'checked_at': datetime.now(timezone.utc).isoformat(),
                'binary': None,
            }

    return summary


# ── Claude CLI live probe (FIX-20260419 — Bug 33) ─────────────────
#
# probe_claude_cli runs ``claude -p --output-format stream-json`` with
# an empty prompt to distinguish a healthy CLI (at least one
# non-system event emitted) from the credential-expired case (exit 0,
# empty stream, empty stderr — see docs/plans/FIX-20260419-
# bug33-credential-check.md). Result is cached for _CLAUDE_PROBE_TTL
# seconds so /api/readiness polling does not fork a subprocess on
# every request.

_CLAUDE_PROBE_CACHE: dict = {"value": None, "at": 0.0, "binary": None}
_CLAUDE_PROBE_TTL = 30.0


def _resolve_claude_binary(explicit: str | None = None) -> str | None:
    """Locate the ``claude`` CLI binary or return None.

    Priority:
      1. ``explicit`` argument when given (settings > env at caller).
      2. ``NIWA_LLM_COMMAND`` env var.
      3. ``shutil.which("claude")``.

    A candidate is only accepted when it points at an existing,
    executable file on disk. An explicit path that does not resolve
    returns None (surface as ``no_cli`` — do not silently fall back
    to ``which``, otherwise the user never sees the misconfig).
    """
    if explicit is not None:
        explicit = explicit.strip()
        if not explicit:
            return None
        return explicit if (
            os.path.isfile(explicit) and os.access(explicit, os.X_OK)
        ) else None

    env_cmd = os.environ.get("NIWA_LLM_COMMAND", "").strip()
    if env_cmd:
        return env_cmd if (
            os.path.isfile(env_cmd) and os.access(env_cmd, os.X_OK)
        ) else None
    return shutil.which("claude")


def _probe_stream_is_empty(stdout: bytes, stderr: bytes) -> bool:
    """True when the stdout carried no informative event.

    Mirrors the adapter-side rule used by Bug 33 classification: a
    bare ``system`` frame does not count; non-JSON output does.
    """
    if stderr and stderr.strip():
        return False
    for raw in stdout.splitlines():
        s = raw.strip()
        if not s:
            continue
        try:
            msg = _json.loads(s)
        except (_json.JSONDecodeError, ValueError):
            return False
        if msg.get("type") != "system":
            return False
    return True


def probe_claude_cli(*, timeout: float = 10.0, force: bool = False,
                    explicit_binary: str | None = None,
                    _clock=None) -> dict:
    """Spawn ``claude -p --output-format stream-json`` and classify.

    Returns a dict ``{status, detail, checked_at, binary}`` where
    status is one of:
      - ``"ok"``: emitted at least one non-system event.
      - ``"no_cli"``: binary not resolvable / not executable.
      - ``"credential_error"``: exit 0 with empty / bare-system
        stream and empty stderr. Callers may refine to
        ``credential_missing`` / ``credential_expired`` through
        :func:`classify_claude_probe`.
      - ``"error"``: non-zero exit or timeout or unexpected failure.

    Cached in-process for ``_CLAUDE_PROBE_TTL`` seconds per binary
    path. ``force=True`` bypasses the cache (UI refresh button).
    """
    clock = _clock or time.time
    now = clock()
    binary = _resolve_claude_binary(explicit_binary)
    cache = _CLAUDE_PROBE_CACHE
    if (not force
            and cache["value"] is not None
            and cache["binary"] == binary
            and (now - cache["at"]) < _CLAUDE_PROBE_TTL):
        return cache["value"]

    if binary is None:
        result = {
            "status": "no_cli",
            "detail": (
                "claude CLI not found. Install the Anthropic CLI or "
                "set NIWA_LLM_COMMAND to the absolute path."
            ),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "binary": None,
        }
    else:
        try:
            out = subprocess.run(
                [binary, "-p", "--output-format", "stream-json"],
                input=b"",
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            result = {
                "status": "error",
                "detail": f"claude probe timed out after {timeout}s",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "binary": binary,
            }
        except OSError as exc:
            result = {
                "status": "no_cli",
                "detail": f"cannot execute {binary}: {exc}",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "binary": binary,
            }
        else:
            if out.returncode != 0:
                stderr = (out.stderr or b"").decode(
                    "utf-8", errors="replace",
                )
                result = {
                    "status": "error",
                    "detail": (
                        f"exit {out.returncode}: "
                        f"{stderr.strip()[:200] or 'no stderr'}"
                    ),
                    "checked_at":
                        datetime.now(timezone.utc).isoformat(),
                    "binary": binary,
                }
            elif _probe_stream_is_empty(out.stdout or b"",
                                        out.stderr or b""):
                result = {
                    "status": "credential_error",
                    "detail": (
                        "claude exited 0 without emitting events; "
                        "credentials are likely expired or malformed"
                    ),
                    "checked_at":
                        datetime.now(timezone.utc).isoformat(),
                    "binary": binary,
                }
            else:
                result = {
                    "status": "ok",
                    "detail": "claude CLI responded with events",
                    "checked_at":
                        datetime.now(timezone.utc).isoformat(),
                    "binary": binary,
                }

    cache["value"] = result
    cache["at"] = now
    cache["binary"] = binary
    return result


def classify_claude_probe(raw: dict, *, has_credential: bool) -> dict:
    """Refine a raw probe result using readiness-side signals.

    The raw probe only sees the CLI exit shape, so it cannot tell
    "no credential configured" from "configured but expired". The
    readiness handler does know ``has_credential`` (from settings +
    oauth_tokens) and calls this helper to split the generic
    ``credential_error`` into:

      - ``credential_missing``: the user never pasted a token.
      - ``credential_expired``: the user has a token in settings but
        the CLI fails to use it.

    ``ok``, ``no_cli`` and ``error`` pass through unchanged.
    """
    refined = dict(raw)
    if raw.get("status") == "credential_error":
        refined["status"] = (
            "credential_expired" if has_credential else "credential_missing"
        )
    return refined


def _check_hosting():
    domain = (os.environ.get('NIWA_HOSTING_DOMAIN') or '').strip()
    if domain:
        return True, f'NIWA_HOSTING_DOMAIN={domain}'
    caddyfile = Path(
        os.environ.get('NIWA_HOSTING_CADDYFILE') or '/tmp/niwa-hosting-Caddyfile'
    )
    try:
        if caddyfile.is_file() and caddyfile.stat().st_size > 0:
            return True, f'caddyfile present at {caddyfile}'
    except Exception:
        pass
    return False, 'no hosting domain and no caddyfile found'


def fetch_readiness():
    """Aggregate local readiness for the MVP happy path.

    Never hits the network. Degrades gracefully when the DB is
    unavailable: individual ``*_ok`` flags flip to False instead of
    raising, so the caller can always 200 the response.
    """
    settings, profiles, oauth_providers, db_ok = _read_settings_and_state()
    admin_ok, admin_detail = _check_admin()
    hosting_ok, hosting_detail = _check_hosting()
    command_ok = _llm_command_set(settings)
    backends = [
        _summarize_backend(p, settings, oauth_providers, command_ok)
        for p in profiles
    ]
    return {
        'docker_ok': _is_docker_ok(),
        'db_ok': db_ok,
        'admin_ok': admin_ok,
        'admin_detail': admin_detail,
        'backends': backends,
        'hosting_ok': hosting_ok,
        'hosting_detail': hosting_detail,
        'checked_at': datetime.now(timezone.utc).isoformat(),
    }
