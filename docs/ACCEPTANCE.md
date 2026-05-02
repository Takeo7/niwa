# Niwa Acceptance Record

Target version: `0.2.0-rc.1`

This document separates evidence that can be generated automatically from
optional live checks and manual infrastructure checks. Do not mark a release
accepted unless the actual command output or operator evidence is attached to
the release notes or PR body.

## Automated Gates

These gates are deterministic and do not require real Claude, GitHub auth, DNS,
Caddy, TLS, or a domain:

- [ ] `cd backend && pytest -q`
- [ ] `cd frontend && npm test -- --run`
- [ ] `make smoke`
- [ ] `make release-gate`

`make smoke` writes `.smoke/report.json`. To summarize that report without
pretending to run other gates:

```bash
python3 scripts/acceptance_summary.py
```

The summary script exits non-zero if the smoke report is missing or contains a
failed check.

## Optional Live Gates

These checks are opt-in and must not be required by CI:

- [ ] `make smoke-live`
  - Without `NIWA_SMOKE_LIVE=1`, this skips successfully.
  - With `NIWA_SMOKE_LIVE=1`, this is a live tools check only: it verifies a
    local `claude` CLI and authenticated `gh` session.
  - It does not prove an end-to-end Claude/GitHub task flow.

## Manual Infrastructure Checks

These checks require operator-owned infrastructure or credentials:

- [ ] DNS points the UI host and wildcard apps host at the intended machine or
      tunnel.
- [ ] Caddy is installed by the operator and validates the rendered Caddyfile.
- [ ] Caddy has been run or reloaded by the operator.
- [ ] TLS is issued by Caddy or provided by the operator's tunnel/proxy.
- [ ] Auth is enabled before exposing Niwa beyond localhost.
- [ ] A public project is deliberately marked `public_enabled=true`; private
      projects remain unrouted.
- [ ] A real Claude/GitHub workflow has been tested only if the release decision
      explicitly requires live integrations.

## Product Flow Checklist

- [ ] Clean bootstrap completes in a temporary `NIWA_HOME`.
- [ ] `niwa-executor doctor --strict` passes in the release gate.
- [ ] Create a project with `public_enabled=false`.
- [ ] Create a task from the UI.
- [ ] Task reaches `done` through plan, execute, verify, review, finalize.
- [ ] Manual plan approval blocks execution until approval when enabled.
- [ ] `waiting_input` can be answered and resumed.
- [ ] Failed/cancelled tasks can be retried where allowed.
- [ ] Safe-mode PR creation uses fake GitHub in smoke and real `gh` only when
      configured.
- [ ] Static deploy becomes healthy.
- [ ] Process deploy records pid/process log and can healthcheck/stop.
- [ ] Caddy render includes only public projects.
- [ ] MCP flow covers `initialize`, `tools/list`, `project_list`, `task_create`,
      `task_status`, `task_respond`, `deploy_trigger`, and `deployment_status`.
- [ ] Backup and restore complete against a disposable home.

## Release Decision

Record the final decision here or in release notes:

- Decision: `accept` / `hold`
- Commit SHA:
- Automated gate output location:
- Optional live gate output location:
- Manual infrastructure evidence:
- Known limitations accepted:

Known limitations that must remain visible:

- Niwa is not a strong OS sandbox; Claude runs as the Niwa OS user.
- DNS, TLS, Caddy install/reload, and tunnels are not managed by Niwa.
- MCP is HTTP JSON-RPC request/response, not stdio or streaming.
- `fake-json` planner/reviewer are deterministic; `claude-code` modes require
  operator credentials.
- The `claude-code` reviewer receives bounded evidence plus diff context, but
  is not a full semantic or security audit.
