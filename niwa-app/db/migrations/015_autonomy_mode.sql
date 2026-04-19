-- Migration 015: project-level autonomy_mode flag (PR-B3)
-- When set to 'dangerous', capability_service.evaluate() and
-- evaluate_runtime_event() return allowed=True, so no approval
-- gates trigger for tasks in that project. Default is 'normal'
-- (prior behaviour: approvals still enforced).
--
-- SQLite cannot add a CHECK constraint via ALTER; the enum is
-- enforced at the HTTP layer (PATCH /api/projects/<slug>). Fresh
-- installs get the CHECK via schema.sql.
ALTER TABLE projects ADD COLUMN autonomy_mode TEXT NOT NULL
  DEFAULT 'normal';
