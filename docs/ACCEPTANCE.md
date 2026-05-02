# Niwa Acceptance Checklist

Target version: `0.2.0-rc.1`

## Required Gates

- [ ] `cd backend && pytest -q`
- [ ] `cd frontend && npm test -- --run`
- [ ] `make smoke`
- [ ] `make release-gate`

## Product Flow

- [ ] Clean bootstrap completes in a temporary `NIWA_HOME`.
- [ ] `niwa-executor doctor` reports actionable warnings only.
- [ ] Create a project with `public_enabled=false`.
- [ ] Create a task from the UI.
- [ ] Task reaches `done` through plan, execute, verify, review, finalize.
- [ ] Manual plan approval blocks execution until approval when enabled.
- [ ] `waiting_input` can be answered and resumed.
- [ ] Failed/cancelled tasks can be retried where allowed.
- [ ] Safe-mode PR creation uses fake GitHub in smoke and real `gh` only when configured.
- [ ] Static deploy becomes healthy.
- [ ] Process deploy records pid/process log and can healthcheck/stop.
- [ ] Caddy render includes only public projects.
- [ ] MCP flow covers `initialize`, `tools/list`, `project_list`, `task_create`,
  `task_status`, `task_respond`, `deploy_trigger`, and `deployment_status`.
- [ ] Backup and restore complete against a disposable home.

## Release Notes

- [ ] Known limitations are included.
- [ ] Required external infrastructure is explicit and optional.
- [ ] No claims depend on secrets, DNS, Caddy reloads, real Claude, or real
  GitHub for CI success.
