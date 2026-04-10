-- Migration 006: OAuth token storage
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
