# Niwa

Local-first autonomous coding workbench. Niwa turns natural-language tasks into
local git branches, verified runs, pull requests, and optional local/online
deployments through the Claude Code CLI.

**Status:** local-first MVP+ / post-v1.1 hardening. Single operator, local
machine or self-hosted VPS. Smoke, auth scopes, deployments, MCP HTTP JSON-RPC,
Caddy config generation, task plans/reviews, doctor, backup, and restore exist.

Important truth boundary: planner and reviewer default to deterministic
`fake-json` for tests and smoke. Operators can opt into configurable
`claude-code` planner/reviewer modes; invalid LLM JSON falls back safely rather
than leaving runs hanging. The `claude-code` reviewer receives verification
evidence plus bounded `git status`/`git diff` context; it is not a complete
semantic or security audit.

See `docs/SPEC.md` for the product contract and `docs/HANDBOOK.md` for the code
map.

## Install

Tested on macOS and Linux. Requires:

- Python 3.11+:
  - macOS: `brew install python@3.11`.
  - Ubuntu 22.04 LTS: `sudo apt install python3.11 python3.11-venv`.
  - Ubuntu 24.04+: `sudo apt install python3-venv`.
- Node.js 22+.
- git.
- Claude Code CLI authenticated for real task execution:
  `npm install -g @anthropic-ai/claude-code && claude`, then `/login`.
- GitHub CLI authenticated if you want Niwa to open/merge PRs:
  `gh auth login`.

Then:

```bash
git clone https://github.com/Takeo7/niwa.git
cd niwa
./bootstrap.sh
source ~/.niwa/venv/bin/activate
niwa-executor start
niwa-executor dev start --detach
```

Backend: http://127.0.0.1:8000. Frontend:
http://127.0.0.1:5173.

Detached dev helpers:

```bash
niwa-executor dev status
niwa-executor dev stop
```

The bootstrap installs into `~/.niwa/` and registers one launchd/systemd user
service. Running multiple Niwa clones against the same user home is not
supported.

## First Project

Niwa works on existing git repositories with a clean working tree.

1. Open the UI and create a project:
   - `slug`: lowercase identifier, e.g. `playground`.
   - `name`: display name.
   - `kind`: `library`, `web-deployable`, or `script`.
   - `local_path`: absolute path to the repo.
   - `git_remote`: optional GitHub remote for PR automation.
   - `autonomy_mode`: `safe` opens PRs for human merge; `dangerous` can merge
     automatically after verification.
   - `deploy_type`: `static` or `process`.
   - `deploy_trigger`: `manual`, `on_done`, or `on_merge`.
   - `public_enabled`: default `false`; only explicit public projects are routed
     by generated Caddy config.

2. Create a task. Current flow:
   triage -> plan -> execute -> verify -> review -> finalize -> optional
   deploy. Plan/review use deterministic `fake-json` by default and optional
   `claude-code` modes when configured.

3. Watch task detail. If Claude asks a question, the task moves to
   `waiting_input`; respond in the UI and Niwa resumes the prior Claude session
   when a session handle exists.

4. For web projects, use the Deploys tab or `deploy_trigger` to create static or
   process deployments. Public domain exposure still requires operator-owned
   DNS/Caddy/tunnel setup.

## Gates

Local gates:

```bash
make test
make smoke
make release-gate
```

`make smoke` is deterministic: it uses fake Claude and fake `gh`, an isolated
`NIWA_HOME`, a temporary SQLite DB, and no real credentials or network services.
It writes:

- `.smoke/report.md`
- `.smoke/report.json`
- `.smoke/logs/*`

Generated `.smoke/` output is ignored by git.

CI runs backend tests, frontend tests, and smoke on Python 3.12 and Node 22.
`make smoke-live` is optional and skips clearly unless real Claude/GitHub
credentials are available.

## Operator CLI

Service and dev:

```bash
niwa-executor start|stop|restart|status|logs
niwa-executor dev start --detach
niwa-executor dev stop
niwa-executor dev status
```

Diagnostics and maintenance:

```bash
niwa-executor doctor
niwa-executor doctor --strict
niwa-executor backup [--output /safe/path/niwa-backup.tar.gz]
niwa-executor restore /safe/path/niwa-backup.tar.gz --yes
niwa-executor cleanup --dry-run
```

Publication support:

```bash
niwa-executor set-password
niwa-executor proxy render --ui-domain niwa.example.com --apps-domain apps.example.com --print
niwa-executor proxy validate --ui-domain niwa.example.com --apps-domain apps.example.com
```

`proxy validate` requires a local `caddy` binary. Tests and smoke do not require
Caddy, DNS, TLS, GitHub auth, or real Claude credentials.

## Security Boundary

Niwa is local-first and single-operator. It is not a hosted SaaS and does not
provide a strong OS sandbox. Claude Code runs with the permissions of the user
running Niwa. Before exposing Niwa beyond localhost, enable auth with
`niwa-executor set-password`, use minimal MCP token scopes, keep
`public_enabled=false` unless publication is intended, and review
`docs/SECURITY.md`.

## Known Gaps

- `fake-json` remains the default planner/reviewer for deterministic local and
  CI gates; real `claude-code` modes require operator CLI credentials. The
  `claude-code` reviewer sees bounded verification evidence and diff context,
  not an exhaustive security review.
- Online publication has deterministic Caddy support, but DNS/TLS/Caddy reloads
  remain manual operator steps.
- MCP is HTTP JSON-RPC request/response, not stdio or streaming MCP.
- Niwa does not provide a strong OS sandbox; Claude runs as the Niwa user.

## Architecture

See `docs/HANDBOOK.md`.
