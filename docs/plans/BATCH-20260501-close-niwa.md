# BATCH-20260501-close-niwa

Batch Orchestrator Mode was activated by the human with:

> RUN BATCH ORCHESTRATOR MODE

This plan is the required startup artifact. Product code must not be changed
until the human gives one explicit `go ahead` for this batch plan.

## Status log

- 2026-05-01: Read `AGENTS.md`, `README.md`, `docs/STATE.md`,
  `docs/HANDBOOK.md`, `docs/SPEC.md`, roadmap/phase documents, closure
  markdowns from `/Users/arturowagener/Downloads/niwa-pendientes-cierre/markdown`,
  `Makefile`, CI workflow, executor/models/API/deployments/MCP areas, and the
  main frontend API/app/features.
- 2026-05-01: Current local branch observed during planning:
  `codex/smoke-reproducible-base`.
- 2026-05-01: Working tree already contains an uncommitted `AGENTS.md` change
  adding Batch Orchestrator Mode. This plan file is the only new batch startup
  artifact.
- 2026-05-01: Awaiting human `go ahead` before product code changes.
- 2026-05-01: Human approved with `go ahead`; batch execution started with
  WS-01 smoke reproducible as the first workstream.
- 2026-05-01: WS-01 implemented locally: added `make smoke`,
  `scripts/smoke_v1_1.py`, `scripts/fake_gh_cli.py`, `.smoke/` ignore,
  CI Node 22/smoke step, and removed tracked `.smoke/` artifacts from git.
  Local `make smoke` passed with fake Claude/fake gh in an isolated sandbox.
- 2026-05-01: WS-02 implemented locally on stacked branch
  `codex/auth-global-scopes`: protected projects, tasks, runs, deployments,
  metrics, pulls, and static deploy serving with scopes; fixed AdminPanel to
  verify `/auth/me` before rendering admin content when auth is enabled; added
  backend scope tests and an AdminPanel auth-gate test.
- 2026-05-01: WS-03 first slice implemented locally on stacked branch
  `codex/pipeline-plan-review`: added `TaskPlan`/`TaskReview` models,
  migration, schemas, task API read endpoints, fake JSON planner before
  execution, fake JSON reviewer after verification and before finalize, and
  TaskDetail plan/review display.
- 2026-05-01: WS-04 implemented locally on stacked branch
  `codex/deploy-triggers-hardening`: added project `deploy_trigger`, auto
  deploy for `on_done`/dangerous `on_merge`, process deployment logs under
  `NIWA_HOME/deployments/{slug}/{id}/process.log`, and stop-previous-process
  behavior before starting a new process deployment.
- 2026-05-01: WS-04 precommit gates passed: `cd backend && pytest -q`,
  `cd frontend && npm test`, and `make smoke`.
- 2026-05-01: WS-05 implemented locally on stacked branch
  `codex/domain-caddy-publication`: added project `public_enabled`, made
  static deploy serving anonymous only for explicitly public projects, wired
  Caddy route generation to public projects/active process deployments, and
  added `niwa-executor proxy render|validate`.
- 2026-05-01: WS-05 precommit gates passed: `cd backend && pytest -q`,
  `cd frontend && npm test`, and `make smoke`.
- 2026-05-01: WS-06 implemented locally on stacked branch
  `codex/mcp-openclaw-tools`: added MCP `task_attach`, `deploy_trigger`, and
  `deployment_status`, normalized JSON-RPC error codes, redacted attachment
  content from MCP audit payloads, and updated the OpenClaw integration guide.
- 2026-05-01: WS-06 precommit gates passed: `cd backend && pytest -q`,
  `cd frontend && npm test`, and `make smoke`.
- 2026-05-01: WS-07 implemented locally on stacked branch
  `codex/ui-management-dashboard`: added project dashboard counters, backlog
  search/status filters with hierarchical subtasks, visible cancel/retry
  actions, project settings for autonomy/deploy/publication/repo settings, and
  focused frontend coverage.
- 2026-05-01: WS-07 precommit gates passed: `cd backend && pytest -q`,
  `cd frontend && npm test`, and `make smoke`.
- 2026-05-01: WS-08 implemented locally on stacked branch
  `codex/security-operational-hardening`: added run PID persistence, redacted
  adapter payloads before `run_events`, made Claude subprocesses group-killable,
  extended kill switch to signal recorded active run process groups, and updated
  the security model.
- 2026-05-01: WS-08 precommit gates passed: `cd backend && pytest -q`,
  `cd frontend && npm test`, and `make smoke`.
- 2026-05-01: WS-08 postcommit gate exposed an SSE terminal-drain regression;
  fixed the stream loop to drain new events before checking terminal state.

## Current repo state

### Already exists

- Local-first FastAPI backend with SQLite models for projects, tasks, task runs,
  run events, attachments, pulls, deployments, and auth tokens.
- React frontend with project list, project detail, task detail, deploys tab,
  admin panel, system/help views, and basic tests.
- Executor loop that can run task lifecycle from queue to run, invoke triage,
  call an adapter, verify, finalize, and persist run events.
- Auth subsystem with password setup/login/logout/session, API tokens, scopes,
  and audit logging utilities.
- Deployment subsystem with deployment records, static/process service paths,
  process manager, rollback/stop endpoints, and build log redaction.
- MCP JSON-RPC endpoint with project/task/pull tools and token handling.
- Caddy rendering helper in `backend/app/network/caddy.py`.
- CI workflow for backend and frontend tests.
- Roadmap and phase documents describing smoke, pipeline, UI, deploy, domain,
  security, MCP, QA, and docs closure.

### Partially implemented

- Auth is implemented but not consistently enforced on critical routers such as
  projects, tasks, runs, pulls, deployments, and metrics.
- Deployment exists but is not fully integrated into task completion, merge
  events, project settings, public exposure rules, or durable process logs.
- MCP exists but lacks tools such as `task_attach`, deployment trigger/status,
  and fuller JSON-RPC coverage.
- Caddy rendering exists but is not connected to CLI commands and references a
  route shape (`public_enabled`) that the project model/API does not expose.
- UI can operate projects/tasks/deployments at a basic level but lacks dashboard,
  backlog filters/search, hierarchy, plan/review display, settings, and richer
  deployment controls.
- Security has pieces such as auth, redaction helpers, audit utilities, and kill
  switch, but redaction is not uniformly applied to run events and subprocess
  cancellation is not proven as real process cancellation.
- CI runs tests, but it does not run smoke and uses Node 20 while the README says
  Node.js 22+.

### Documented only or mostly documented

- Formal planning/review pipeline with `TaskPlan`, `TaskReview`, explicit
  planning/reviewing states, approval, and request-changes loop.
- Reproducible smoke suite with fake Claude, fake GitHub CLI, isolated sandbox,
  reports, and CI artifact behavior.
- `make smoke`.
- `niwa-executor proxy render` and `proxy validate`.
- Project publication model with `public_enabled` and deploy triggers.
- Backup/restore CLI, migration-from-fixture tests, smoke UI, runbooks, and
  production-oriented incident/domain/MCP operations docs.

### Broken, missing, or misaligned

- `.smoke/` is tracked in the repo but should be generated output and ignored.
- `Makefile` has no `smoke` target.
- CI has no smoke gate and is misaligned with README Node version.
- `docs/SPEC.md` is historical MVP material and says no auth, no MCP, and no
  wildcard subdomains, while the current product and closure roadmap explicitly
  target auth, MCP, deployments, domains, and online exposure.
- `docs/STATE.md` says the next step is smoke v1.1, but smoke support is absent.
- Backend test baseline cannot be claimed from this planning pass because the
  active local environment observed earlier did not have `pytest` installed.
- Admin auth gate appears optimistic: frontend admin state starts as authenticated
  and should verify `/auth/me` when auth is enabled before showing protected UI.
- Executor has no formal persisted plan/review objects.
- Critical areas require explicit approval before edits:
  `backend/app/executor/`, `backend/app/verification/`, `backend/app/finalize.py`,
  and `backend/app/adapters/`.

## Batch objective

Close Niwa toward a coherent local-first product:

- Project management system usable locally from UI.
- Tasks managed through UI with visible lifecycle, backlog, subtasks, and
  recovery controls.
- Executor flow that can triage, plan, execute, verify, review, request changes,
  and finalize with persisted evidence.
- Local deploy and online publication through domains/subdomains where explicitly
  enabled.
- MCP surface usable by OpenClaw or other JSON-RPC clients.
- Minimum security posture for online exposure: auth, scopes, redaction, audit,
  kill/cancel behavior, and operational guardrails.
- Reproducible smoke and CI gates that do not require real Claude, real GitHub,
  real credentials, or external network access.

## Strategy recommendation

Recommended strategy: multiple PRs created by this same batch session, not one
large integration PR.

Reasoning:

- The total scope crosses backend models/migrations, executor, deploy, MCP, UI,
  CI, security, and docs. A single integration PR would be too hard to review,
  test, and rollback.
- Smoke should land first so later PRs can prove behavior with deterministic
  evidence.
- Auth and pipeline changes affect critical product behavior and should be
  isolated.
- UI work should follow API/model contracts rather than driving them.
- A short-lived integration branch can be used locally if needed, but review
  should happen as small ordered PRs.

Expected PR partition:

1. Smoke reproducible base.
2. Smoke in CI and version/artifact alignment.
3. Auth coverage and Admin AuthGate.
4. Audit/redaction for mutations and run events.
5. TaskPlan/TaskReview models, migrations, and API read surface.
6. Executor planning/review state machine and approval loop.
7. Deploy triggers, process logs, and deployment hardening.
8. Domain/publication model and Caddy CLI.
9. MCP tool completion and JSON-RPC tests.
10. UI dashboard/backlog/task detail plan-review.
11. UI settings/deploy/domain controls.
12. Operational safety: cancellation, limits, locking, backup/restore.
13. QA fixtures, migration tests, smoke UI if approved.
14. Docs/doctor/runbooks alignment.

The exact number may shrink if adjacent PRs are small and independently tested,
but the batch should avoid one oversized PR.

## Execution order

1. WS-01 Smoke reproducible.
2. WS-02 Auth global and safe exposure.
3. WS-03 Pipeline formal plan/review.
4. WS-04 Deploy integrated and protected.
5. WS-05 Domain, Caddy, and subdomains.
6. WS-06 MCP/OpenClaw complete.
7. WS-07 UI project management.
8. WS-08 Security and operational isolation.
9. WS-09 QA/CI/productization.
10. WS-10 Docs/operability/doctor.

## Workstreams

### WS-01 Smoke reproducible

Purpose:

- Create deterministic smoke coverage that proves core product flows without
  real Claude, real GitHub, real credentials, or external network calls.

Probable files:

- `.gitignore`
- `Makefile`
- `.github/workflows/ci.yml`
- `scripts/smoke_v1_1.py`
- `scripts/fake_gh_cli.py`
- `tests/fixtures/` or `backend/tests/fixtures/` if existing patterns fit
- Generated but ignored `.smoke/report.md`, `.smoke/report.json`, `.smoke/logs/`

Dependencies:

- None. This should land first.

Concrete tasks:

- Remove tracked `.smoke/` outputs from the repo and add `.smoke/` to
  `.gitignore`.
- Add `make smoke`.
- Add deterministic smoke runner in an isolated temp `NIWA_HOME`.
- Add fake Claude behavior and fake `gh` CLI behavior.
- Cover health/readiness, project create, task execute/verify/finalize, split,
  waiting input/resume, attachments, and static deploy.
- Emit `.smoke/report.md` and `.smoke/report.json`.
- Add smoke to CI if reliable within the same PR; otherwise split CI integration
  into the next PR.

Risks:

- Smoke may reveal real executor/deploy bugs. If fixing those requires touching
  critical areas, stop and confirm the relevant plan slice before editing them.
- The current local environment may lack backend test dependencies; setup must
  be documented rather than hidden.

Specific tests:

- `make smoke`
- `cd backend && pytest -q`
- `cd frontend && npm test`
- CI smoke job once added

Acceptance:

- `make smoke` runs from a clean checkout and writes deterministic reports.
- Smoke uses only fake/local dependencies.
- `.smoke/` is generated and ignored.
- CI artifact behavior is defined.

Estimated size:

- Large; likely 1-2 PRs.

Critical areas:

- No planned product critical edits. Critical only if executor/verification/
  finalize/adapters must be changed to make smoke truthful.

### WS-02 Auth global and safe exposure

Purpose:

- Ensure online exposure is not accidentally unauthenticated while preserving
  local no-password mode.

Probable files:

- `backend/app/api/projects.py`
- `backend/app/api/tasks.py`
- `backend/app/api/runs.py`
- `backend/app/api/pulls.py`
- `backend/app/api/deployments.py`
- `backend/app/api/metrics.py`
- `backend/app/api/deploy.py`
- `backend/app/auth/deps.py`
- `backend/tests/test_auth*.py`
- `backend/tests/test_*auth*.py`
- `frontend/src/features/AdminPanel.tsx`
- `frontend/src/api.ts`

Dependencies:

- Best after WS-01 so auth regressions are caught by smoke.

Concrete tasks:

- Apply `require_auth`/`require_scope` to critical routers.
- Keep public only health/readiness/auth setup-login-status and explicitly public
  deployment serving when `public_enabled` exists.
- Enforce scopes such as `read`, `task:create`, `task:write`, `deploy`, `merge`,
  and `admin`.
- Fix AdminPanel/AuthGate to call `/auth/me` before showing protected UI when
  auth is enabled.
- Add tests for auth-disabled local mode and auth-enabled protected mode.

Risks:

- Existing UI tests and local flows may assume unauthenticated access.
- Public deployment serving depends on WS-05 if `public_enabled` is not yet in
  the model.

Specific tests:

- Backend auth/scope tests for every protected router.
- Frontend tests for admin auth gate behavior.
- `make smoke` with auth-disabled local mode.

Acceptance:

- Critical APIs are protected when auth is enabled.
- Local mode remains frictionless when no password is configured.
- Token scopes are enforced and covered.

Estimated size:

- Large; likely 1-2 PRs.

Critical areas:

- No executor critical area expected.

### WS-03 Pipeline formal plan/review

Purpose:

- Persist and expose a formal LLM pipeline: triage, planning, approval,
  execution, verification, review, request changes, and finalization.

Probable files:

- `backend/app/models/*.py`
- `backend/app/db.py` or migration utilities
- `backend/app/executor/core.py`
- `backend/app/executor/*`
- `backend/app/verification/*`
- `backend/app/finalize.py`
- `backend/app/api/tasks.py`
- `backend/app/api/runs.py`
- `backend/tests/test_executor*.py`
- `backend/tests/test_models.py`
- `frontend/src/api.ts`
- `frontend/src/features/TaskDetail.tsx`

Dependencies:

- WS-01 smoke and WS-02 auth should land first.

Concrete tasks:

- Add `TaskPlan` and `TaskReview` persistence with migrations.
- Add explicit pipeline states if compatible with existing status semantics:
  `triaging`, `planning`, `waiting_approval`, `executing`, `verifying`,
  `reviewing`.
- Add fake/JSON planner before code execution.
- Add optional manual approval before execution.
- Add fake/JSON reviewer after verify and before finalize.
- Implement bounded `request_changes` loop.
- Expose plan/review through API and UI read models.

Risks:

- This is the highest behavioral-risk workstream because it changes lifecycle
  contracts.
- Existing tests may encode old statuses.
- Need a compatibility path for old tasks and old UI filters.

Specific tests:

- Model/migration tests from old fixture to head.
- Executor tests for happy path, approval wait/resume, review success, review
  request changes, and loop limit.
- API tests for plan/review retrieval.
- Smoke updated to assert plan/review evidence once implemented.

Acceptance:

- Every executed task has persisted plan/review evidence when the new pipeline
  is active.
- Waiting approval and request-changes loops are deterministic and bounded.
- Finalization is not reached before review passes.

Estimated size:

- Extra large; split into 2-3 PRs.

Critical areas:

- Yes. Explicitly touches `backend/app/executor/`, likely
  `backend/app/verification/`, and possibly `backend/app/finalize.py` and
  `backend/app/adapters/`.

### WS-04 Deploy integrated and protected

Purpose:

- Make deployment a coherent, protected product workflow connected to project
  settings, task completion, and merge outcomes.

Probable files:

- `backend/app/models/project.py`
- `backend/app/models/deployment.py`
- `backend/app/api/deployments.py`
- `backend/app/deployments/service.py`
- `backend/app/deployments/process_manager.py`
- `backend/app/executor/core.py`
- `backend/app/finalize.py`
- `backend/tests/test_deployments*.py`
- `frontend/src/api.ts`
- `frontend/src/features/DeploysTab.tsx`

Dependencies:

- WS-01 and WS-02. Some trigger behavior depends on WS-03 final states.

Concrete tasks:

- Protect deployment endpoints with auth/scopes.
- Add `deploy_trigger` project setting: `manual`, `on_done`, `on_merge`.
- Trigger deploy after task done or merge when configured.
- Store useful process logs under
  `~/.niwa/deployments/{slug}/{id}/process.log`.
- Stop previous active process before making a new process deployment active.
- Improve stop/rollback/healthcheck behavior and tests.

Risks:

- Auto-deploy can create surprising side effects if not strictly project-scoped
  and opt-in.
- Process management needs cleanup that works across failures and restarts.

Specific tests:

- Deployment API auth/scope tests.
- Static deploy tests.
- Process deploy lifecycle tests including stop previous process.
- Auto-trigger tests for `on_done`/`on_merge`.
- Smoke static deploy path.

Acceptance:

- Deploy endpoints require deploy/admin scope where appropriate.
- Manual deploy remains available.
- Auto-deploy is opt-in and recorded.
- Logs are available and redacted.

Estimated size:

- Large; likely 1-2 PRs.

Critical areas:

- Yes if hooking into executor completion or finalize/merge.

### WS-05 Domain, Caddy, and subdomains

Purpose:

- Prepare explicit safe publication through domains/subdomains and Caddy
  rendering/validation.

Probable files:

- `backend/app/models/project.py`
- `backend/app/schemas/project.py`
- `backend/app/api/projects.py`
- `backend/app/api/deploy.py`
- `backend/app/network/caddy.py`
- `backend/app/cli.py` or executor CLI entrypoint
- `backend/tests/test_caddy*.py`
- `backend/tests/test_deploy_public*.py`
- `frontend/src/api.ts`
- `frontend/src/features/ProjectSettings*.tsx`
- Docs in WS-10

Dependencies:

- WS-02 auth and WS-04 deployment model.

Concrete tasks:

- Add `public_enabled` default false to project model/schema/API/UI.
- Connect `backend/app/network/caddy.py` to CLI commands:
  `niwa-executor proxy render` and `niwa-executor proxy validate`.
- Render Caddy routes only for public projects.
- Validate `base_domain`, `ui_domain`, `apps_domain`, and `public_scheme`
  behavior.
- Fix static/process route rendering and asset path behavior.

Risks:

- Caddy routing is easy to make plausible but wrong for static assets or process
  upstream paths.
- Publication must never become public by default.

Specific tests:

- Caddy render tests for no-public-project, static, process, and mixed routes.
- CLI render/validate tests.
- API tests for `public_enabled`.
- Smoke extension if a local Caddy-free validation mode is available.

Acceptance:

- No project is public unless explicitly enabled.
- Caddy output is deterministic and validates against expected snapshots or
  structured assertions.
- Docs explain domain variables and publication model.

Estimated size:

- Medium to large; likely 1 PR plus docs.

Critical areas:

- No executor critical area expected.

### WS-06 MCP/OpenClaw complete

Purpose:

- Make the MCP JSON-RPC surface useful and safe for OpenClaw and other clients.

Probable files:

- `backend/app/mcp/server.py`
- `backend/app/mcp/*`
- `backend/app/api/mcp.py`
- `backend/tests/test_mcp*.py`
- `docs/integrations/OPENCLAW.md`
- `frontend/src/api.ts` only if UI exposes MCP token/help

Dependencies:

- WS-02 auth/scopes. WS-04 for deployment tools. WS-03 if plan/review tool data
  is exposed.

Concrete tasks:

- Add `task_attach`.
- Add deployment tool(s), likely `deploy_trigger` and `deployment_status`.
- Use service-layer functions only; no direct MCP filesystem writes.
- Normalize JSON-RPC errors.
- Verify token scopes for every write action.
- Update OpenClaw docs.

Risks:

- MCP tools can bypass UI/API assumptions if they call internals directly.
- Attachment handling must avoid arbitrary file access.

Specific tests:

- JSON-RPC list/call tests.
- Scope denial tests.
- Attachment success/failure tests.
- Deployment tool tests.

Acceptance:

- OpenClaw can list projects, create/respond/cancel/retry tasks, attach files,
  trigger deploy, and read deploy status through documented tools.
- Errors are JSON-RPC shaped and stable.

Estimated size:

- Medium; likely 1 PR.

Critical areas:

- No executor critical area expected unless task lifecycle behavior changes.

### WS-07 UI project management

Purpose:

- Turn the frontend into an actual project/task management surface rather than a
  minimal API browser.

Probable files:

- `frontend/src/App.tsx`
- `frontend/src/api.ts`
- `frontend/src/features/ProjectList.tsx`
- `frontend/src/features/ProjectDetail.tsx`
- `frontend/src/features/TaskList.tsx`
- `frontend/src/features/TaskDetail.tsx`
- `frontend/src/features/DeploysTab.tsx`
- New `frontend/src/features/*` components for dashboard, backlog, settings,
  timeline, plan/review, subtasks, and deploy/domain settings
- Frontend tests beside features

Dependencies:

- WS-02 for auth behavior.
- WS-03 for plan/review API.
- WS-04/WS-05 for deploy/domain settings.

Concrete tasks:

- Add dashboard/global overview.
- Add backlog filters/search and status grouping.
- Display hierarchical subtasks.
- Make cancel/retry visible where allowed.
- Add unified task timeline.
- Display TaskPlan and TaskReview in task detail.
- Add project settings for deploy trigger, publication, domain, and deploy
  commands/paths.

Risks:

- UI scope can expand quickly. Keep it utilitarian and tied to API contracts.
- Need responsive layout without hiding operational controls.

Specific tests:

- React Testing Library tests for dashboard, backlog filters, task detail
  plan/review, settings forms, deploy controls.
- `cd frontend && npm test`
- `make smoke-ui` only if approved and dependency story is settled.

Acceptance:

- A user can manage projects/tasks/deploy settings from UI without dropping to
  API calls for normal flows.
- Plan/review/deployment state is visible in task detail.
- Existing frontend tests remain green.

Estimated size:

- Extra large; split into 2-3 PRs.

Critical areas:

- No backend critical area expected.

### WS-08 Security and operational isolation

Purpose:

- Reduce operational risk when Niwa is exposed online or running subprocesses
  locally.

Probable files:

- `backend/app/security/redaction.py`
- `backend/app/executor/core.py`
- `backend/app/deployments/process_manager.py`
- `backend/app/ops.py` or ops modules
- `backend/app/config.py`
- `backend/app/models/*.py`
- `backend/tests/test_security*.py`
- `backend/tests/test_ops*.py`
- Docs/runbooks in WS-10

Dependencies:

- WS-01 and WS-02. Some locking/cancel behavior depends on WS-03/WS-04.

Concrete tasks:

- Apply redaction before persisting `run_events`.
- Implement realistic cancellation of active subprocesses where possible.
- Add creation/concurrency limits that respect config.
- Add project locking before any real parallelism.
- Add backup/restore CLI if it fits safely in this batch.
- Update threat model.

Risks:

- Process cancellation and locking can create deadlocks or orphan processes.
- Redaction can over-redact useful debugging data or under-redact secrets.

Specific tests:

- Redaction tests for run events and deployment logs.
- Cancellation tests for active task/process.
- Concurrency/limit tests.
- Backup/restore round-trip test if implemented.

Acceptance:

- Secrets/tokens are not persisted in run event payloads.
- Kill/cancel behavior stops future work and terminates active owned processes
  when supported.
- Limits and locks fail closed with clear errors.

Estimated size:

- Large; likely 1-2 PRs.

Critical areas:

- Yes if touching executor cancellation, adapters, or process execution paths.

### WS-09 QA/CI/productization

Purpose:

- Make quality gates reproducible and broad enough to trust product closure.

Probable files:

- `.github/workflows/ci.yml`
- `Makefile`
- `backend/tests/fixtures/*`
- `backend/tests/test_migrations*.py`
- `backend/tests/test_smoke_contract*.py`
- `frontend/src/**/*.test.tsx`
- `scripts/*`
- Possibly Playwright config if explicitly approved

Dependencies:

- All feature workstreams; can also add incremental tests alongside each PR.

Concrete tasks:

- Keep backend tests green and expand coverage for models/migrations/API/MCP/
  deploy/security.
- Keep frontend tests green and expand UI coverage.
- Add deterministic fixtures: library, script, static web, process web.
- Add migration tests from old fixture to head.
- Align CI Node version with README Node 22.
- Add smoke artifact upload on failure.
- Add `make smoke-ui` with Playwright only after dependency approval if it is not
  already declared.

Risks:

- QA can become a catch-all. It should harden already-defined behavior, not add
  new product scope.
- Playwright is a likely new dependency and needs explicit approval unless it is
  already declared in package manifests.

Specific tests:

- `cd backend && pytest -q`
- `cd frontend && npm test`
- `make smoke`
- `make smoke-ui` if added
- CI workflow run evidence

Acceptance:

- Gates are documented, deterministic, and produce literal output.
- CI matches local documented versions.
- No final completion claim is made without literal gate evidence.

Estimated size:

- Medium to large; spread across PRs plus final hardening PR.

Critical areas:

- Only if tests require product fixes in critical backend areas.

### WS-10 Docs, operability, and doctor

Purpose:

- Align user/operator documentation with the actual product and provide local
  diagnostics.

Probable files:

- `README.md`
- `docs/STATE.md`
- `docs/HANDBOOK.md`
- `docs/SPEC.md`
- `docs/roadmap/*`
- `docs/runbooks/*`
- `docs/integrations/OPENCLAW.md`
- `backend/app/cli.py` or doctor command implementation
- `backend/tests/test_doctor*.py`

Dependencies:

- Should be updated incrementally, with final alignment after implementation.

Concrete tasks:

- Add or complete `niwa doctor`.
- Warn about insecure `NIWA_HOME` permissions.
- Align README/STATE/HANDBOOK/SPEC with implemented auth/pipeline/deploy/MCP.
- Move root roadmap material to `docs/roadmap/` if needed.
- Add runbooks for local install, VPS/domain setup, deploy, MCP/OpenClaw, smoke,
  backup/restore, and incidents.

Risks:

- Docs can drift if finalized before implementation stabilizes.
- Doctor must report actionable warnings, not vague advice.

Specific tests:

- Doctor command tests.
- Link/path sanity checks if existing tooling exists.
- Final manual doc review against implemented behavior.

Acceptance:

- New operator can install, run, smoke, expose, deploy, connect MCP, backup, and
  recover from documented runbooks.
- STATE reflects exact current product state and known limitations.

Estimated size:

- Medium; likely 1 final docs/doctor PR plus incremental doc updates.

Critical areas:

- No executor critical area expected.

## Cross-workstream dependencies

- Smoke first, because every later PR needs deterministic evidence.
- Auth before public deploy/MCP/domain work, because exposure without auth is the
  largest security risk.
- Pipeline models/API before UI plan/review display.
- Deploy triggers before Caddy/publication settings.
- MCP deployment tools after deploy services are stable.
- UI after backend contracts are stable.
- Security hardening should be incremental, with final locking/cancel passes
  after pipeline/deploy behavior is clear.
- Docs/doctor should be updated throughout but finalized last.

## Rollback strategy

- Prefer small PRs with clear migration boundaries.
- For schema changes, add backwards-compatible columns/tables with defaults
  first, then use them in later PRs.
- Keep feature defaults conservative:
  - auth-disabled local mode remains available only when no password is set,
  - `public_enabled` defaults false,
  - `deploy_trigger` defaults `manual`,
  - approval gates default to current local-safe behavior unless explicitly
    enabled.
- If a workstream destabilizes critical paths, revert that PR independently
  rather than reverting the whole batch.
- Generated artifacts such as `.smoke/` must be ignored and reproducible.

## Final gates

Required before final batch delivery:

- `cd backend && pytest -q`
- `cd frontend && npm test`
- `make smoke`

Additional gates once introduced by the batch:

- Backend targeted tests for auth scopes, pipeline, migrations, deploy, Caddy,
  MCP JSON-RPC, redaction, cancellation, locking, backup/restore, and doctor.
- Frontend targeted tests for dashboard, backlog, task detail plan/review,
  settings, deployment controls, and auth gate.
- `make smoke-ui` if Playwright or equivalent smoke UI support is approved and
  added.
- CI workflow evidence for the final pushed commits.

Every PR body created by this batch must include literal gate output and the
exact commit SHA measured. The batch is not complete without literal evidence.

## Safety rules for this batch

- No product code changes before the human approves this plan with one explicit
  `go ahead`.
- No PRs opened before approval.
- No destructive operations.
- No `git push --force`.
- No `--no-verify`.
- No self-merge without explicit human instruction.
- No new dependencies without calling them out and asking before adding them.
- No secrets, production credentials, paid services, or external infrastructure
  changes without explicit confirmation.
- No scope expansion beyond this approved batch plan; add a status-log note and
  ask if scope changes.
- Do not ignore failing tests.
- Do not claim completion without literal evidence.

## Approval checkpoint

This plan intentionally names critical areas for WS-03, WS-04, WS-08, and
possibly WS-09. Human approval of this batch plan is required before those areas
can be edited.

Awaiting explicit human:

> go ahead
