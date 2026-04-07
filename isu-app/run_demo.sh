#!/usr/bin/env bash
# run_demo.sh — Launch Desk backend+frontend with a single command.
# Usage: cd Desk && bash run_demo.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

BACKEND_PID=""

cleanup() {
    echo ""
    echo "Shutting down..."
    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        kill "$BACKEND_PID" 2>/dev/null || true
        wait "$BACKEND_PID" 2>/dev/null || true
    fi
    echo "Done."
}
trap cleanup EXIT INT TERM

PORT="${DESK_PORT:-8080}"
HOST="${DESK_HOST:-127.0.0.1}"

# Seed demo data if DB is empty
echo "Seeding demo data (if needed)..."
python3 backend/seed.py 2>/dev/null || true

# Launch backend (serves both API and frontend static files)
echo "Starting Desk backend on ${HOST}:${PORT}..."
DESK_HOST="$HOST" DESK_PORT="$PORT" python3 backend/app.py &
BACKEND_PID=$!

sleep 1

if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "ERROR: Backend failed to start."
    exit 1
fi

echo ""
echo "============================================"
echo "  Desk is running!"
echo "  Open: http://${HOST}:${PORT}"
echo "  Default login: arturo / yume1234"
echo "  Press Ctrl+C to stop."
echo "============================================"
echo ""

wait "$BACKEND_PID"
