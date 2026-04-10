-- Chat + Memory tables (added 2026-04-10)
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

CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'general',
    project_id  TEXT,
    source      TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_key ON memories(key, COALESCE(project_id,''));
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_id);
