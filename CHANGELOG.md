# Changelog

## 0.2.0-rc.1 - 2026-05-02

Release-candidate close for Niwa local-first operation.

- Added deterministic `make smoke`, clean-machine `make release-gate`, and
  optional `make smoke-live`.
- Added auth scopes, audit/redaction coverage, operational limits, backup/
  restore, doctor, and kill-switch support.
- Made the task pipeline explicit: triage, plan, optional approval, execute,
  verify, review, bounded request-changes loop, finalize, and optional deploy.
- Added configurable planner/reviewer modes: deterministic `fake-json` default
  and opt-in `claude-code`.
- Added static/process deployments, deploy triggers, process logs,
  healthchecks, rollback/stop, and Caddy render/validate support.
- Added public/private publication controls with `public_enabled=false` by
  default.
- Added MCP HTTP JSON-RPC tools for projects, tasks, attachments, pulls, deploy
  trigger/status, plus `initialize`, stable errors, and OpenClaw examples.
- Expanded the UI with project settings, backlog controls, task plan/review/run
  visibility, deploy operations, admin metrics/tokens/audit/ops, and system
  readiness.

Known limitations:

- Real Claude/GitHub/DNS/Caddy infrastructure is opt-in and not required for
  CI/smoke. `make smoke-live` is a live tools check, not a full E2E live flow.
- Niwa is not a strong OS sandbox; Claude runs as the Niwa user.
- MCP is HTTP JSON-RPC request/response, not stdio or streaming.
- The `claude-code` reviewer receives bounded diff/evidence context and is not
  a complete semantic or security audit.
