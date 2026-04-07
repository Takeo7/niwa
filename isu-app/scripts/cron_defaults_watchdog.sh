#!/usr/bin/env bash
# cron_defaults_watchdog.sh — Periodic check that app.py critical defaults are intact.
# If violations found, auto-reverts app.py from git HEAD and logs the incident.
#
# Install in crontab:
#   Managed via launchd: com.yume.arturo.defaults-watchdog

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCHDOG="$SCRIPT_DIR/guard_defaults_watchdog.py"
GUARD="$SCRIPT_DIR/guard_protected_files.py"
LOG="/tmp/defaults-watchdog.log"
REPO_TOP="$(git -C "$SCRIPT_DIR/../.." rev-parse --show-toplevel)"

cd "$REPO_TOP"

# 1. Check critical defaults in app.py
RESULT=$(python3 "$WATCHDOG" --fix --json 2>/dev/null || true)
OK=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ok', False))" 2>/dev/null || echo "False")

if [[ "$OK" != "True" ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%S)] VIOLATION detected and fixed:"
    echo "$RESULT"

    # Also run the full guard with revert
    python3 "$GUARD" --revert --project-path Desk --json 2>/dev/null || true
fi

# 2. Quick check: ensure app.py hasn't been staged with dangerous changes
STAGED_DIFF=$(git diff --cached -- Desk/backend/app.py 2>/dev/null || true)
if [[ -n "$STAGED_DIFF" ]]; then
    # Check for dangerous patterns in staged changes
    if echo "$STAGED_DIFF" | grep -qE '^\+.*(DESK_PASSWORD|DESK_SESSION_SECRET|CLAUDE_BRIDGE_TOKEN)\s*=\s*["'"'"']?["'"'"']?\s*$'; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%S)] DANGER: staged diff blanks critical defaults — unstaging app.py"
        git reset HEAD -- Desk/backend/app.py 2>/dev/null || true
        git checkout HEAD -- Desk/backend/app.py 2>/dev/null || true
    fi
    if echo "$STAGED_DIFF" | grep -qE '^\+.*sys\.exit\(.*(missing|required|not set|must be set)'; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%S)] DANGER: staged diff adds sys.exit for env vars — unstaging app.py"
        git reset HEAD -- Desk/backend/app.py 2>/dev/null || true
        git checkout HEAD -- Desk/backend/app.py 2>/dev/null || true
    fi
fi
