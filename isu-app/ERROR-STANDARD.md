# Error Handling Standard

## API Response Envelope

All API responses use this shape:

```json
// Success
{"ok": true, "data": { ... }}

// Error
{"ok": false, "error": {"code": "NOT_FOUND", "category": "VALIDATION", "message": "Task not found"}}
```

## Error Categories

| Category | HTTP | Retry? | Action |
|----------|------|--------|--------|
| `AUTH` | 401, 403 | No | Redirect to login |
| `VALIDATION` | 400 | No | Show message, user fixes input |
| `NOT_FOUND` | 404 | No | Show "not found" |
| `TRANSIENT` | 429, 502, 503 | Yes | Auto-retry with backoff |
| `SYSTEM` | 500 | No | Log + toast "unexpected error" |

## Error Codes

```
# Auth
UNAUTHORIZED          — 401, missing or invalid session
FORBIDDEN             — 403, valid session but no permission
SESSION_EXPIRED       — 401, session token expired

# Validation
BAD_REQUEST           — 400, malformed request
MISSING_FIELD         — 400, required field absent
INVALID_FORMAT        — 400, field fails validation

# Resources
NOT_FOUND             — 404, entity doesn't exist
CONFLICT              — 409, concurrent modification

# Transient
RATE_LIMITED           — 429, slow down
TIMEOUT               — 504, upstream didn't respond
SERVICE_UNAVAILABLE    — 503, try again later

# System
INTERNAL_ERROR         — 500, unexpected crash
```

## Backend Pattern (app.py)

```python
# Return errors consistently
def _error(self, code, message, status=400):
    self._json({"ok": False, "error": {"code": code, "category": _category(status), "message": message}}, status)

def _category(status):
    if status == 401 or status == 403: return "AUTH"
    if status == 404: return "NOT_FOUND"
    if status == 429 or status >= 502: return "TRANSIENT"
    if status >= 500: return "SYSTEM"
    return "VALIDATION"

# Usage
if not task:
    return self._error("NOT_FOUND", "Task not found", 404)
```

## Frontend Pattern (app.js)

```javascript
async function api(path, opts = {}) {
    const r = await fetch('/api/' + path, {...opts, headers: {'Content-Type': 'application/json'}});
    if (r.status === 401) { window.location.href = '/login'; return null; }
    const data = await r.json().catch(() => null);
    if (!r.ok || (data && !data.ok)) {
        const err = data?.error || {code: 'HTTP_' + r.status, category: r.status >= 500 ? 'SYSTEM' : 'VALIDATION'};
        throw new APIError(err);
    }
    return data?.data ?? data;
}

// Callers
try {
    const task = await api('tasks/' + id);
} catch (e) {
    if (e.isRetryable?.()) { /* auto-retry */ }
    toast(e.message || 'Error inesperado', 'error');
}
```

## Task-Worker Pattern

Errors in task-worker.sh should be categorized when logged:

```python
# Rate limit → TRANSIENT, auto-retry
add_note(conn, task_id, "[execute] TRANSIENT: rate limited, reintentando en 60s")

# Build failure → VALIDATION, needs fix
add_note(conn, task_id, "[test] VALIDATION: build failed — npm run build exit 1")

# Bridge unreachable → TRANSIENT, auto-retry
add_note(conn, task_id, "[execute] TRANSIENT: bridge connection refused")

# Review rejected → VALIDATION, fix loop
add_note(conn, task_id, "[review] VALIDATION: issues found, applying fix")
```

## Rules

1. Never return `null` silently — always throw or log
2. Never swallow exceptions with bare `except: pass`
3. Transient errors get auto-retry (max 3); permanent errors fail immediately
4. User-facing messages are localized; error codes are English enums
5. Every error response includes `code` and `category` at minimum
