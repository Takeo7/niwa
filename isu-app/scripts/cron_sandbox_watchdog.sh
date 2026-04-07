#!/usr/bin/env bash
# cron_sandbox_watchdog.sh — Periodic sandbox enforcement for task-worker.
#
# Ensures protected files remain read-only at all times.
# Designed to run as a cron job every 1-5 minutes.
#
# Install:
#   crontab -e
#   Managed via launchd: com.yume.arturo.sandbox-watchdog
#
# What it does:
#   1. Runs sandbox_enforcer.py --lock to ensure all protected files are read-only
#   2. Runs sandbox_enforcer.py --check to verify integrity
#   3. If violations found, logs and optionally notifies via Telegram

set -euo pipefail

DESK_DIR="/opt/yume/instances/arturo/.openclaw/workspace/Desk"
ENFORCER="${DESK_DIR}/scripts/sandbox_enforcer.py"
TTS_NOTIFY="/opt/yume/instances/arturo/.openclaw/workspace/scripts/tts_notify.py"
LOG_FILE="${DESK_DIR}/data/sandbox-cron.log"

# Ensure data dir exists
mkdir -p "${DESK_DIR}/data"

# Step 1: Lock all protected files
python3 "$ENFORCER" --lock 2>/dev/null || true

# Step 2: Check integrity
CHECK_OUTPUT=$(python3 "$ENFORCER" --check --json 2>/dev/null || true)
IS_CLEAN=$(echo "$CHECK_OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print('yes' if d.get('clean') else 'no')" 2>/dev/null || echo "error")

if [ "$IS_CLEAN" = "no" ]; then
    VIOLATIONS=$(echo "$CHECK_OUTPUT" | python3 -c "
import sys,json
d=json.load(sys.stdin)
v=d.get('unlocked_violations',[])
print(', '.join(v) if v else 'unknown')
" 2>/dev/null || echo "unknown")

    MSG="[sandbox-watchdog] ALERTA: archivos protegidos sin bloqueo detectados: ${VIOLATIONS}"
    echo "$(date -u +%Y-%m-%dT%H:%M:%S) $MSG"

    # Re-lock immediately
    python3 "$ENFORCER" --lock 2>/dev/null || true

    # Notify via tts_notify (respects notification_format: text/audio/both)
    if [ -f "$TTS_NOTIFY" ]; then
        python3 "$TTS_NOTIFY" "🔒 ${MSG}" 2>/dev/null || true
    fi
elif [ "$IS_CLEAN" = "yes" ]; then
    # Silent on success, only log every 10th run to avoid log bloat
    MINUTE=$(date +%M)
    if [ "$((MINUTE % 10))" = "0" ]; then
        echo "$(date -u +%Y-%m-%dT%H:%M:%S) [sandbox-watchdog] OK — all protected files locked"
    fi
fi
