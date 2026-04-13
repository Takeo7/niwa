-- Migration 008: State machine CHECK constraints (PR-02)
--
-- Adds CHECK constraint on backend_runs.status to enforce the canonical
-- state machine defined in docs/SPEC-v0.2.md § PR-02 and
-- docs/state-machines.md.
--
-- tasks.status already has a CHECK constraint from schema.sql (PR-01).
-- backend_runs.status was deliberately deferred to PR-02
-- (see DECISIONS-LOG PR-01, Decision 2).
--
-- Strategy: recreate backend_runs with the CHECK.  The table was added in
-- migration 007 and has no production data yet, so the swap is safe.
-- Foreign keys are disabled during the swap and re-enabled after.
--
-- Idempotency: the migration runner tracks applied versions in
-- schema_version, so this will not re-run.  If applied on a fresh install
-- (schema.sql already loaded), the table will already have the CHECK from
-- the updated schema.sql; this migration still runs cleanly because it
-- recreates the table identically.

PRAGMA foreign_keys = OFF;

BEGIN TRANSACTION;

-- 1. Create replacement table with CHECK on status
CREATE TABLE backend_runs_new (
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

-- 2. Copy any existing rows (expected: zero)
INSERT INTO backend_runs_new SELECT * FROM backend_runs;

-- 3. Drop old table and rename
DROP TABLE backend_runs;
ALTER TABLE backend_runs_new RENAME TO backend_runs;

-- 4. Recreate indexes (from migration 007 / schema.sql)
CREATE INDEX IF NOT EXISTS idx_backend_runs_task_status ON backend_runs(task_id, status);

COMMIT;

PRAGMA foreign_keys = ON;
