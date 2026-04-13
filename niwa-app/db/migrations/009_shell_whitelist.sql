-- Migration 009: Add shell_whitelist_json to project_capability_profiles (PR-05)
--
-- Stores the per-project shell command whitelist as a JSON array of strings.
-- When shell_mode = 'whitelist', only commands in this list are allowed.
-- Example: ["ls","cat","grep","find","pwd","echo"]
--
-- Fresh installs already have this column from schema.sql.
-- This migration adds it to existing databases.

ALTER TABLE project_capability_profiles ADD COLUMN shell_whitelist_json TEXT;
