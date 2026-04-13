-- Migration 007: v0.2 execution core
--
-- Adds the foundational tables for auditable task execution in Niwa v0.2:
--   backend_profiles, routing_rules, routing_decisions, backend_runs,
--   backend_run_events, approvals, artifacts, project_capability_profiles,
--   secret_bindings.
--
-- Extends the tasks table with routing and execution columns.
--
-- Deprecation notice:
--   tasks.assigned_to_claude and tasks.assigned_to_yume are DEPRECATED as of
--   v0.2. They remain in the schema for backward compatibility but MUST NOT be
--   used for routing or execution decisions. Use backend_profiles and
--   routing_decisions instead. These columns will be removed in a future major
--   version.
--
-- Idempotency:
--   All CREATE TABLE / CREATE INDEX use IF NOT EXISTS.
--   ALTER TABLE ADD COLUMN does NOT support IF NOT EXISTS in SQLite; those
--   statements will fail harmlessly if the columns already exist (e.g. when
--   schema.sql was applied first on a fresh install). The application migration
--   runner (app.py _run_migrations) tracks applied versions in schema_version
--   and will not re-run this migration.

-- ── Backend profiles ──
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

-- ── Routing rules ──
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

-- ── Routing decisions ──
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
    created_at              TEXT NOT NULL
);

-- ── Backend runs ──
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
    status                     TEXT NOT NULL,
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

-- ── Backend run events ──
CREATE TABLE IF NOT EXISTS backend_run_events (
    id              TEXT PRIMARY KEY,
    backend_run_id  TEXT NOT NULL REFERENCES backend_runs(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    message         TEXT,
    payload_json    TEXT,
    created_at      TEXT NOT NULL
);

-- ── Approvals ──
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

-- ── Artifacts ──
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

-- ── Project capability profiles ──
CREATE TABLE IF NOT EXISTS project_capability_profiles (
    id                    TEXT PRIMARY KEY,
    project_id            TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name                  TEXT NOT NULL,
    repo_mode             TEXT,
    shell_mode            TEXT,
    web_mode              TEXT,
    network_mode          TEXT,
    filesystem_scope_json TEXT,
    secrets_scope_json    TEXT,
    resource_budget_json  TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

-- ── Secret bindings ──
CREATE TABLE IF NOT EXISTS secret_bindings (
    id                 TEXT PRIMARY KEY,
    project_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    backend_profile_id TEXT NOT NULL REFERENCES backend_profiles(id) ON DELETE CASCADE,
    secret_name        TEXT NOT NULL,
    provider           TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

-- ── Extend tasks table with v0.2 execution columns ──
-- NOTE: SQLite does not support ADD COLUMN IF NOT EXISTS.
-- These statements are safe to skip if columns already exist (fresh install
-- via schema.sql). The migration runner tracks applied versions to prevent
-- re-execution.
ALTER TABLE tasks ADD COLUMN requested_backend_profile_id TEXT REFERENCES backend_profiles(id) ON DELETE SET NULL;
ALTER TABLE tasks ADD COLUMN selected_backend_profile_id TEXT REFERENCES backend_profiles(id) ON DELETE SET NULL;
ALTER TABLE tasks ADD COLUMN current_run_id TEXT REFERENCES backend_runs(id) ON DELETE SET NULL;
ALTER TABLE tasks ADD COLUMN approval_required INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN quota_risk TEXT;
ALTER TABLE tasks ADD COLUMN estimated_resource_cost TEXT;

-- ── Indices (SPEC-required) ──
CREATE INDEX IF NOT EXISTS idx_tasks_status_source_updated ON tasks(status, source, updated_at);
CREATE INDEX IF NOT EXISTS idx_backend_runs_task_status ON backend_runs(task_id, status);
CREATE INDEX IF NOT EXISTS idx_approvals_status_requested ON approvals(status, requested_at);
