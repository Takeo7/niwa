# Isu strip — audit and delete plan

> **Date:** 2026-04-07
> **Goal:** identify exactly what to delete from Isu when porting it to the Niwa pack, keeping only the 6 views in active use.
> **Status:** P0 complete.

## Decisions

- **Views to KEEP (6):** dashboard, kanban, projects, notes, history, system
- **Views to REMOVE (5):** calendar, email, agents, connections, terminal

## Critical findings

### 1. `/api/agents-status` is shared with dashboard
The endpoint that powers the "agents view" is also called by **dashboard** (`app.js` line 270, widget `dash-agents`). **Cannot delete the endpoint** — only the agents view UI. The `fetch_agents_status()` function and its helpers (`load_agent_metadata`, `_load_workspace_agents_state`) stay.

### 2. `/api/flows` is used by system view
Same situation. `fetch_flows_overview()` stays.

### 3. `day_focus` / `day_focus_tasks` tables stay
Used by `/api/my-day` and `fetch_my_day()` for the "Mi día" widget in dashboard. Not part of any view to delete.

### 4. `inbox_items` table stays
Not referenced by Isu's `app.py` directly, but it IS used by the Niwa `isu-mcp` server (`inbox_create`, `inbox_list` verbs). Schema must include it.

## Files to DELETE entirely

| File | Lines | Reason |
|---|---|---|
| `backend/connections_service.py` | ~240 | OAuth framework, only used by connections view |
| `backend/google_service.py` | ~197 | Google Calendar/Gmail, only used by calendar+email |

## Files to STRIP (partial deletes)

### `frontend/index.html` (~216 lines to delete from 1159 total, ~18%)

| Block | Lines | What |
|---|---|---|
| Calendar section | 460-493 | `<section id="view-calendar">` |
| Email section | 494-522 | `<section id="view-email">` |
| Agents section | 523-560 | `<section id="view-agents">` |
| Connections section | 916-928 | `<section id="view-connections">` |
| Connection modal | 1108-1128 | OAuth setup modal |
| Terminal section | 930-1010 | Hardcoded command snippets |
| Nav links 132-160 | (toggle off) | calendar, email, agents, connections, terminal links |

### `frontend/static/app.js` (~424 lines to delete from 3091 total, ~14%)

| Symbol | Lines | What |
|---|---|---|
| `loadCalendar` + `renderCalendar` + `renderCalendarList` + `calNav` + `calFilterScope` + `syncCalendar` | 2102-2270 | ~150 lines |
| Calendar globals (`_calEvents`, `_calScope`, `_calMonth`, `_calYear`, `_calViewMode`) | ~5 |  |
| `loadEmails` + `renderEmails` + `emailFilterScope` + `syncEmails` + `dismissEmail` + `emailToTask` | 2276-2395 | ~110 lines |
| `loadAgents` | 1446-1517 | 72 lines |
| `loadConnections` + `openConnectionModal` + `closeConnectionModal` + `saveConnection` + `disconnectConnection` + `deleteConnection` | 2421-2487 | ~60 lines |
| `loadTerminal` + `copyCmd` | 2400-2419 | ~20 lines |
| Switch cases for the 5 views | 256-261 | 6 lines |
| Keyboard shortcut `case 'a'` | 2875 | 1 line |

**KEEP:** `renderDashAgents` (line 379) — used by dashboard, NOT by agents view alone.

### `backend/app.py` (~22 lines of handlers + import changes)

| Endpoint handler | Line | Action |
|---|---|---|
| `GET /api/calendar-events` | 1443-1445 | DELETE |
| `POST /api/google/sync` | 1598-1603 | DELETE |
| `GET /api/email-summary` | 1446-1448 | DELETE |
| `POST /api/emails/dismiss` | 1623-1624 | DELETE |
| `POST /api/outlook/sync` | 1621-1622 | DELETE |
| `GET /api/connections` | 1435-1436 | DELETE |
| `POST /api/connections` | 1585-1587 | DELETE |
| `POST /api/connections/{id}/disconnect` | 1588-1591 | DELETE |
| `PATCH /api/connections/{id}` | 1677-1680 | DELETE |
| `DELETE /api/connections/{id}` | 1709-1712 | DELETE |
| `GET /api/agents-status` | 1437-1438 | **KEEP** (used by dashboard) |
| `GET /api/flows` | 1439-1440 | **KEEP** (used by system) |

**Imports to remove:**
- `import connections_service` (line 22)
- `from google_service import sync_google_calendar, fetch_calendar_events, fetch_gmail_summary, parse_gmail_headers, is_important_email` (lines 751-754)

**KEEP:** `fetch_agents_status` (line 623), `load_agent_metadata` (line 551), `_load_workspace_agents_state` (line 576), `_load_active_delegations` (line 588), `extract_last_user_task` (line 557), `fetch_flows_overview` (line 408).

### `db/schema.sql` (~19 lines)

| Table | Lines | Action |
|---|---|---|
| `calendar_events` | 72-84 | DELETE |
| `task_calendar_links` | 86-90 | DELETE |
| `idx_calendar_events_starts_at` | 119 | DELETE |
| `connections` | (in `init_db`) | DELETE |
| `connection_auth` | (in `init_db`) | DELETE |
| `dismissed_emails` | (if exists) | DELETE |

**KEEP:** `tasks`, `projects`, `notes`, `inbox_items`, `kanban_columns`, `task_events`, `task_metrics`, `task_calendar_links` (NO — delete this), `task_labels`, `day_focus`, `day_focus_tasks`, `settings`, `sessions`, `login_attempts`, `briefings`, `briefing_items`, `chat_messages`, `healthchecks`, `project_files`, `watchlist_items`, `research_notes`.

### `frontend/i18n.js` (~50 strings)

Remove all keys starting with: `nav.calendar`, `nav.email`, `nav.agents`, `nav.connections`, `nav.terminal`, `cal.*`, `email.*`, `agents.*`, `conn.*`, `term.*`.

## Total lines deleted

| Area | Lines |
|---|---|
| HTML | ~216 |
| JS (app.js) | ~424 |
| Python endpoints | ~22 |
| Python modules deleted entirely | ~437 (2 files) |
| SQL | ~19 |
| i18n strings | ~50 |
| **Total** | **~1,168 lines + 2 deleted files** |

## Risks

1. **Imports at top-level**: removing `connections_service` and `google_service` imports from `app.py` cleanly requires removing all references in one pass. If a single helper still imports them, build fails.
2. **Sandbox config**: `Isu/config/sandbox.json` may reference deleted files. Verify and clean.
3. **Frontend route handler**: `switchView('agents')` etc. needs to be removed from the keyboard shortcut handler AND any deep-links if the URL hash router supports `#agents`.
4. **i18n strings deletion**: harmless if missed (keys just stop matching), but cleaner to remove.

## Open questions resolved

- ~~`day_focus` table?~~ → KEEP (used by `/api/my-day` and `fetch_my_day`).
- ~~`inbox_items` table?~~ → KEEP (used by Niwa `isu-mcp` server even if Isu app.py doesn't query it directly).
- Keyboard shortcut `'a'` → remove the handler line, no need to reassign.
- Settings OAuth status → delete OAuth-related fields if any.
