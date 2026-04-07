# Desk Refactor Plan

## Current State

### Backend: `backend/app.py` (~2270 lines)

One monolithic file containing:
- Configuration and constants (lines 1-53)
- Auth helpers: session tokens, cookies, rate limiting (lines 95-290)
- Agent/delegation helpers (lines 300-370)
- Task CRUD and query functions (lines 373-700)
- My Day functions (lines 706-731)
- OAuth configuration and token management (lines 733-1066)
- External API helpers: Google Calendar, Gmail (lines 1068-1231)
- Cron job management (lines 1234-1720)
- Settings, search, KPIs, pipeline analytics (lines 1427-1684)
- Health, security, logs (lines 1283-1385)
- File upload/attachment management (lines 1743-1791)
- HTTP Handler class with all routes (lines 1812-2263)
  - `do_GET`: ~35 route branches
  - `do_POST`: ~18 route branches
  - `do_PATCH`: 2 route branches
  - `do_DELETE`: 5 route branches

### Frontend: `frontend/static/app.js` (~3200 lines)

One monolithic file containing:
- All view rendering (dashboard, kanban, tasks, projects, agents, crons, settings, etc.)
- State management (global state object)
- API client functions
- DOM manipulation and event handling
- Routing (hash-based SPA router)
- Real-time polling (live-state change detection)

### Also: `backend/history.py` (separate module, lazy-imported)

Already extracted -- good precedent for further extraction.

---

## Proposed Backend Structure

```
backend/
  app.py              -- Entrypoint: server startup, Handler class (routing only)
  config.py           -- Constants, env vars, paths
  db.py               -- db_conn(), init_db(), seed_if_empty()
  auth.py             -- Session management, login, rate limiting, is_authenticated()
  routes/
    __init__.py
    tasks.py           -- /api/tasks, /api/tasks/:id, /api/search, /api/tasks/history
    projects.py        -- /api/projects
    dashboard.py       -- /api/dashboard, /api/my-day, /api/stats, /api/activity
    agents.py          -- /api/agents-status, /api/flows
    connections.py     -- /api/connections, OAuth start/callback, /api/google/sync
    crons.py           -- /api/crons, toggle, toggle-notify, toggle-format
    settings.py        -- /api/settings, /api/config
    system.py          -- /health, /api/health/full, /api/security, /api/logs, /api/metrics
    kpis.py            -- /api/kpis, /api/dashboard/pipeline
    labels.py          -- /api/tasks/:id/labels
    attachments.py     -- /api/tasks/:id/attachments
  models/
    __init__.py
    tasks.py           -- fetch_tasks(), create_task(), update_task(), delete_task(), search_tasks()
    projects.py        -- fetch_projects()
    day_focus.py       -- fetch_my_day(), add_task_to_my_day(), remove_task_from_my_day()
    connections.py     -- CRUD, OAuth helpers, token management
    crons.py           -- fetch_crons(), toggle_cron(), toggle_cron_delivery()
    agents.py          -- fetch_agents_status(), load_delegations_index(), enrich_tasks_with_agent_info()
    calendar.py        -- sync_google_calendar(), fetch_calendar_events()
    email.py           -- fetch_gmail_summary()
    health.py          -- fetch_health(), fetch_security(), fetch_logs()
    stats.py           -- fetch_stats(), fetch_kpis(), fetch_pipeline()
    settings.py        -- fetch_settings(), save_setting(), fetch_config()
    labels.py          -- fetch_task_labels(), add_task_label(), remove_task_label()
    attachments.py     -- fetch/save/delete task attachments
  utils/
    __init__.py
    time.py            -- now_iso(), _parse_dt()
    http.py            -- fetch_url_json()
    events.py          -- record_task_event(), fetch_task_timelines(), fetch_activity()
  history.py           -- Already separate (keep as-is)
```

### Routing Pattern

Replace the chain of `if path == ...` branches with a routing table:

```python
# In app.py Handler class
ROUTES = {
    ('GET', '/api/tasks'): tasks_routes.list_tasks,
    ('POST', '/api/tasks'): tasks_routes.create_task,
    # ... etc
}

# Regex routes for parameterized paths
REGEX_ROUTES = [
    ('PATCH', r'^/api/tasks/([^/]+)$', tasks_routes.update_task),
    ('DELETE', r'^/api/tasks/([^/]+)$', tasks_routes.delete_task),
    # ... etc
]
```

Each route handler receives `(handler, params, qs, payload)` and returns by calling `handler._json()` or `handler._html()`.

---

## Proposed Frontend Structure

```
frontend/
  index.html
  theme.css
  i18n.js
  static/
    app.js              -- Entrypoint: router, init, global state
    modules/
      api.js            -- All API client functions
      router.js         -- Hash-based SPA routing
      state.js          -- Global state management, polling
      views/
        dashboard.js    -- Dashboard view
        kanban.js       -- Kanban board view
        tasks.js        -- Task list, detail, create/edit
        projects.js     -- Projects list and detail
        agents.js       -- Agent status view
        crons.js        -- Cron jobs view
        connections.js  -- Connections/OAuth view
        settings.js     -- Settings view
        security.js     -- Security panel
        health.js       -- Health/system view
        logs.js         -- Log viewer
        kpis.js         -- KPIs dashboard
      components/
        task-card.js    -- Reusable task card component
        modal.js        -- Modal dialog
        toast.js        -- Toast notifications
        sidebar.js      -- Navigation sidebar
```

Use ES modules (`import`/`export`) with a simple bundling step or native browser ESM support.

---

## Migration Strategy

### Principle: Extract one group at a time, keep app.py working at every step.

### Phase 1: Backend foundation (low risk)

1. Extract `config.py` -- move all constants and env var reads
2. Extract `db.py` -- move `db_conn()`, `init_db()`, `seed_if_empty()`
3. Extract `utils/time.py` and `utils/http.py`
4. Update `app.py` imports. Run smoke test.

### Phase 2: Models (medium risk)

5. Extract `models/tasks.py` -- move `fetch_tasks()`, `create_task()`, `update_task()`, `delete_task()`, `search_tasks()`, `get_task()`
6. Extract `models/projects.py`
7. Extract `models/day_focus.py`
8. Extract `models/stats.py` -- `fetch_stats()`, `fetch_kpis()`, `fetch_pipeline()`
9. Extract `models/connections.py` -- all connection CRUD and OAuth helpers
10. Extract `models/agents.py` -- agent status, delegations
11. Extract `models/health.py`, `models/settings.py`, `models/crons.py`
12. Run smoke test after each extraction.

### Phase 3: Auth (medium risk)

13. Extract `auth.py` -- session tokens, login logic, rate limiting, `is_authenticated()`
14. Update Handler._require_auth() to use imported auth module.

### Phase 4: Routes (medium risk)

15. Create `routes/` package
16. Extract one route group at a time (start with the simplest: `routes/system.py`)
17. Build a routing table in Handler
18. Migrate remaining route groups one by one
19. Handler.do_GET/POST/PATCH/DELETE become thin dispatchers

### Phase 5: Frontend modularization (`app.js` — 3202 lines)

**Current state**: Single monolithic file with 122 global functions, HTML via string
concatenation, global state object `S`, naive 15s polling, no module system.

**Step 5a: Foundation modules (1-2 hours)**

20. Extract `modules/api.js` — centralize `fetch()` wrapper with standard error envelope:
    ```javascript
    // Standard error response: {ok, error: {code, category, message}}
    // Categories: TRANSIENT (retry), VALIDATION (user fix), AUTH (re-login), SYSTEM (report)
    export async function api(path, opts) { ... }
    export class APIError extends Error { isRetryable() {...} }
    ```
21. Extract `modules/state.js` — state store with getter/setter + event emitter:
    ```javascript
    export const state = { ...S };  // Move from global S
    export function setState(key, value) { state[key] = value; emit('change', key); }
    export function on(event, handler) { ... }
    ```
22. Extract `modules/router.js` — hash routing + lazy view loading:
    ```javascript
    const ROUTES = { dashboard: loadDashboard, kanban: loadKanban, ... };
    export function navigate(view) { ... }
    ```
23. Extract `modules/utils.js` — `escHtml()`, `escJsAttr()`, `fmtDuration()`, status label helpers

**Step 5b: View extraction (3-4 hours, one at a time)**

24. Extract `modules/views/system.js` (626 lines) — largest, least coupled, good first target
25. Extract `modules/views/projects.js` (573 lines)
26. Extract `modules/views/kanban.js` (275 lines)
27. Extract `modules/views/dashboard.js` (322 lines)
28. Extract `modules/views/history.js` (165 lines)
29. Extract `modules/views/kpis.js` (86 lines)
30. Extract remaining: `calendar.js`, `email.js`, `connections.js`, `agents.js`

**Step 5c: Components (1-2 hours)**

31. Extract `modules/components/task-modal.js` (200 lines) — used across views
32. Extract `modules/components/task-card.js` — render function reused in kanban/history/dashboard
33. Extract `modules/components/toast.js` + `modules/components/search.js`

**Step 5d: Integration (1 hour)**

34. Update `app.js` to be a thin entrypoint: imports + init + keyboard shortcuts
35. Migrate `<script>` tags to `<script type="module">`
36. Test all views, verify polling, verify login flow

**Priority order**: 5a (foundation) → 5b (system view first) → 5c → 5d
**Each step must pass**: manual click-through of affected views + smoke_test.sh

### Testing at Each Step

- Run `tests/smoke_test.sh` after every extraction
- Curl all major endpoints: `/health`, `/api/dashboard`, `/api/tasks`, `/api/settings`
- Verify login flow works
- Check the frontend loads and renders correctly

### Estimated Effort

| Phase | Files created | Risk | Effort |
|-------|--------------|------|--------|
| Phase 1 | 4 | Low | 1-2 hours |
| Phase 2 | 8 | Medium | 3-4 hours |
| Phase 3 | 1 | Medium | 1 hour |
| Phase 4 | 8-10 | Medium | 3-4 hours |
| Phase 5 | 10-12 | Medium | 4-6 hours |

Total: ~12-17 hours of focused work, or ~3-4 sessions.
