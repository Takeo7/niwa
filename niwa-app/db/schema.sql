-- Niwa schema
-- Authoritative schema reflecting v0.2 (execution core) + Niwa MCP requirements.
-- Used by niwa-app/backend/app.py init_db() and the Niwa MCP servers (tasks-mcp, notes-mcp).
-- Fresh installs run this once. Bumping requires a versioned migration in db/migrations/.

PRAGMA foreign_keys = ON;

-- ── Projects ──
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  area TEXT NOT NULL CHECK (area IN ('personal','empresa','proyecto','sistema')),
  description TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  directory TEXT,
  url TEXT,
  -- PR-B3: when 'dangerous', capability_service bypasses the approval gate.
  autonomy_mode TEXT NOT NULL DEFAULT 'normal'
    CHECK (autonomy_mode IN ('normal','dangerous'))
);

-- ── Tasks ──
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT,
  area TEXT NOT NULL CHECK (area IN ('personal','empresa','proyecto','sistema')) DEFAULT 'proyecto',
  project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN ('inbox','pendiente','en_progreso','bloqueada','revision','waiting_input','hecha','archivada')) DEFAULT 'inbox',
  priority TEXT NOT NULL CHECK (priority IN ('baja','media','alta','critica','low','medium','high','critical')) DEFAULT 'media',
  urgent INTEGER NOT NULL DEFAULT 0,
  scheduled_for TEXT,
  due_at TEXT,
  completed_at TEXT,
  source TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  assigned_to_yume INTEGER NOT NULL DEFAULT 0,   -- DEPRECATED v0.2: use backend_profiles/routing_decisions
  assigned_to_claude INTEGER NOT NULL DEFAULT 0, -- DEPRECATED v0.2: use backend_profiles/routing_decisions
  attachments TEXT,
  parent_task_id TEXT,  -- PR-55: follow-up tasks link back to their parent (waiting_input reply, etc.)
  retry_from_run_id TEXT,  -- PR-57: marker; executor reads it to create a retry-linked backend_run
  -- v0.2 execution columns (migration 007)
  requested_backend_profile_id TEXT REFERENCES backend_profiles(id) ON DELETE SET NULL,
  selected_backend_profile_id TEXT REFERENCES backend_profiles(id) ON DELETE SET NULL,
  current_run_id TEXT REFERENCES backend_runs(id) ON DELETE SET NULL,
  approval_required INTEGER NOT NULL DEFAULT 0,
  quota_risk TEXT,
  estimated_resource_cost TEXT
);

-- ── Kanban columns ──
CREATE TABLE IF NOT EXISTS kanban_columns (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL UNIQUE CHECK (status IN ('inbox','pendiente','en_progreso','bloqueada','revision','waiting_input','hecha','archivada')),
  label TEXT NOT NULL,
  position INTEGER NOT NULL,
  color TEXT,
  is_terminal INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- ── Task labels ──
CREATE TABLE IF NOT EXISTS task_labels (
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  PRIMARY KEY (task_id, label)
);

-- ── Task events / history timeline ──
CREATE TABLE IF NOT EXISTS task_events (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  type TEXT NOT NULL CHECK (type IN ('created','updated','status_changed','scheduled','completed','comment','alerted')),
  payload_json TEXT,
  created_at TEXT NOT NULL
);

-- ── Day focus (Mi día) ──
CREATE TABLE IF NOT EXISTS day_focus (
  day TEXT PRIMARY KEY,
  summary TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS day_focus_tasks (
  day TEXT NOT NULL REFERENCES day_focus(day) ON DELETE CASCADE,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, task_id)
);

-- ── Inbox items (quick captures, used by notes-mcp inbox_create/list) ──
CREATE TABLE IF NOT EXISTS inbox_items (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('task','note','email','calendar','file','message')),
  title TEXT,
  body TEXT,
  source TEXT,
  payload_json TEXT,
  triaged INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- ── Notes (typed, Phase 5) ──
-- Used by notes-mcp for note_*, decision_*, idea_*, research_*, diary_* verbs.
CREATE TABLE IF NOT EXISTS notes (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  content TEXT,
  project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
  tags TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  type TEXT NOT NULL DEFAULT 'note' CHECK (type IN ('decision','idea','research','diary','note')),
  metadata TEXT,
  status TEXT,
  linked_tasks TEXT,
  linked_decisions TEXT
);

-- ── Routines (cron-like scheduler) ──
CREATE TABLE IF NOT EXISTS routines (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    schedule TEXT NOT NULL,
    tz TEXT NOT NULL DEFAULT 'UTC',
    action TEXT NOT NULL CHECK (action IN ('create_task', 'script', 'webhook')),
    action_config TEXT NOT NULL DEFAULT '{}',
    notify_channel TEXT NOT NULL DEFAULT 'none',
    notify_config TEXT NOT NULL DEFAULT '{}',
    last_run_at TEXT,
    last_status TEXT,
    last_error TEXT,
    consecutive_errors INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- ── Task metrics (executor pipeline tracking) ──
CREATE TABLE IF NOT EXISTS task_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    phase TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL,
    error_message TEXT,
    hit_limit INTEGER NOT NULL DEFAULT 0,
    turns_used INTEGER,
    max_turns INTEGER,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_metrics_task_id ON task_metrics(task_id);
CREATE INDEX IF NOT EXISTS idx_task_metrics_phase ON task_metrics(phase);
CREATE INDEX IF NOT EXISTS idx_task_metrics_timestamp ON task_metrics(timestamp);

-- ── Healthchecks (monitoring history) ──
CREATE TABLE IF NOT EXISTS healthchecks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL
);

-- ── Settings (key-value store for app config) ──
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- ── Login attempts (auth rate limiting) ──
CREATE TABLE IF NOT EXISTS login_attempts (
  key TEXT PRIMARY KEY,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_attempt_at TEXT NOT NULL,
  blocked_until TEXT
);

-- ── Indices ──
CREATE INDEX IF NOT EXISTS idx_tasks_area ON tasks(area);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
CREATE INDEX IF NOT EXISTS idx_tasks_due_at ON tasks(due_at);
CREATE INDEX IF NOT EXISTS idx_tasks_project_id ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_parent_task_id ON tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_retry_from_run_id
  ON tasks(retry_from_run_id) WHERE retry_from_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_scheduled ON tasks(scheduled_for);
CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_id, status);
CREATE INDEX IF NOT EXISTS idx_task_events_task_id ON task_events(task_id);
CREATE INDEX IF NOT EXISTS idx_task_events_created_at ON task_events(created_at);
CREATE INDEX IF NOT EXISTS idx_notes_project_id ON notes(project_id);
CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(type);
CREATE INDEX IF NOT EXISTS idx_notes_status ON notes(status);
CREATE INDEX IF NOT EXISTS idx_inbox_items_kind ON inbox_items(kind);
CREATE INDEX IF NOT EXISTS idx_inbox_items_source ON inbox_items(source);
-- v0.2 task index (table exists above)
CREATE INDEX IF NOT EXISTS idx_tasks_status_source_updated ON tasks(status, source, updated_at);

-- ── Memories (persistent knowledge across tasks) ──
CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'general',
    project_id  TEXT REFERENCES projects(id) ON DELETE SET NULL,
    source      TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_key ON memories(key, COALESCE(project_id,''));
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_id);

-- ── Chat ──
CREATE TABLE IF NOT EXISTS chat_sessions (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT 'Nueva conversación',
    model_id   TEXT,
    external_ref TEXT,  -- PR-08: external channel identifier (e.g. OpenClaw chat_id)
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK(role IN ('user','assistant')),
    content    TEXT NOT NULL DEFAULT '',
    task_id    TEXT,
    status     TEXT NOT NULL DEFAULT 'done',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, created_at);

-- ── OAuth tokens (subscription auth for Claude/OpenAI/Gemini) ──
CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider    TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    id_token    TEXT,
    expires_at  INTEGER,
    email       TEXT,
    account_id  TEXT,
    metadata    TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- ── Backend profiles (v0.2) ──
CREATE TABLE IF NOT EXISTS backend_profiles (
    id               TEXT PRIMARY KEY,
    slug             TEXT NOT NULL UNIQUE,
    display_name     TEXT NOT NULL,
    backend_kind     TEXT NOT NULL CHECK(backend_kind IN ('claude_code','codex')),
    runtime_kind     TEXT NOT NULL CHECK(runtime_kind IN ('cli','api','acp','local')),
    default_model    TEXT,
    command_template TEXT,
    capabilities_json TEXT,
    enabled          INTEGER NOT NULL DEFAULT 1,
    priority         INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

-- ── Routing rules (v0.2) ──
CREATE TABLE IF NOT EXISTS routing_rules (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    position    INTEGER NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    match_json  TEXT,
    action_json TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- ── Routing decisions (v0.2) ──
CREATE TABLE IF NOT EXISTS routing_decisions (
    id                      TEXT PRIMARY KEY,
    task_id                 TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    decision_index          INTEGER NOT NULL,
    requested_profile_id    TEXT REFERENCES backend_profiles(id) ON DELETE SET NULL,
    selected_profile_id     TEXT REFERENCES backend_profiles(id) ON DELETE SET NULL,
    reason_summary          TEXT,
    matched_rules_json      TEXT,
    fallback_chain_json     TEXT,
    estimated_resource_cost TEXT,
    quota_risk              TEXT,
    contract_version        TEXT,
    created_at              TEXT NOT NULL
);

-- ── Backend runs (v0.2) ──
CREATE TABLE IF NOT EXISTS backend_runs (
    id                         TEXT PRIMARY KEY,
    task_id                    TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    routing_decision_id        TEXT REFERENCES routing_decisions(id) ON DELETE SET NULL,
    previous_run_id            TEXT REFERENCES backend_runs(id) ON DELETE SET NULL,
    relation_type              TEXT CHECK(relation_type IN ('fallback','resume','retry')),
    backend_profile_id         TEXT REFERENCES backend_profiles(id) ON DELETE SET NULL,
    backend_kind               TEXT,
    runtime_kind               TEXT,
    model_resolved             TEXT,
    session_handle             TEXT,
    status                     TEXT NOT NULL CHECK(status IN ('queued','starting','running','waiting_approval','waiting_input','succeeded','failed','cancelled','timed_out','rejected')),
    capability_snapshot_json   TEXT,
    budget_snapshot_json       TEXT,
    observed_usage_signals_json TEXT,
    heartbeat_at               TEXT,
    started_at                 TEXT,
    finished_at                TEXT,
    outcome                    TEXT,
    exit_code                  INTEGER,
    error_code                 TEXT,
    artifact_root              TEXT,
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL
);

-- ── Backend run events (v0.2) ──
CREATE TABLE IF NOT EXISTS backend_run_events (
    id              TEXT PRIMARY KEY,
    backend_run_id  TEXT NOT NULL REFERENCES backend_runs(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    message         TEXT,
    payload_json    TEXT,
    created_at      TEXT NOT NULL
);

-- ── Approvals (v0.2) ──
CREATE TABLE IF NOT EXISTS approvals (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    backend_run_id  TEXT REFERENCES backend_runs(id) ON DELETE SET NULL,
    approval_type   TEXT NOT NULL,
    reason          TEXT,
    risk_level      TEXT,
    status          TEXT NOT NULL,
    requested_at    TEXT NOT NULL,
    resolved_at     TEXT,
    resolved_by     TEXT,
    resolution_note TEXT
);

-- ── Artifacts (v0.2) ──
CREATE TABLE IF NOT EXISTS artifacts (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    backend_run_id  TEXT REFERENCES backend_runs(id) ON DELETE SET NULL,
    artifact_type   TEXT NOT NULL,
    path            TEXT NOT NULL,
    size_bytes      INTEGER,
    sha256          TEXT,
    created_at      TEXT NOT NULL
);

-- ── Project capability profiles (v0.2) ──
CREATE TABLE IF NOT EXISTS project_capability_profiles (
    id                    TEXT PRIMARY KEY,
    project_id            TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name                  TEXT NOT NULL,
    repo_mode             TEXT,
    shell_mode            TEXT,
    shell_whitelist_json  TEXT,
    web_mode              TEXT,
    network_mode          TEXT,
    filesystem_scope_json TEXT,
    secrets_scope_json    TEXT,
    resource_budget_json  TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

-- ── Secret bindings (v0.2) ──
CREATE TABLE IF NOT EXISTS secret_bindings (
    id                 TEXT PRIMARY KEY,
    project_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    backend_profile_id TEXT NOT NULL REFERENCES backend_profiles(id) ON DELETE CASCADE,
    secret_name        TEXT NOT NULL,
    provider           TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

-- v0.2 indices (tables defined above)
CREATE INDEX IF NOT EXISTS idx_backend_runs_task_status ON backend_runs(task_id, status);
CREATE INDEX IF NOT EXISTS idx_approvals_status_requested ON approvals(status, requested_at);

-- ── GitHub PAT (singleton, PR-49) ──
CREATE TABLE IF NOT EXISTS github_tokens (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    token_encrypted TEXT NOT NULL,
    username        TEXT,
    scopes          TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ── Schema versioning (migration tracking) ──
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    filename    TEXT
);
