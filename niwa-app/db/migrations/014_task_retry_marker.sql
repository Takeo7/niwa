-- Migration 014: retry marker column (PR-57)
-- When the user clicks "Reintentar" in the UI, the endpoint sets
-- ``retry_from_run_id`` to the id of the run being retried and flips
-- the task back to ``pendiente``. The executor, when it picks the
-- task up, uses that marker to create a new ``backend_run`` with
-- ``relation_type='retry'``, ``previous_run_id=retry_from_run_id``,
-- and the same ``backend_profile_id`` + ``routing_decision_id`` as
-- the previous run (retry, not reroute).
--
-- Design notes:
--   * Nullable on purpose — a task can be ``pendiente`` without being
--     a retry (fresh tasks, bug fixes, etc.).
--   * No FK: if the historical run gets garbage-collected, the
--     executor's graceful-degrade path clears the marker and falls
--     back to the normal routing flow rather than getting stuck.
ALTER TABLE tasks ADD COLUMN retry_from_run_id TEXT;
CREATE INDEX IF NOT EXISTS idx_tasks_retry_from_run_id
  ON tasks(retry_from_run_id)
  WHERE retry_from_run_id IS NOT NULL;
