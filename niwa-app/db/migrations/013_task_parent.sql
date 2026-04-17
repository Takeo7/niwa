-- Migration 013: parent_task_id for follow-up tasks (PR-55)
-- When Claude leaves the task in ``waiting_input`` (typical: asked a
-- question in its output), the user responds by creating a child
-- task with a short hint in its description. ``parent_task_id``
-- records the chain so the UI can render "↳ responde a <parent>".
--
-- A NULLable column with an index on itself — no FK to avoid
-- cascading deletes that would erase context when the parent is
-- archived.
ALTER TABLE tasks ADD COLUMN parent_task_id TEXT;
CREATE INDEX IF NOT EXISTS idx_tasks_parent_task_id ON tasks(parent_task_id);
