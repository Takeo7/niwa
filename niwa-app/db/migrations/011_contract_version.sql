-- Migration 011: Add contract_version to routing_decisions for audit trail.
-- Records which MCP contract was active when the routing decision was made.
-- NULL is valid (core mode or decisions made before this migration).
-- PR-09 — Niwa v0.2

ALTER TABLE routing_decisions ADD COLUMN contract_version TEXT;
