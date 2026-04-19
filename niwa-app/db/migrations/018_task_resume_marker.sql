-- Migration 018: resume marker + pending followup (FIX-20260420)
-- When the user answers Claude from the UI via POST /api/tasks/:id/respond,
-- the endpoint stores the followup message and a pointer to the run being
-- resumed, then flips the task back to ``pendiente``. The executor picks
-- the task up, reads the marker, and creates a new ``backend_run`` with
-- ``relation_type='resume'`` and ``previous_run_id=resume_from_run_id``.
-- The adapter reads ``pending_followup_message`` from the task to build
-- the prompt (original task description + followup).
--
-- Design notes (aligned with PR-57 retry marker):
--   * Nullable on purpose — most tasks never go through this flow.
--   * No FK on resume_from_run_id: if the historical run gets
--     garbage-collected, the executor clears the marker and falls back
--     to the normal routing flow rather than getting stuck.
--   * Followup is cleared after the executor consumes it, so a future
--     ``/respond`` round-trip starts from a clean slate.
ALTER TABLE tasks ADD COLUMN resume_from_run_id TEXT;
ALTER TABLE tasks ADD COLUMN pending_followup_message TEXT;
CREATE INDEX IF NOT EXISTS idx_tasks_resume_from_run_id
  ON tasks(resume_from_run_id)
  WHERE resume_from_run_id IS NOT NULL;
