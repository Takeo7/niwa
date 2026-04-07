#!/usr/bin/env bash
# smoke_test.sh — End-to-end CRUD smoke test for Desk API.
# Usage: bash Desk/tests/smoke_test.sh [base_url]
#   Requires a running Desk backend. Defaults to http://127.0.0.1:8080
set -euo pipefail

BASE="${1:-http://127.0.0.1:8080}"
PASS=0
FAIL=0
HEADER_DUMP=$(mktemp)
trap "rm -f $HEADER_DUMP" EXIT

log_ok()   { echo "  OK: $1"; PASS=$((PASS + 1)); }
log_fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }

check_status() {
    local label="$1" expected="$2" actual="$3"
    if [ "$actual" = "$expected" ]; then
        log_ok "$label (HTTP $actual)"
    else
        log_fail "$label — expected $expected, got $actual"
    fi
}

echo "=== Desk Smoke Test ==="
echo "Target: $BASE"
echo ""

# --- 0. Pre-check: server reachable ---
echo "[0a] Server reachable"
PRE_STATUS=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$BASE/health" 2>/dev/null || echo "000")
if [ "$PRE_STATUS" != "200" ]; then
    echo "  WARN: /health returned $PRE_STATUS — server may be down"
fi

# --- 0b. Login (get session cookie) ---
echo "[0b] Login"
# Auto-detect credentials from Docker container when env vars are not set
_DOCKER_USER=""
_DOCKER_PASS=""
if command -v docker &>/dev/null; then
    _DOCKER_ENV=$(docker inspect isu --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null || true)
    if [ -z "${DESK_USERNAME:-}" ]; then
        _DOCKER_USER=$(echo "$_DOCKER_ENV" | grep '^DESK_USERNAME=' | cut -d= -f2- || true)
    fi
    if [ -z "${DESK_PASSWORD:-}" ]; then
        _DOCKER_PASS=$(echo "$_DOCKER_ENV" | grep '^DESK_PASSWORD=' | cut -d= -f2- || true)
    fi
fi
DESK_USER="${DESK_USERNAME:-${_DOCKER_USER:-arturo}}"
DESK_PASS="${DESK_PASSWORD:-${_DOCKER_PASS:-yume1234}}"
# --max-redirs 0: do NOT follow the 302 redirect so we capture the actual status
STATUS=$(curl -s -o /dev/null -D "$HEADER_DUMP" -w '%{http_code}' \
    --max-redirs 0 \
    -X POST "$BASE/login" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode "username=${DESK_USER}" \
    --data-urlencode "password=${DESK_PASS}")
check_status "POST /login" "302" "$STATUS"
if [ "$STATUS" != "302" ]; then
    echo "  DEBUG: Login failed. User='${DESK_USER}' Base='${BASE}'"
    echo "  DEBUG: Response headers:"
    head -n 5 "$HEADER_DUMP" 2>/dev/null | sed 's/^/    /'
fi

# Extract session token from Set-Cookie header (cookie jar won't work when
# the server sets Domain=.yumewagener.com but we're hitting localhost).
# Strip \r from HTTP headers (CRLF line endings) before parsing.
SESSION_COOKIE=$(tr -d '\r' < "$HEADER_DUMP" | sed -n 's/^Set-Cookie: desk_session=\([^;]*\).*/\1/p' | head -n 1)
if [ -z "$SESSION_COOKIE" ]; then
    log_fail "Could not extract session cookie from login response"
fi
AUTH="-b desk_session=$SESSION_COOKIE"

# --- 1. Health check ---
echo "[1] Health"
STATUS=$(curl -s -o /dev/null -w '%{http_code}' $AUTH "$BASE/health")
check_status "GET /health" "200" "$STATUS"

# --- 2. Create task ---
echo "[2] Create task"
RESPONSE=$(curl -s -w '\n%{http_code}' $AUTH \
    -X POST "$BASE/api/tasks" \
    -H 'Content-Type: application/json' \
    -d '{"title":"Smoke test task","description":"Automated smoke test","area":"personal","priority":"media"}')
STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | sed '$d')
check_status "POST /api/tasks" "201" "$STATUS"

TASK_ID=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
if [ -z "$TASK_ID" ]; then
    log_fail "Could not extract task ID from response"
    echo "Response: $BODY"
fi

# --- 3. Read tasks ---
echo "[3] Read tasks"
STATUS=$(curl -s -o /dev/null -w '%{http_code}' $AUTH "$BASE/api/tasks")
check_status "GET /api/tasks" "200" "$STATUS"

# --- 4. Update task ---
if [ -n "$TASK_ID" ]; then
    echo "[4] Update task"
    STATUS=$(curl -s -o /dev/null -w '%{http_code}' $AUTH \
        -X PATCH "$BASE/api/tasks/$TASK_ID" \
        -H 'Content-Type: application/json' \
        -d '{"status":"en_progreso","priority":"alta"}')
    check_status "PATCH /api/tasks/$TASK_ID" "200" "$STATUS"
fi

# --- 5. Delete task ---
if [ -n "$TASK_ID" ]; then
    echo "[5] Delete task"
    STATUS=$(curl -s -o /dev/null -w '%{http_code}' $AUTH \
        -X DELETE "$BASE/api/tasks/$TASK_ID")
    check_status "DELETE /api/tasks/$TASK_ID" "200" "$STATUS"
fi

# --- 6. Projects ---
echo "[6] Projects"
STATUS=$(curl -s -o /dev/null -w '%{http_code}' $AUTH "$BASE/api/projects")
check_status "GET /api/projects" "200" "$STATUS"

# --- 7. Stats ---
echo "[7] Stats"
STATUS=$(curl -s -o /dev/null -w '%{http_code}' $AUTH "$BASE/api/stats")
check_status "GET /api/stats" "200" "$STATUS"

# --- 8. Settings read ---
echo "[8] Settings"
STATUS=$(curl -s -o /dev/null -w '%{http_code}' $AUTH "$BASE/api/settings")
check_status "GET /api/settings" "200" "$STATUS"

# --- 9. Settings save+read roundtrip ---
echo "[9] Settings roundtrip"
TEST_KEY="__smoke_test_$$"
STATUS=$(curl -s -o /dev/null -w '%{http_code}' $AUTH \
    -X POST "$BASE/api/settings" \
    -H 'Content-Type: application/json' \
    -d "{\"$TEST_KEY\":\"smoke_val\"}")
check_status "POST /api/settings" "200" "$STATUS"

SETTINGS_BODY=$(curl -s $AUTH "$BASE/api/settings")
if echo "$SETTINGS_BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('$TEST_KEY')=='smoke_val'" 2>/dev/null; then
    log_ok "Settings roundtrip verified"
else
    log_fail "Settings roundtrip mismatch"
fi

# Cleanup test key
curl -s -o /dev/null $AUTH \
    -X POST "$BASE/api/settings" \
    -H 'Content-Type: application/json' \
    -d "{\"$TEST_KEY\":\"\"}"

# --- Summary ---
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
