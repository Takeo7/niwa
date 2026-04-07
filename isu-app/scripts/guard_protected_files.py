#!/usr/bin/env python3
"""
guard_protected_files.py — Post-execution gate for task-worker.

Checks git diff for unauthorized modifications to protected files.
If any protected file was modified, reverts those specific changes
and logs the violation.

Usage:
    python3 guard_protected_files.py [--revert] [--project-path Desk]

Exit codes:
    0 = clean (no protected files touched)
    1 = violation detected (reverted if --revert)
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_PROTECTED_FILES = [
    'backend/app.py',
    'docker-compose.yml',
    'Dockerfile',
    '.env',
    'openclaw.json',
    'auth-profiles.json',
    'send_audio_raw.sh',
    'send_audio.sh',
    'security-audit.py',
    'prompt_injection_scan.py',
    'task-worker.sh',
    'task-executor.sh',
    'schema.sql',
]

# Load from centralized config if available, fall back to hardcoded list
_SANDBOX_CONFIG = Path(__file__).resolve().parent.parent / 'config' / 'sandbox.json'


def _load_protected_files():
    """Load protected files list from sandbox.json, with hardcoded fallback."""
    try:
        if _SANDBOX_CONFIG.is_file():
            with open(_SANDBOX_CONFIG) as f:
                cfg = json.load(f)
            # Use repo-level paths for git diff matching
            repo_paths = cfg.get('protected_files_repo_paths', [])
            if repo_paths:
                return repo_paths
            # Fallback to relative paths → extract basenames
            rel_paths = cfg.get('protected_files', [])
            if rel_paths:
                return [Path(p).name for p in rel_paths]
    except (json.JSONDecodeError, OSError):
        pass
    return _DEFAULT_PROTECTED_FILES


PROTECTED_FILES = _load_protected_files()

# Critical env var names whose defaults must never be blanked
CRITICAL_DEFAULTS = [
    'DESK_PASSWORD',
    'DESK_SESSION_SECRET',
    'CLAUDE_BRIDGE_TOKEN',
]

# Patterns that should never appear in added lines of diffs
_CRIT_JOINED = "|".join(CRITICAL_DEFAULTS)
DANGEROUS_PATTERNS = [
    # Blanking critical defaults: os.environ.get('DESK_PASSWORD', '') -> empty fallback
    r"os\.environ\.get\(\s*['\"](" + _CRIT_JOINED + r")['\"],\s*['\"]['\"]?\s*\)",
    # os.environ['VAR'] without fallback (will raise KeyError)
    r"os\.environ\[[\'\"](" + _CRIT_JOINED + r")[\'\"]\]",
    # os.getenv('VAR') with no default or empty default
    r"os\.getenv\(\s*['\"](" + _CRIT_JOINED + r")['\"](\s*,\s*['\"]['\"])?\s*\)",
    # Adding sys.exit for missing env vars in app startup
    r'sys\.exit\(.*(missing|required|not set|must be set|undefined|no encontrad).*\)',
    # raise SystemExit / raise RuntimeError for missing env vars (must reference env/config/variable context)
    r'raise\s+(SystemExit|RuntimeError|ValueError)\(.*(missing|required|not set|must be set).*(env|config|variable|DESK_|CLAUDE_|SECRET|TOKEN|PASSWORD).*\)',
    # Direct assignment to empty for critical vars
    r"(" + _CRIT_JOINED + r")\s*=\s*['\"]['\"]?\s*$",
    # Direct assignment to None for critical vars
    r"(" + _CRIT_JOINED + r")\s*=\s*None\s*$",
    # if not VAR: sys.exit / raise pattern (kills app when env var missing but has default)
    r"if\s+not\s+(" + _CRIT_JOINED + r").*:\s*(sys\.exit|raise|exit)\s*\(",
]


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def get_repo_root():
    result = subprocess.run(
        ['git', 'rev-parse', '--show-toplevel'],
        capture_output=True, text=True
    )
    return result.stdout.strip()


WORKSPACE_ROOT = os.environ.get('YUME_BASE', '/opt/yume/instances/arturo')


def get_changed_files(project_path):
    """Get list of modified files (staged + unstaged) in the project."""
    result = subprocess.run(
        ['git', 'diff', '--name-only', 'HEAD', '--', project_path],
        capture_output=True, text=True
    )
    staged = set(result.stdout.strip().split('\n')) if result.stdout.strip() else set()

    result2 = subprocess.run(
        ['git', 'diff', '--name-only', '--', project_path],
        capture_output=True, text=True
    )
    unstaged = set(result2.stdout.strip().split('\n')) if result2.stdout.strip() else set()

    # Also check uncommitted new files
    result3 = subprocess.run(
        ['git', 'status', '--porcelain', '--', project_path],
        capture_output=True, text=True
    )
    all_changed = staged | unstaged
    for line in result3.stdout.strip().split('\n'):
        if line.strip():
            # Format: XY filename
            fname = line[3:].strip()
            all_changed.add(fname)

    return all_changed


def get_all_changed_files():
    """Get ALL changed files across the entire repo (for boundary checking)."""
    result = subprocess.run(
        ['git', 'diff', '--name-only', 'HEAD'],
        capture_output=True, text=True
    )
    files = set(result.stdout.strip().split('\n')) if result.stdout.strip() else set()

    result2 = subprocess.run(
        ['git', 'diff', '--name-only'],
        capture_output=True, text=True
    )
    files |= set(result2.stdout.strip().split('\n')) if result2.stdout.strip() else set()

    result3 = subprocess.run(
        ['git', 'status', '--porcelain'],
        capture_output=True, text=True
    )
    for line in result3.stdout.strip().split('\n'):
        if line.strip():
            fname = line[3:].strip()
            files.add(fname)

    files.discard('')
    return files


def get_diff_content(filepath):
    """Get the actual diff for a file."""
    result = subprocess.run(
        ['git', 'diff', 'HEAD', '--', filepath],
        capture_output=True, text=True
    )
    if result.stdout:
        return result.stdout
    # Try unstaged
    result2 = subprocess.run(
        ['git', 'diff', '--', filepath],
        capture_output=True, text=True
    )
    return result2.stdout


def check_dangerous_patterns(changed_files, project_path):
    """Check if any changed file introduces dangerous patterns."""
    violations = []
    for filepath in changed_files:
        diff = get_diff_content(filepath)
        if not diff:
            continue
        # Only check added lines
        added_lines = [l[1:] for l in diff.split('\n') if l.startswith('+') and not l.startswith('+++')]
        for line in added_lines:
            for pattern in DANGEROUS_PATTERNS:
                if re.search(pattern, line):
                    violations.append({
                        'file': filepath,
                        'line': line.strip(),
                        'pattern': pattern,
                    })
    return violations


def revert_file(filepath):
    """Revert a specific file to HEAD state."""
    subprocess.run(['git', 'checkout', 'HEAD', '--', filepath], capture_output=True)


def _re_lock_protected_files():
    """Re-lock protected files via sandbox_enforcer after a revert."""
    enforcer = Path(__file__).resolve().parent / 'sandbox_enforcer.py'
    if enforcer.is_file():
        try:
            subprocess.run(
                ['python3', str(enforcer), '--lock'],
                capture_output=True, timeout=10,
            )
            print("[guard] Protected files re-locked via sandbox_enforcer", file=sys.stderr)
        except Exception as e:
            print(f"[guard] Warning: could not re-lock files: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='Guard protected files against unauthorized changes')
    parser.add_argument('--revert', action='store_true', help='Revert protected file changes automatically')
    parser.add_argument('--project-path', default='Desk', help='Relative project path within repo')
    parser.add_argument('--json', action='store_true', help='Output results as JSON')
    args = parser.parse_args()

    repo_root = get_repo_root()
    if not repo_root:
        print("Error: not in a git repository", file=sys.stderr)
        sys.exit(2)

    changed = get_changed_files(args.project_path)

    # Check 1: Protected files touched
    protected_violations = []
    for f in changed:
        basename = Path(f).name
        relpath = f
        for pf in PROTECTED_FILES:
            if basename == Path(pf).name or relpath.endswith(pf):
                protected_violations.append(f)
                break

    # Check 2: Dangerous patterns in any changed file
    pattern_violations = check_dangerous_patterns(changed, args.project_path)

    # Check 3: Workspace boundary — files outside the allowed workspace
    boundary_violations = []
    try:
        all_files = get_all_changed_files()
        for f in all_files:
            abs_path = str(Path(repo_root) / f)
            if not abs_path.startswith(WORKSPACE_ROOT):
                boundary_violations.append(f)
    except Exception:
        pass

    # Check 4: Verify critical defaults in app.py are intact (content-level check)
    defaults_violations = []
    try:
        import importlib.util
        watchdog_path = Path(__file__).parent / 'guard_defaults_watchdog.py'
        if watchdog_path.is_file():
            spec = importlib.util.spec_from_file_location('guard_defaults_watchdog', watchdog_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if mod.APP_PY.is_file():
                content = mod.APP_PY.read_text()
                defaults_violations = mod.check_defaults(content)
    except Exception:
        pass

    has_violations = bool(protected_violations) or bool(pattern_violations) or bool(boundary_violations) or bool(defaults_violations)

    if args.json:
        print(json.dumps({
            'clean': not has_violations,
            'protected_files_modified': protected_violations,
            'dangerous_patterns': pattern_violations,
            'boundary_violations': boundary_violations,
            'defaults_violations': defaults_violations,
            'timestamp': now_iso(),
        }, indent=2, ensure_ascii=False))
    else:
        if protected_violations:
            print(f"[guard] VIOLACIÓN: archivos protegidos modificados: {', '.join(protected_violations)}")
        if pattern_violations:
            print(f"[guard] VIOLACIÓN: patrones peligrosos detectados:")
            for v in pattern_violations:
                print(f"  - {v['file']}: {v['line'][:100]}")
        if boundary_violations:
            print(f"[guard] VIOLACIÓN: archivos fuera del workspace: {', '.join(boundary_violations)}")
        if defaults_violations:
            print(f"[guard] VIOLACIÓN: defaults críticos alterados en app.py:")
            for d in defaults_violations:
                print(f"  - {d['detail']}")
        if not has_violations:
            print("[guard] OK — ningún archivo protegido modificado, sin patrones peligrosos, dentro del workspace.")

    if has_violations and args.revert:
        _revert_out = sys.stderr if args.json else sys.stdout
        for f in protected_violations:
            print(f"[guard] Revirtiendo {f}", file=_revert_out)
            revert_file(f)
        if pattern_violations:
            reverted_files = set()
            for v in pattern_violations:
                if v['file'] not in reverted_files:
                    print(f"[guard] Revirtiendo {v['file']} (patrón peligroso)", file=_revert_out)
                    revert_file(v['file'])
                    reverted_files.add(v['file'])
        for f in boundary_violations:
            print(f"[guard] Revirtiendo {f} (fuera del workspace)", file=_revert_out)
            revert_file(f)
        if defaults_violations:
            # Revert app.py to restore critical defaults
            app_py_rel = str(Path(args.project_path) / 'backend' / 'app.py')
            print(f"[guard] Revirtiendo {app_py_rel} (defaults críticos alterados)", file=_revert_out)
            revert_file(app_py_rel)

        # Re-lock protected files after revert to prevent further tampering
        _re_lock_protected_files()

    sys.exit(0 if not has_violations else 1)


if __name__ == '__main__':
    main()
