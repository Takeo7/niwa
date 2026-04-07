#!/usr/bin/env python3
"""
guard_defaults_watchdog.py — Verify critical defaults in app.py are intact.

Checks that DESK_PASSWORD, DESK_SESSION_SECRET, and CLAUDE_BRIDGE_TOKEN
still have non-empty fallback defaults in os.environ.get() calls.
Also checks that no sys.exit() calls were added for missing env vars.

Can run standalone (cron) or be called by other scripts.

Usage:
    python3 guard_defaults_watchdog.py [--fix] [--json]

Exit codes:
    0 = all defaults intact
    1 = violations found (fixed if --fix)
    2 = app.py not found
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

APP_PY = Path(__file__).resolve().parent.parent / 'backend' / 'app.py'

# Critical env var names and their expected non-empty default patterns
# Format: var_name -> regex that matches a valid default (non-empty string)
CRITICAL_DEFAULTS = {
    'DESK_PASSWORD': r"os\.environ\.get\(\s*['\"]DESK_PASSWORD['\"],\s*['\"]([^'\"]+)['\"]\s*\)",
    'DESK_SESSION_SECRET': r"os\.environ\.get\(\s*['\"]DESK_SESSION_SECRET['\"],\s*['\"]([^'\"]+)['\"]\s*\)",
}

# Vars that are only flagged if they EXIST in app.py but with bad defaults
# (not flagged if simply absent — they may live in other files)
OPTIONAL_CRITICAL_DEFAULTS = {
    'CLAUDE_BRIDGE_TOKEN': r"os\.environ\.get\(\s*['\"]CLAUDE_BRIDGE_TOKEN['\"],\s*['\"]([^'\"]+)['\"]\s*\)",
}

# Patterns that should NOT exist in app.py
FORBIDDEN_PATTERNS = [
    # sys.exit for missing env vars
    (r'sys\.exit\(.*(missing|required|not set|env)', 'sys.exit() for missing env var'),
    # Empty string defaults for critical vars
    (r"os\.environ\.get\(\s*['\"]DESK_PASSWORD['\"],\s*['\"]['\"]", 'DESK_PASSWORD blanked to empty'),
    (r"os\.environ\.get\(\s*['\"]DESK_SESSION_SECRET['\"],\s*['\"]['\"]", 'DESK_SESSION_SECRET blanked to empty'),
    (r"os\.environ\.get\(\s*['\"]CLAUDE_BRIDGE_TOKEN['\"],\s*['\"]['\"]", 'CLAUDE_BRIDGE_TOKEN blanked to empty'),
    # raise/exit for env vars
    (r'raise\s+\w*(Error|Exit).*(DESK_PASSWORD|DESK_SESSION_SECRET|CLAUDE_BRIDGE_TOKEN)', 'raise for missing critical var'),
]


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def check_defaults(content):
    """Check that critical defaults are present and non-empty."""
    issues = []

    # Required vars: must exist with non-empty defaults
    for var_name, pattern in CRITICAL_DEFAULTS.items():
        match = re.search(pattern, content)
        if not match:
            if var_name in content:
                issues.append({
                    'type': 'missing_default',
                    'var': var_name,
                    'detail': f'{var_name} exists but has no non-empty default value',
                })
            else:
                issues.append({
                    'type': 'missing_var',
                    'var': var_name,
                    'detail': f'{var_name} not found in app.py — may have been deleted',
                })

    # Optional vars: only flagged if present BUT with bad defaults (not if absent)
    for var_name, pattern in OPTIONAL_CRITICAL_DEFAULTS.items():
        if var_name in content:
            match = re.search(pattern, content)
            if not match:
                issues.append({
                    'type': 'missing_default',
                    'var': var_name,
                    'detail': f'{var_name} exists but has no non-empty default value',
                })

    for pattern, desc in FORBIDDEN_PATTERNS:
        matches = re.findall(pattern, content)
        if matches:
            issues.append({
                'type': 'forbidden_pattern',
                'pattern': desc,
                'detail': f'Found forbidden pattern: {desc}',
            })

    return issues


def fix_via_git_restore():
    """Restore app.py from git HEAD."""
    try:
        result = subprocess.run(
            ['git', 'checkout', 'HEAD', '--', str(APP_PY)],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description='Verify critical defaults in app.py')
    parser.add_argument('--fix', action='store_true', help='Restore app.py from git HEAD if violations found')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()

    if not APP_PY.is_file():
        if args.json:
            print(json.dumps({'ok': False, 'error': 'app.py not found', 'path': str(APP_PY)}))
        else:
            print(f'[defaults-watchdog] ERROR: app.py not found at {APP_PY}')
        sys.exit(2)

    content = APP_PY.read_text()
    issues = check_defaults(content)

    if args.json:
        result = {
            'ok': len(issues) == 0,
            'issues': issues,
            'timestamp': now_iso(),
            'path': str(APP_PY),
        }
        if issues and args.fix:
            restored = fix_via_git_restore()
            result['restored'] = restored
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if not issues:
            print('[defaults-watchdog] OK — all critical defaults intact.')
        else:
            print(f'[defaults-watchdog] VIOLATION — {len(issues)} issue(s):')
            for i in issues:
                print(f'  - {i["detail"]}')
            if args.fix:
                ok = fix_via_git_restore()
                print(f'[defaults-watchdog] {"Restored" if ok else "FAILED to restore"} app.py from HEAD')

    sys.exit(0 if not issues else 1)


if __name__ == '__main__':
    main()
