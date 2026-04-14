-- Migration 010: Add external_ref to chat_sessions for OpenClaw mapping — PR-08.
--
-- external_ref stores an external channel identifier (e.g. OpenClaw chat_id)
-- so Niwa can map incoming requests to an existing chat_session.  NULL for
-- sessions created natively by the Niwa web UI.

ALTER TABLE chat_sessions ADD COLUMN external_ref TEXT;
