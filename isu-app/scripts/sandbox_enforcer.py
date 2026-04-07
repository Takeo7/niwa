#!/usr/bin/env python3
"""
sandbox_enforcer.py — Filesystem-level sandbox for task-worker.

Provides real-time protection by making protected files read-only (chmod),
so Claude Code literally cannot write to them even with --dangerously-skip-permissions.

Modes:
    --lock      Make all protected files read-only (run before task execution)
    --unlock    Restore write permissions (for manual intervention only)
    --check     Verify sandbox integrity (exit 0=ok, 1=violations)
    --watch     Continuous enforcement loop (for cron/daemon)
    --json      Output results as JSON

Usage:
    python3 sandbox_enforcer.py --lock
    python3 sandbox_enforcer.py --unlock   # requires ALLOW_PROTECTED_WRITE=1
    python3 sandbox_enforcer.py --check --json
    python3 sandbox_enforcer.py --watch --interval 30

This script reads config/sandbox.json for the protected files list.
"""
import argparse
import json
import os
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DESK_DIR = SCRIPT_DIR.parent
CONFIG_PATH = DESK_DIR / 'config' / 'sandbox.json'
LOG_PATH = DESK_DIR / 'data' / 'sandbox-enforcer.log'
WORKSPACE_ROOT = Path(os.environ.get('YUME_BASE', '/opt/yume/instances/arturo'))


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def log(msg, to_file=True):
    ts = now_iso()
    line = f"[{ts}] {msg}"
    print(line, file=sys.stderr)
    if to_file:
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_PATH, 'a') as f:
                f.write(line + '\n')
        except Exception:
            pass


def load_config():
    """Load sandbox configuration from config/sandbox.json."""
    if not CONFIG_PATH.is_file():
        log(f"ERROR: config not found at {CONFIG_PATH}")
        sys.exit(2)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def resolve_protected_files(config):
    """Resolve protected file paths relative to Desk directory."""
    files = []
    for rel in config.get('protected_files', []):
        path = (DESK_DIR / rel).resolve()
        if path.is_file():
            files.append(path)
    return files


def resolve_protected_directories(config):
    """Resolve protected directory paths."""
    dirs = []
    for rel in config.get('protected_directories', []):
        path = (DESK_DIR / rel).resolve()
        if path.is_dir():
            dirs.append(path)
    return dirs


def is_readonly(filepath):
    """Check if a file is read-only for owner."""
    try:
        st = os.stat(filepath)
        return not (st.st_mode & stat.S_IWUSR)
    except OSError:
        return False


def make_readonly(filepath):
    """Remove write permission from file (owner, group, other)."""
    try:
        st = os.stat(filepath)
        # Remove write bits, keep read and execute
        new_mode = st.st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        os.chmod(filepath, new_mode)
        return True
    except OSError as e:
        log(f"ERROR: cannot chmod {filepath}: {e}")
        return False


def make_writable(filepath):
    """Restore write permission for owner only."""
    try:
        st = os.stat(filepath)
        new_mode = st.st_mode | stat.S_IWUSR
        os.chmod(filepath, new_mode)
        return True
    except OSError as e:
        log(f"ERROR: cannot restore {filepath}: {e}")
        return False


def cmd_lock(config, json_output=False):
    """Lock all protected files (make read-only)."""
    files = resolve_protected_files(config)
    results = []
    for f in files:
        was_ro = is_readonly(f)
        if was_ro:
            results.append({'file': str(f), 'action': 'already_locked'})
        else:
            ok = make_readonly(f)
            results.append({
                'file': str(f),
                'action': 'locked' if ok else 'error',
            })
            if ok:
                log(f"LOCKED: {f}")

    if json_output:
        print(json.dumps({
            'ok': True,
            'action': 'lock',
            'files': results,
            'timestamp': now_iso(),
        }, indent=2))
    else:
        locked = sum(1 for r in results if r['action'] == 'locked')
        already = sum(1 for r in results if r['action'] == 'already_locked')
        errors = sum(1 for r in results if r['action'] == 'error')
        print(f"[sandbox] Lock: {locked} locked, {already} already locked, {errors} errors")


def cmd_unlock(config, json_output=False):
    """Unlock protected files (restore write). Requires ALLOW_PROTECTED_WRITE=1."""
    if os.environ.get('ALLOW_PROTECTED_WRITE') != '1':
        msg = "DENIED: set ALLOW_PROTECTED_WRITE=1 to unlock protected files"
        if json_output:
            print(json.dumps({'ok': False, 'error': msg}))
        else:
            print(f"[sandbox] {msg}")
        sys.exit(1)

    files = resolve_protected_files(config)
    results = []
    for f in files:
        ok = make_writable(f)
        results.append({
            'file': str(f),
            'action': 'unlocked' if ok else 'error',
        })
        if ok:
            log(f"UNLOCKED: {f} (manual override)")

    if json_output:
        print(json.dumps({
            'ok': True,
            'action': 'unlock',
            'files': results,
            'timestamp': now_iso(),
        }, indent=2))
    else:
        unlocked = sum(1 for r in results if r['action'] == 'unlocked')
        print(f"[sandbox] Unlock: {unlocked} files unlocked")


def cmd_check(config, json_output=False):
    """Check sandbox integrity: verify all protected files are read-only."""
    files = resolve_protected_files(config)
    violations = []
    ok_files = []

    for f in files:
        if is_readonly(f):
            ok_files.append(str(f))
        else:
            violations.append(str(f))

    # Check directory boundaries
    boundary_ok = True
    workspace = config.get('allowed_workspace', str(WORKSPACE_ROOT))
    protected_dirs = resolve_protected_directories(config)

    result = {
        'clean': len(violations) == 0,
        'protected_files_total': len(files),
        'locked': len(ok_files),
        'unlocked_violations': violations,
        'protected_dirs': [str(d) for d in protected_dirs],
        'workspace_boundary': workspace,
        'timestamp': now_iso(),
    }

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        if violations:
            print(f"[sandbox] VIOLATIONS: {len(violations)} protected files are writable:")
            for v in violations:
                print(f"  - {v}")
        else:
            print(f"[sandbox] OK: all {len(files)} protected files are read-only")

    return len(violations) == 0


def cmd_watch(config, interval=30, json_output=False):
    """Continuous enforcement: re-lock any protected file that becomes writable."""
    log(f"Starting sandbox watch (interval={interval}s)")
    print(f"[sandbox] Watch mode started, checking every {interval}s. Ctrl+C to stop.")

    while True:
        files = resolve_protected_files(config)
        relocked = []

        for f in files:
            if not is_readonly(f):
                ok = make_readonly(f)
                if ok:
                    relocked.append(str(f))
                    log(f"WATCH-RELOCK: {f}")

        if relocked:
            msg = f"[sandbox-watch] Re-locked {len(relocked)} files: {', '.join(Path(r).name for r in relocked)}"
            log(msg)
            if not json_output:
                print(msg)

        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            log("Watch stopped by user")
            break


def cmd_status(config, json_output=False):
    """Show full sandbox status report."""
    files = resolve_protected_files(config)
    file_status = []
    for f in files:
        ro = is_readonly(f)
        file_status.append({
            'file': str(f),
            'name': f.name,
            'locked': ro,
            'exists': f.is_file(),
        })

    result = {
        'enforce_readonly': config.get('enforce_readonly', True),
        'total_protected': len(files),
        'locked_count': sum(1 for fs in file_status if fs['locked']),
        'unlocked_count': sum(1 for fs in file_status if not fs['locked']),
        'files': file_status,
        'config_path': str(CONFIG_PATH),
        'timestamp': now_iso(),
    }

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        print(f"[sandbox] Status report ({now_iso()})")
        print(f"  Config: {CONFIG_PATH}")
        print(f"  Enforce readonly: {config.get('enforce_readonly', True)}")
        print(f"  Protected files: {len(files)}")
        locked = sum(1 for fs in file_status if fs['locked'])
        print(f"  Locked: {locked}/{len(files)}")
        if locked < len(files):
            print("  UNLOCKED files:")
            for fs in file_status:
                if not fs['locked']:
                    print(f"    - {fs['name']} ({fs['file']})")


def main():
    parser = argparse.ArgumentParser(
        description='Filesystem-level sandbox enforcer for task-worker'
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--lock', action='store_true',
                       help='Make protected files read-only')
    group.add_argument('--unlock', action='store_true',
                       help='Restore write permissions (requires ALLOW_PROTECTED_WRITE=1)')
    group.add_argument('--check', action='store_true',
                       help='Verify sandbox integrity')
    group.add_argument('--watch', action='store_true',
                       help='Continuous enforcement loop')
    group.add_argument('--status', action='store_true',
                       help='Show full sandbox status')

    parser.add_argument('--json', action='store_true',
                        help='Output as JSON')
    parser.add_argument('--interval', type=int, default=30,
                        help='Watch interval in seconds (default: 30)')

    args = parser.parse_args()

    config = load_config()

    if not config.get('enforce_readonly', True):
        if args.json:
            print(json.dumps({'ok': True, 'skipped': True,
                              'reason': 'enforce_readonly disabled in config'}))
        else:
            print("[sandbox] enforce_readonly is disabled in config. No action taken.")
        sys.exit(0)

    if args.lock:
        cmd_lock(config, args.json)
    elif args.unlock:
        cmd_unlock(config, args.json)
    elif args.check:
        ok = cmd_check(config, args.json)
        sys.exit(0 if ok else 1)
    elif args.watch:
        cmd_watch(config, args.interval, args.json)
    elif args.status:
        cmd_status(config, args.json)


if __name__ == '__main__':
    main()
