# CLAUDE.md -- Isu

Isu (formerly Desk) is the operational dashboard for the Yume platform. It manages tasks, projects, agent status, cron jobs, connections (Google/Outlook), and system health.

## Architecture

- **Backend:** Single Python file (`backend/app.py`, ~2270 lines) using `http.server.BaseHTTPRequestHandler` + `ThreadingHTTPServer`. No framework.
- **Frontend:** Vanilla JavaScript SPA (`frontend/static/app.js`, ~3200 lines) with a single `index.html` entry point and `theme.css` for styling.
- **Database:** SQLite3 (`data/desk.sqlite3`). Schema in `db/schema.sql` with inline migrations in `init_db()`.
- **No dependencies beyond Python stdlib** (no pip install needed).

## Key Files

| Path | Purpose |
|------|---------|
| `backend/app.py` | All routes, models, helpers, and server startup |
| `backend/history.py` | Task history query module (imported lazily) |
| `frontend/index.html` | SPA shell, loads app.js |
| `frontend/static/app.js` | All frontend logic, routing, rendering |
| `frontend/theme.css` | CSS variables and global styles |
| `frontend/i18n.js` | Internationalization strings |
| `db/schema.sql` | SQLite schema definition |
| `config/agents.json` | Agent metadata (names, roles, descriptions) |
| `config/sandbox.json` | Sandbox security configuration |
| `data/settings.json` | User settings (persisted by the API) |
| `scripts/desk_change_flow.sh` | Deploy flow: validate, commit, recreate container |
| `scripts/desk_close_task.py` | Close a Desk task with deploy verification |
| `scripts/validate_desk.py` | Pre-commit validation script |
| `scripts/guard_protected_files.py` | Pre-commit guard for protected files |
| `scripts/guard_defaults_watchdog.py` | Watches for unintended default value changes |
| `scripts/sandbox_enforcer.py` | Runtime sandbox security enforcement |
| `infra/docker-compose.yml` | Docker Compose for deployment |
| `tests/smoke_test.sh` | Basic smoke tests |

## How to Test Changes

1. **Backend changes:** Restart the container: `docker restart isu`
2. **Frontend changes:** Hard-refresh the browser (Cmd+Shift+R). The backend serves files with `Cache-Control: no-cache` but the browser may still cache.
3. **Smoke test:** Run `tests/smoke_test.sh` or use curl:
   ```bash
   curl -s http://localhost:8080/health          # should return {"ok":true}
   curl -s http://localhost:8080/api/dashboard    # needs auth cookie
   ```
4. **Database reset:** Delete `data/desk.sqlite3` and restart. `init_db()` + `seed_if_empty()` recreate everything.

## Protected Files

These files have guards that prevent accidental modification:

- `scripts/guard_protected_files.py` -- enforces a list of protected paths
- `scripts/guard_defaults_watchdog.py` -- prevents reverting env defaults (usernames, passwords, secrets)
- `scripts/pre-commit-guard.sh` -- pre-commit hook runner

Do NOT modify protected files without explicit user approval.

## Standards

- **Error handling:** Follow `ERROR-STANDARD.md` — all API errors must return `{ok: false, error: {code, category, message}}`. Categories: AUTH, VALIDATION, NOT_FOUND, TRANSIENT, SYSTEM.
- **Refactoring:** See `REFACTOR-PLAN.md` for the planned extraction of `app.py` (backend) and `app.js` (frontend Phase 5).

## Common Gotchas

1. **Cache busting:** Frontend JS/CSS may be cached by the browser even though the server sends `no-cache`. Always hard-refresh after changes. If deploying, consider adding a query param bust to script tags in `index.html`.

2. **settings.json vs DB:** Settings are merged from two sources -- `data/settings.json` (file) and the `settings` table in SQLite. The POST endpoint writes to the JSON file only. The GET merges both, with DB values overriding file values.

3. **Desk deploy closure:** Tasks belonging to `proj-desk` cannot be marked as `hecha` unless the notes contain the marker `desk-deploy:verified`. This is enforced in `update_task()`. Use `scripts/desk_close_task.py` or add the marker manually.

4. **Agent info enrichment:** Tasks are enriched with `active_agent` and `completed_by_agent` from two external files: `agents-state.json` and `delegations.json` in the workspace runtime directory. These files are written by the OpenClaw orchestrator, not by Desk.

5. **OAuth secrets:** Google/Outlook OAuth credentials come from env vars (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, etc.). Without them, connection OAuth flows will fail with `oauth_not_configured`.

6. **history.py is lazy-imported:** The `/api/tasks/history` route imports `history.py` at call time, not at startup. If that file is missing, the route will 500.

7. **Single-file monolith:** Both `app.py` and `app.js` are large single files. When editing, search for the route path or function name rather than scrolling. Use `do_GET`, `do_POST`, `do_PATCH`, `do_DELETE` as anchors in the backend.

8. **Database migrations:** New tables/columns are created inline in `init_db()` using `CREATE TABLE IF NOT EXISTS` and `INSERT OR IGNORE`. There is also a `db/migrations/` directory for more structured migrations.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DESK_PORT` | 8080 | Server port |
| `DESK_DB_PATH` | `data/desk.sqlite3` | SQLite path |
| `DESK_USERNAME` | arturo | Login username |
| `DESK_PASSWORD` | yume1234 | Login password |
| `DESK_AUTH_REQUIRED` | 1 | Set to 0 to disable auth |
| `DESK_SESSION_SECRET` | (dev default) | HMAC secret for sessions |
| `DESK_SESSION_TTL_HOURS` | 168 | Session lifetime (7 days) |
| `DESK_PUBLIC_BASE_URL` | http://127.0.0.1:8080 | Used for OAuth callback URLs |
| `GOOGLE_CLIENT_ID` | (empty) | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | (empty) | Google OAuth client secret |
| `MICROSOFT_CLIENT_ID` | (empty) | Microsoft OAuth client ID |
| `MICROSOFT_CLIENT_SECRET` | (empty) | Microsoft OAuth client secret |
| `MICROSOFT_TENANT_ID` | common | Azure AD tenant |
