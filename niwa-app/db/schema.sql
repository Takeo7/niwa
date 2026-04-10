-- Niwa schema
-- Authoritative schema reflecting Phase 5 (typed notes) + Niwa MCP requirements.
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
  url TEXT
);

-- ── Tasks ──
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT,
  area TEXT NOT NULL CHECK (area IN ('personal','empresa','proyecto','sistema')) DEFAULT 'proyecto',
  project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN ('inbox','pendiente','en_progreso','bloqueada','revision','hecha','archivada')) DEFAULT 'inbox',
  priority TEXT NOT NULL CHECK (priority IN ('baja','media','alta','critica','low','medium','high','critical')) DEFAULT 'media',
  urgent INTEGER NOT NULL DEFAULT 0,
  scheduled_for TEXT,
  due_at TEXT,
  completed_at TEXT,
  source TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  assigned_to_yume INTEGER NOT NULL DEFAULT 0,
  assigned_to_claude INTEGER NOT NULL DEFAULT 0,
  attachments TEXT
);

-- ── Kanban columns ──
CREATE TABLE IF NOT EXISTS kanban_columns (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL UNIQUE CHECK (status IN ('inbox','pendiente','en_progreso','bloqueada','revision','hecha','archivada')),
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
