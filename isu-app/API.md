# Desk API Reference

Base URL: `http://localhost:8080` (configurable via `DESK_PORT`)

All `/api/*` endpoints require session authentication unless noted otherwise.
Authentication is cookie-based (`desk_session`). Set `DESK_AUTH_REQUIRED=0` to disable.

---

## Auth

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/login` | No | Renders login HTML page. Redirects to `/` if already authenticated. |
| POST | `/login` | No | Authenticates with `username` + `password` (form or JSON). Sets session cookie on success. Rate-limited per IP. |
| GET | `/logout` | No | Clears session cookie, redirects to `/login`. |
| GET | `/auth/check` | No | Returns `{"ok": true}` if authenticated; 401 with HTML redirect otherwise. Used by Traefik ForwardAuth. |
| GET | `/auth/start/:connection_id` | Yes | Initiates OAuth flow for a connection (Google/Outlook). Redirects to provider authorize URL. |
| GET | `/auth/callback/:provider` | Yes | OAuth callback. Exchanges code for tokens, saves to DB, syncs calendar if Google. Redirects to `/?oauth=connected`. |

### POST `/login`

**Body (form or JSON):**
```json
{ "username": "string", "password": "string" }
```

**Responses:**
- 302 redirect to `/` with `Set-Cookie` on success
- 401 HTML with error on bad credentials
- 429 HTML on rate limit exceeded

---

## Tasks

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/tasks` | Yes | List all tasks (excludes done/archived by default) |
| POST | `/api/tasks` | Yes | Create a new task |
| PATCH | `/api/tasks/:id` | Yes | Update a task |
| DELETE | `/api/tasks/:id` | Yes | Delete a task |
| GET | `/api/search` | Yes | Full-text search across tasks |
| GET | `/api/tasks/history` | Yes | Paginated history of completed tasks |
| GET | `/api/tasks/timelines` | Yes | Event timelines for multiple tasks |
| POST | `/api/tasks/:id/reject` | Yes | Reject a completed task back to pendiente |
| GET | `/api/tasks/:id/labels` | Yes | Get labels for a task |
| POST | `/api/tasks/:id/labels` | Yes | Add a label to a task |
| DELETE | `/api/tasks/:id/labels/:label` | Yes | Remove a label from a task |
| GET | `/api/tasks/:id/attachments` | Yes | List attachments for a task |
| POST | `/api/tasks/:id/attachments` | Yes | Upload an attachment (multipart/form-data) |
| GET | `/api/tasks/:id/attachments/:filename` | Yes | Download/view an attachment |
| DELETE | `/api/tasks/:id/attachments/:filename` | Yes | Delete an attachment |

### GET `/api/tasks`

**Query params:**
- `include_done` (0|1, default 0) -- include done/archived tasks

**Response:** Array of task objects with `project_name`, `active_agent`, `completed_by_agent` enrichment.

### POST `/api/tasks`

**Body:**
```json
{
  "title": "string (required)",
  "description": "string",
  "area": "personal|empresa|proyecto",
  "project_id": "string|null",
  "status": "pendiente|en_progreso|bloqueada|hecha|archivada",
  "priority": "critica|alta|media|baja",
  "urgent": false,
  "scheduled_for": "YYYY-MM-DD|null",
  "due_at": "YYYY-MM-DD|null",
  "notes": "string",
  "assigned_to_yume": false,
  "assigned_to_claude": false
}
```

**Response:** `{ "ok": true, "id": "uuid" }` (201)

### PATCH `/api/tasks/:id`

**Body:** Any subset of task fields (same as POST).

**Special behavior:**
- Setting `status=hecha` on a Desk project task requires `desk-deploy:verified` marker in notes (409 if missing).
- Records a `task_event` on every update.

**Response:** `{ "ok": true }` or `{ "error": "desk_deploy_closure_required" }` (409)

### GET `/api/search`

**Query params:**
- `q` (string) -- search term, matched against title/description/notes

**Response:** Array of task objects (max 30).

### GET `/api/tasks/history`

**Query params:**
- `project_id`, `from`, `to`, `source`, `search` -- filters
- `page` (default 1), `limit` (default 50)
- `sort` (default `completed_at`), `order` (default `desc`)

**Response:** Paginated result from `history.py`.

### GET `/api/tasks/timelines`

**Query params:**
- `ids` -- comma-separated task IDs

**Response:** `{ "task_id": [{ "type", "payload", "at" }...] }`

### POST `/api/tasks/:id/reject`

**Body:**
```json
{ "reason": "string" }
```

**Response:** `{ "ok": true }` -- resets task to pendiente, clears assigned_to_claude, appends `[rejected]` to notes.

### POST `/api/tasks/:id/attachments`

**Content-Type:** `multipart/form-data` with field `file`.

**Response:** `{ "ok": true, "filename": "string", "attachments": [...] }` (201)

---

## Projects

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/projects` | Yes | List all active projects with task counts |

**Response:** Array of project objects with `open_tasks`, `done_tasks`, `total_tasks`.

---

## Dashboard

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/dashboard` | Yes | Full dashboard payload (urgent, today, projects, my_day, kanban_columns, counts, by_area) |
| GET | `/api/my-day` | Yes | Today's focused tasks and summary |
| POST | `/api/my-day/tasks` | Yes | Add a task to My Day |
| DELETE | `/api/my-day/tasks/:task_id` | Yes | Remove a task from My Day |
| GET | `/api/kanban-columns` | Yes | List kanban columns |
| GET | `/api/stats` | Yes | Task statistics (total, open, done, overdue, by_status, by_priority, completions_by_day) |
| GET | `/api/activity` | Yes | Recent task events |
| GET | `/api/dashboard/pipeline` | Yes | Pipeline analytics (avg durations per stage, bottleneck) |
| GET | `/api/kpis` | Yes | KPIs per agent phase (triage/execute/review/deploy) |
| GET | `/api/metrics` | Yes | Live service status and task counters |

### POST `/api/my-day/tasks`

**Body:**
```json
{ "task_id": "string" }
```

### GET `/api/kanban-columns`

**Query params:**
- `include_terminal` (0|1, default 1)

### GET `/api/activity`

**Query params:**
- `limit` (default 50)

### GET `/api/dashboard/pipeline`

**Query params:**
- `days` (default 7)

---

## System

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | No | Simple health check `{ "ok": true }` |
| GET | `/api/health/full` | Yes | Full health: Docker containers, workers, tunnel, system stats, last healthcheck |
| GET | `/api/security` | Yes | Security scan: sandbox enforcer log threats |
| POST | `/api/security/scan` | Yes | Trigger a security scan (returns same as GET) |
| GET | `/api/logs` | Yes | Read log files |
| GET | `/api/live-state` | Yes | Change-detection token (hash of latest timestamps across all data) |
| GET | `/api/agents-status` | Yes | Agent org chart: status, current_task, last_seen, model |
| GET | `/api/flows` | Yes | Operational flows overview (routing rules, deploy flow, n8n workflows) |
| GET | `/api/config` | Yes | Read config files (agents.json, sandbox.json) |
| POST | `/api/trigger/idle-review` | Yes | Queue an idle-review trigger (stub) |

### GET `/api/logs`

**Query params:**
- `source` (all|gateway|sync|bridge|executor|watchdog, default `gateway`)
- `lines` (default 100)

**Response:** Array of `{ "source": "string", "line": "string" }`.

---

## Settings

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/settings` | Yes | Read all settings (merged from settings.json + DB) |
| POST | `/api/settings` | Yes | Save settings (key-value pairs written to settings.json) |

### POST `/api/settings`

**Body:** Object of key-value pairs. Each key is saved individually.

**Response:** `{ "ok": true }`

---

## Crons

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/crons` | Yes | List all cron jobs with state, schedule, delivery info |
| POST | `/api/crons/toggle` | Yes | Enable/disable a cron job |
| POST | `/api/crons/toggle-notify` | Yes | Mute/unmute delivery for a cron job |
| POST | `/api/crons/toggle-format` | Yes | Cycle delivery format (text -> audio -> both -> text) |

### POST `/api/crons/toggle`

**Body:**
```json
{ "id": "job_id" }
```

**Response:** `{ "ok": true, "enabled": true|false }`

### POST `/api/crons/toggle-notify`

**Body:**
```json
{ "id": "job_id" }
```

**Response:** `{ "ok": true, "muted": true|false }`

### POST `/api/crons/toggle-format`

**Body:**
```json
{ "id": "job_id" }
```

**Response:** `{ "ok": true, "format": "text|audio|both" }`

---

## Connections

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/connections` | Yes | List all connections with auth status |
| POST | `/api/connections` | Yes | Create a new connection |
| PATCH | `/api/connections/:id` | Yes | Update connection (label, scope, email) |
| DELETE | `/api/connections/:id` | Yes | Delete a connection |
| POST | `/api/connections/:id/disconnect` | Yes | Disconnect (revoke tokens, set status to pending) |
| POST | `/api/google/sync` | Yes | Sync Google Calendar + Gmail for a scope |
| POST | `/api/outlook/sync` | Yes | Outlook sync (not yet implemented) |
| GET | `/api/calendar-events` | Yes | List synced calendar events |
| GET | `/api/email-summary` | Yes | Important Gmail messages (last 7 days) |
| POST | `/api/emails/dismiss` | Yes | Dismiss email notifications (stub, returns ok) |

### POST `/api/connections`

**Body:**
```json
{
  "provider": "google|outlook",
  "label": "string",
  "scope": "personal|empresa",
  "email": "string"
}
```

**Response:** `{ "ok": true, "id": "uuid" }` (201)

### GET `/api/calendar-events`

**Query params:**
- `scope` (default `personal`)

### GET `/api/email-summary`

**Query params:**
- `scope` (default `personal`)

### POST `/api/google/sync`

**Query params:**
- `scope` (default `personal`)

**Response:** `{ "ok": bool, "calendar": {...}, "emails": int, "email_errors": [...] }`

---

## Static & Frontend

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` or `/index.html` | Yes | Serves `frontend/index.html` |
| GET | `/static/*` | No | Serves files from `frontend/static/` |
