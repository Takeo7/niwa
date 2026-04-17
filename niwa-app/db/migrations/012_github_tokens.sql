-- Migration 012: GitHub PAT storage (PR-49)
-- Singleton table (PK = 1) that holds the admin's GitHub personal access
-- token. The token column stores an obfuscated blob (see
-- backend/github_client.py::encrypt_token) — NOT plaintext. The
-- obfuscation key is derived from NIWA_APP_SESSION_SECRET so a DB leak
-- alone does not reveal the token.
--
-- Note: this is defense-in-depth, not serious encryption. Per the
-- Dockerfile's stdlib-only constraint we do not depend on pyca/cryptography.
-- A proper AEAD upgrade is tracked as Bug 28's GitHub-sibling for v0.3.
CREATE TABLE IF NOT EXISTS github_tokens (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    token_encrypted TEXT NOT NULL,
    username TEXT,
    scopes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
