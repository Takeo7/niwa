-- Migration 005: Services system + settings unification
-- Ensures settings table exists and has an index for service config queries.
-- The actual migration of settings.json → SQLite is handled by app.py _run_migrations().

-- Index for fast service config lookups (svc.* keys)
CREATE INDEX IF NOT EXISTS idx_settings_key ON settings(key);
