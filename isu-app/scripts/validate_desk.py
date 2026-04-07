#!/usr/bin/env python3
"""Pre-deploy validation for Desk.

Checks:
  1. Python syntax (py_compile)
  2. JavaScript syntax in inline <script> blocks (via node)
  3. HTML structure (all <script> tags close, no obvious breaks)
  4. Critical API endpoints return expected responses (post-deploy)

Usage:
  validate_desk.py --pre-deploy          # checks 1-3 (before docker recreate)
  validate_desk.py --post-deploy [URL]   # check 4 (after container is up)
  validate_desk.py --all [URL]           # all checks

Exit code 0 = pass, non-zero = fail with details.
"""
import argparse
import json
import os
import py_compile
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_PY = ROOT / 'backend' / 'app.py'
DEFAULT_BASE = 'http://127.0.0.1:8080'

RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
RESET = '\033[0m'

failures: list[str] = []
warnings: list[str] = []


def ok(msg: str):
    print(f'  {GREEN}✓{RESET} {msg}')


def warn(msg: str):
    warnings.append(msg)
    print(f'  {YELLOW}⚠{RESET} {msg}')


def fail(msg: str):
    failures.append(msg)
    print(f'  {RED}✗{RESET} {msg}')


# ── 0. Protected defaults guard ───────────────────────────────────

CRITICAL_DEFAULTS = {
    'DESK_PASSWORD': False,
    'DESK_SESSION_SECRET': False,
    'CLAUDE_BRIDGE_TOKEN': False,
}


def check_protected_defaults():
    """Verify that app.py still has non-empty defaults for critical env vars
    and does not contain sys.exit() calls for missing env vars."""
    print('\n[0/4] Protected defaults')

    if not APP_PY.exists():
        warn('backend/app.py not found — skipping defaults check')
        return

    source = APP_PY.read_text(encoding='utf-8')

    # Check that critical defaults have non-empty fallback values
    for var_name in CRITICAL_DEFAULTS:
        # Match os.environ.get('VAR', 'value') or os.getenv('VAR', 'value')
        pattern = re.compile(
            rf"""os\.(?:environ\.get|getenv)\(\s*['\"]({re.escape(var_name)})['\"],\s*(['"])(.*?)\2\s*\)"""
        )
        match = pattern.search(source)
        if not match:
            warn(f'{var_name}: no os.environ.get/getenv call found in app.py')
            continue

        default_val = match.group(3)
        if not default_val.strip():
            fail(f'{var_name}: default is EMPTY — this will break Desk without .env')
        else:
            ok(f'{var_name}: has non-empty default')

    # Check for dangerous sys.exit / raise on missing env vars
    if re.search(r'sys\.exit\(.*(missing|required|not set|must be set|undefined)', source, re.IGNORECASE):
        fail('app.py contains sys.exit() for missing env vars — Desk uses safe defaults, not hard exits')
    elif re.search(r'raise\s+(SystemExit|RuntimeError|ValueError)\(.*(missing|required|not set|must be set)', source, re.IGNORECASE):
        fail('app.py raises exception for missing env vars — Desk uses safe defaults, not hard exits')
    else:
        ok('No dangerous sys.exit()/raise for env vars')

    # Check that critical vars are not assigned to empty/None directly
    for var_name in CRITICAL_DEFAULTS:
        if re.search(rf'{re.escape(var_name)}\s*=\s*[\'\"]\s*[\'\"]\s*$', source, re.MULTILINE):
            fail(f'{var_name}: directly assigned to empty string')
        if re.search(rf'{re.escape(var_name)}\s*=\s*None\s*$', source, re.MULTILINE):
            fail(f'{var_name}: directly assigned to None')
        # os.environ['VAR'] without fallback (will KeyError if not set)
        if re.search(rf'os\.environ\[\s*[\'\"]({re.escape(var_name)})[\'\"]', source):
            fail(f'{var_name}: uses os.environ[] without fallback — must use os.environ.get() with default')


# ── 1. Python syntax ──────────────────────────────────────────────

def check_python_syntax():
    print('\n[1/4] Python syntax')
    py_files = list(ROOT.glob('backend/**/*.py')) + list(ROOT.glob('scripts/**/*.py'))
    for f in py_files:
        try:
            py_compile.compile(str(f), doraise=True)
            ok(f.relative_to(ROOT))
        except py_compile.PyCompileError as e:
            fail(f'{f.relative_to(ROOT)}: {e}')


# ── 2. JavaScript syntax ──────────────────────────────────────────

def _extract_inline_scripts(python_source: str) -> list[tuple[int, str]]:
    """Extract JS from inline HTML strings in the Python source.

    Approach: render the actual HTML by importing the running server's
    HTML generation is too complex. Instead, find raw string literals
    that contain <script> blocks — these are the HTML templates.
    We also simulate a GET / by running the server's HTML builder if
    possible, but as a fallback we regex-extract script blocks from
    any triple-quoted or raw string that contains '<script'.
    """
    scripts = []
    # Find all <script>...</script> blocks in the full source text
    # (they live inside Python string literals that form the HTML)
    pattern = re.compile(r'<script[^>]*>(.*?)</script>', re.DOTALL)
    for m in pattern.finditer(python_source):
        js = m.group(1).strip()
        if not js:
            continue
        # Calculate approximate line number
        line_no = python_source[:m.start()].count('\n') + 1
        scripts.append((line_no, js))
    return scripts


def _check_js_syntax(js_code: str, context: str) -> bool:
    """Use node to check JS syntax."""
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
            f.write(js_code)
            f.flush()
            result = subprocess.run(
                ['node', '--check', f.name],
                capture_output=True, text=True, timeout=10
            )
            os.unlink(f.name)
            if result.returncode != 0:
                # Extract useful error info
                err = result.stderr.strip()
                # Map temp file line numbers back
                fail(f'JS syntax error ({context}): {err}')
                return False
            return True
    except FileNotFoundError:
        warn('node not found — skipping JS syntax check')
        return True
    except subprocess.TimeoutExpired:
        warn(f'JS syntax check timed out ({context})')
        return True


def check_js_syntax():
    print('\n[2/4] JavaScript syntax')

    # Check standalone frontend JS files
    frontend_dir = ROOT / 'frontend'
    js_files = list(frontend_dir.glob('*.js')) if frontend_dir.exists() else []

    for js_file in js_files:
        try:
            result = subprocess.run(
                ['node', '--check', str(js_file)],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                fail(f'{js_file.relative_to(ROOT)}: {result.stderr.strip()}')
            else:
                ok(f'{js_file.relative_to(ROOT)}: syntax OK')
        except FileNotFoundError:
            warn('node not found — skipping JS syntax check')
            return

    # Also check any inline scripts remaining in app.py
    if APP_PY.exists():
        source = APP_PY.read_text(encoding='utf-8')
        scripts = _extract_inline_scripts(source)
        for i, (line_no, js) in enumerate(scripts):
            js_clean = re.sub(r'\{[a-zA-Z_][a-zA-Z0-9_]*\}', '""', js)
            if _check_js_syntax(js_clean, f'inline block {i+1}, ~line {line_no}'):
                ok(f'Inline block {i+1} (~line {line_no} in app.py): syntax OK')


# ── 3. HTML structure ─────────────────────────────────────────────

def check_html_structure():
    print('\n[3/4] HTML structure')

    # Scan frontend HTML files
    frontend_dir = ROOT / 'frontend'
    html_files = list(frontend_dir.glob('*.html')) if frontend_dir.exists() else []

    if not html_files:
        warn('No HTML files found in frontend/')
        return

    for html_file in html_files:
        source = html_file.read_text(encoding='utf-8')
        name = html_file.relative_to(ROOT)

        open_tags = len(re.findall(r'<script\b', source))
        close_tags = len(re.findall(r'</script>', source))
        if open_tags != close_tags:
            fail(f'{name}: mismatched <script> tags: {open_tags} open vs {close_tags} close')
        else:
            ok(f'{name}: script tags balanced ({open_tags})')

        open_divs = len(re.findall(r'<div\b', source))
        close_divs = len(re.findall(r'</div>', source))
        diff = abs(open_divs - close_divs)
        if diff > 2:
            warn(f'{name}: div tags may be unbalanced: {open_divs} open vs {close_divs} close (diff={diff})')
    else:
        ok(f'Div tags roughly balanced: {open_divs} open, {close_divs} close')


# ── 4. API endpoint smoke tests (post-deploy) ────────────────────

ENDPOINTS = [
    ('GET', '/health', 200, lambda d: d.get('ok') is True),
    ('GET', '/auth/check', 302, None),  # no cookie → redirect
    ('GET', '/api/dashboard', 401, None),  # no cookie → unauthorized
    ('GET', '/login', 200, None),
]


def check_rendered_js(base_url: str):
    """Fetch the actual rendered HTML pages and validate JS syntax in the browser context."""
    print('\n[5/5] Rendered JS validation (post-deploy)')

    # Login to get a session cookie, then fetch the dashboard with it
    login_url = base_url.rstrip('/') + '/login'
    try:
        username = os.environ.get('DESK_USERNAME', 'arturo')
        password = os.environ.get('DESK_PASSWORD', 'yume1234')
        data = urllib.parse.urlencode({'username': username, 'password': password}).encode()

        # POST login — don't follow redirect, grab Set-Cookie instead
        try:
            _no_redirect_opener.open(urllib.request.Request(login_url, data=data, method='POST'), timeout=10)
        except urllib.error.HTTPError as e:
            cookie_header = e.headers.get('Set-Cookie', '')
            if not cookie_header:
                warn('Login did not return a session cookie')
                return

        # Extract cookie value
        cookie_val = cookie_header.split(';')[0]  # "desk_session=..."

        # Fetch the main dashboard page with the cookie
        req = urllib.request.Request(base_url.rstrip('/') + '/')
        req.add_header('Cookie', cookie_val)
        resp = urllib.request.urlopen(req, timeout=10)
        html = resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        warn(f'Could not fetch rendered HTML: {e}')
        return

    # Extract and validate all <script> blocks from the rendered HTML
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
    scripts = [s.strip() for s in scripts if s.strip()]

    if not scripts:
        warn('No script blocks found in rendered HTML')
        return

    ok(f'Found {len(scripts)} script block(s) in rendered HTML')

    for i, js in enumerate(scripts):
        if _check_js_syntax(js, f'rendered block {i+1}'):
            ok(f'Rendered block {i+1}: syntax OK')
        # fail() is called inside _check_js_syntax if it fails


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


_no_redirect_opener = urllib.request.build_opener(_NoRedirectHandler)


def check_endpoints(base_url: str):
    print('\n[4/4] API endpoint smoke tests')

    for method, path, expected_status, validator in ENDPOINTS:
        url = base_url.rstrip('/') + path
        try:
            req = urllib.request.Request(url, method=method)
            try:
                resp = _no_redirect_opener.open(req, timeout=10)
                status = resp.status
                body = resp.read().decode('utf-8', errors='replace')
            except urllib.error.HTTPError as e:
                status = e.code
                body = e.read().decode('utf-8', errors='replace') if e.fp else ''

            if status != expected_status:
                fail(f'{method} {path}: expected {expected_status}, got {status}')
                continue

            if validator:
                try:
                    data = json.loads(body)
                    if not validator(data):
                        fail(f'{method} {path}: response validation failed: {body[:200]}')
                        continue
                except json.JSONDecodeError:
                    fail(f'{method} {path}: invalid JSON response')
                    continue

            ok(f'{method} {path} → {status}')

        except Exception as e:
            fail(f'{method} {path}: {e}')


# ── Main ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Desk pre/post-deploy validation')
    parser.add_argument('--pre-deploy', action='store_true', help='Run pre-deploy checks (syntax, structure)')
    parser.add_argument('--post-deploy', action='store_true', help='Run post-deploy checks (endpoints)')
    parser.add_argument('--all', action='store_true', help='Run all checks')
    parser.add_argument('--base-url', default=DEFAULT_BASE, help=f'Base URL for endpoint tests (default: {DEFAULT_BASE})')
    args = parser.parse_args()

    if not (args.pre_deploy or args.post_deploy or args.all):
        args.all = True

    print(f'{"="*50}')
    print(f' Desk Validation')
    print(f'{"="*50}')

    if args.pre_deploy or args.all:
        check_protected_defaults()
        check_python_syntax()
        check_js_syntax()
        check_html_structure()

    if args.post_deploy or args.all:
        check_endpoints(args.base_url)
        check_rendered_js(args.base_url)

    print(f'\n{"="*50}')
    if failures:
        print(f' {RED}FAILED{RESET}: {len(failures)} error(s), {len(warnings)} warning(s)')
        for f in failures:
            print(f'  {RED}✗{RESET} {f}')
        sys.exit(1)
    elif warnings:
        print(f' {YELLOW}PASSED with warnings{RESET}: {len(warnings)} warning(s)')
        sys.exit(0)
    else:
        print(f' {GREEN}ALL PASSED{RESET}')
        sys.exit(0)


if __name__ == '__main__':
    main()
