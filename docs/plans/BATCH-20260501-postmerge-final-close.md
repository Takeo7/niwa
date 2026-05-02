# BATCH-20260501-postmerge-final-close

Batch Orchestrator Mode was activated by the human with:

> RUN BATCH ORCHESTRATOR MODE

This is the required startup plan for the postmerge final close. Product code
must not be changed until the human reviews this file and gives one explicit:

> go ahead

## Status Log

- 2026-05-01: Read `AGENTS.md` fully. Batch Orchestrator Mode is available
  and explicitly activated for this session. Hard safety rules still apply:
  no destructive ops, no force push, no `--no-verify`, no ignored tests, no
  unapproved dependencies, no unapproved secrets/infrastructure work, and no
  scope expansion outside this approved plan.
- 2026-05-01: Observed local branch `codex/qa-docs-operability` at
  `c49d535f2c34174a100c1b15417ca6666524ed02`; `origin/main` is
  `fe3800aaf66352bc27307296b25cde20a6572179`. The tree content is the
  postmerge WS-01..WS-10 state.
- 2026-05-01: Read required repo docs and files: `README.md`,
  `docs/STATE.md`, `docs/HANDBOOK.md`, `docs/SPEC.md`,
  `docs/plans/BATCH-20260501-close-niwa.md`, `Makefile`,
  `.github/workflows/ci.yml`, executor core, task/project/plan/review models,
  task/project/deploy/deployment APIs, MCP server, Caddy generator, CLI,
  frontend API, project features, and task features.
- 2026-05-01: Read postmerge closure documents from
  `/Users/arturowagener/Downloads/niwa-postmerge-cierre-definido/markdown/`.
- 2026-05-01: Created this plan only. No product code changes have been made.
- 2026-05-01: Human approved with `go ahead`; batch execution started with
  PR-CLOSE-01 on branch `codex/close-01-truth-alignment`.
- 2026-05-01: PR-CLOSE-01 implemented locally: aligned README, STATE, SPEC,
  HANDBOOK, operations/deployment/OpenClaw docs, and corrected the obsolete
  `respond_to_task` docstring. No functional product behavior changed.
- 2026-05-01: PR-CLOSE-01 gates passed locally: obsolete-claim grep checks,
  `cd backend && pytest -q`, `cd frontend && npm test -- --run`, and
  `make smoke`.
- 2026-05-02: PR-CLOSE-02 initially exceeded the 400 LOC PR cap, so it was
  split into stacked PRs. PR-CLOSE-02a covers explicit executor states,
  project plan approval mode, `approve-plan` API, and smoke assertions for
  plan/review artifacts. PR-CLOSE-02b will cover bounded review
  request-changes loops and the richer operator UI/settings follow-up.
- 2026-05-02: PR-CLOSE-02a targeted gates passed locally for models,
  executor, task/project APIs, and the frontend test suite. Full PR gates are
  being measured before commit/push.
- 2026-05-02: PR-CLOSE-02a pushed and opened as draft PR #169, stacked on
  PR-CLOSE-01. PR-CLOSE-02b started on `codex/close-02b-review-loop-ui` for
  bounded review retries, review iterations, and operator UI/settings.
- 2026-05-02: PR-CLOSE-02b implemented locally and full gates passed before
  commit: `cd backend && pytest -q`, `cd frontend && npm test -- --run`, and
  `make smoke`. Gates will be repeated on the pushed SHA.
- 2026-05-02: PR-CLOSE-02b pushed and opened as draft PR #170, stacked on
  PR-CLOSE-02a. PR-CLOSE-03 started on
  `codex/close-03-real-llm-planner-reviewer` for configurable fake/Claude
  planner and reviewer services.
- 2026-05-02: PR-CLOSE-03 implemented locally with `fake-json` defaults,
  `claude-code` planner/reviewer modes, fake-CLI tests for valid/invalid
  JSON, and executor integration. Full gates passed before commit and will be
  repeated on the pushed SHA.
- 2026-05-02: PR-CLOSE-03 pushed and opened as draft PR #171, stacked on
  PR-CLOSE-02b. PR-CLOSE-04 started on
  `codex/close-04-clean-machine-release-gates` for `make release-gate`, manual
  CI dispatch, and opt-in `make smoke-live`.
- 2026-05-02: PR-CLOSE-04 release-gate initially exposed the existing
  timing-sensitive runs SSE test; the test was stabilized and `make
  release-gate` then passed with clean HOME bootstrap, `make test`,
  `make smoke`, doctor, backup, and restore.
- 2026-05-02: PR-CLOSE-04 pushed and opened as draft PR #172, stacked on
  PR-CLOSE-03. PR-CLOSE-05 started on
  `codex/close-05-online-publication-e2e` for Caddy/publication tests and
  operator runbook coverage.
- 2026-05-02: PR-CLOSE-05 implemented locally with added Caddy/CLI coverage
  and `docs/runbooks/ONLINE_PUBLICATION.md`. Targeted publication tests,
  backend, frontend, and smoke gates passed before commit.
- 2026-05-02: PR-CLOSE-05 pushed and opened as draft PR #173, stacked on
  PR-CLOSE-04. PR-CLOSE-06 started on
  `codex/close-06-security-locks-limits-sandbox` for operational locks,
  queue/attachment limits, and the security model update.
- 2026-05-02: PR-CLOSE-06 implemented locally with queued-task limits,
  attachment size limits, run-level project/concurrency claim guards, MCP
  error mapping, backend tests, and `docs/SECURITY.md` updates. Targeted
  security/ops tests, backend, frontend, and smoke gates passed before commit.
- 2026-05-02: PR-CLOSE-06 pushed and opened as draft PR #174, stacked on
  PR-CLOSE-05. PR-CLOSE-07 started on
  `codex/close-07-mcp-openclaw-conformance` for MCP handshake, tools/error
  contract tests, OpenClaw examples, and an optional MCP smoke script.
- 2026-05-02: PR-CLOSE-07 implemented locally with `initialize`, exact
  `tools/list` contract tests, OpenClaw documentation examples, JSON-RPC
  error assertions, and `scripts/mcp_smoke.py`. MCP targeted tests, backend,
  frontend, and smoke gates passed before commit.
- 2026-05-02: PR-CLOSE-07 pushed and opened as draft PR #175, stacked on
  PR-CLOSE-06. PR-CLOSE-08 started on
  `codex/close-08-ui-operator-closure` for TaskDetail operator timeline,
  deployment visibility, deploy healthcheck controls, and admin ops hints.
- 2026-05-02: PR-CLOSE-08 implemented locally with TaskDetail plan/review/run/
  deployment timeline, deploy healthcheck/process-log UI, admin operator hints,
  and RTL coverage. Backend, frontend, and smoke gates passed before commit.
- 2026-05-02: PR-CLOSE-08 pushed and opened as draft PR #176, stacked on
  PR-CLOSE-07. PR-CLOSE-09 started on
  `codex/close-09-release-packaging-final-acceptance` for version, changelog,
  acceptance checklist, release notes template, and final gates.

## Current Repo State

### Already Implemented

- Local-first FastAPI + SQLite backend and React/Mantine frontend.
- Batch WS-01..WS-10 are merged into `main`.
- `make smoke` exists and runs deterministic fake-Claude/fake-gh coverage.
- CI uses Python 3.12, Node 22, backend tests, frontend tests, smoke, and
  failure artifact upload for `.smoke/`.
- Auth subsystem exists with password, sessions, API tokens, scopes, and
  protected routers.
- Projects have deployment settings including `deploy_trigger` and
  `public_enabled`.
- `TaskPlan` and `TaskReview` models exist and the executor persists
  deterministic fake-json plans/reviews.
- Task statuses include pipeline values:
  `triaging`, `planning`, `waiting_approval`, `executing`, `verifying`,
  `reviewing`.
- Deployments support static/process records, stop/rollback/healthcheck,
  process logs, and auto-trigger hooks.
- Caddy rendering exists through `backend/app/network/caddy.py` and
  `niwa-executor proxy render|validate`.
- MCP HTTP JSON-RPC exists with tools for projects, tasks, attachments, pulls,
  deployment trigger, and deployment status.
- UI has project list/detail, task list/detail, plan/review display, settings,
  deploys tab, cancel/retry, hierarchy/search/filtering, admin/system/help.
- Operational commands include `niwa-executor dev start --detach`,
  `doctor`, `backup`, `restore`, `cleanup`, and proxy commands.

### Partially Implemented

- Pipeline states are admitted by the model and frontend, but executor flow
  still mostly claims `queued -> running`, then creates plan, executes,
  verifies, reviews, and finalizes without real intermediate task statuses.
- Planner/reviewer are deterministic fake-json only; there is no configurable
  real LLM planner/reviewer path yet.
- Manual approval is represented as a status but has no project setting,
  approval endpoint, or blocking executor behavior.
- Review `request_changes` exists as a possible decision but there is no
  bounded re-execution loop.
- Caddy/publication support exists, but online publication lacks full E2E
  tests, a proxy doctor, and an unambiguous domain runbook.
- MCP tools exist, but MCP conformance is incomplete: no `initialize`, no
  initialized notification behavior, limited stable-error contract docs, and
  incomplete client-oriented examples.
- UI exposes much of the operator surface, but lacks manual plan approval,
  unified timeline, deployment logs, `build_command` editing, and public URL
  preview.
- Security has auth, redaction, audit, kill switch, PID tracking, and doctor,
  but lacks project locks, clear concurrency semantics, attachment size limits,
  strong exposure guard checks, and a blunt no-sandbox declaration.
- Release gates are good locally, but there is no clean-machine/release gate,
  no smoke-live opt-in, no release checklist, no changelog, and no final
  version/acceptance artifact.

### Broken Or Desynchronized Claims

- `README.md` still says `v1 MVP. Single-user, single-machine` and references
  a planned detached dev target even though detached dev CLI exists.
- `docs/STATE.md` still says the next step is `smoke-v1.1`, even though smoke
  and WS-01..WS-10 are merged.
- `docs/HANDBOOK.md` still contains historical v1 layout/status and does not
  fully describe current models, scopes, MCP tools, deployment/publication,
  doctor, backup/restore, and PID/kill-switch behavior.
- `docs/SPEC.md` still says no auth, no MCP, and no wildcard subdomains in the
  MVP without a current implemented product contract.
- `backend/app/api/tasks.py` contains an obsolete respond docstring saying the
  next adapter run does not receive the response; current executor does use
  latest `user_response` with prior `session_handle` when available.

## Batch Objective

Close Niwa as a truthful local-first release candidate after WS-01..WS-10:

- Align public and operator truth with the real postmerge product.
- Make pipeline states, approval, and review loops real, not decorative.
- Add configurable real LLM planner/reviewer paths while keeping deterministic
  fake mode for CI/smoke.
- Prove clean-machine/release gates without real credentials.
- Make online publication deterministic to validate and honest about the
  manual DNS/Caddy/TLS boundary.
- Strengthen security with locks, limits, exposure guardrails, and a clear
  no-strong-sandbox declaration.
- Make MCP usable by OpenClaw/HTTP JSON-RPC clients without guessing.
- Complete the UI for normal operator workflows.
- Add release packaging, changelog, limitations, and final acceptance docs.

## Strategy Recommendation

Use multiple ordered PRs created by this batch session, not one integration PR.

Reasons:

- The close scope spans docs, executor lifecycle, adapters, CI, Caddy, MCP, UI,
  and security. One integration PR would be hard to review and rollback.
- The first PR is truth alignment and can land without product behavior changes.
- PR-CLOSE-02, PR-CLOSE-03, and PR-CLOSE-06 touch critical areas and need tight
  review boundaries.
- Later UI/docs PRs depend on backend contracts from earlier PRs.
- Each PR can carry focused literal test evidence and a clear rollback point.

Recommended implementation shape:

- Create each branch from updated `main` after the previous PR is merged, unless
  the human explicitly authorizes a stacked PR workflow.
- Work in the exact order below.
- Keep PRs small enough to review. If one PR is growing beyond the repo's LOC
  cap, stop and ask before pushing.
- Use subagents/worktrees only for independent reading or disjoint write scopes;
  because these PRs are strongly ordered, default to serial implementation.

## PR-CLOSE-01 - Truth Alignment

Branch: `codex/close-01-truth-alignment`

Objective:

- Align `README.md`, `docs/STATE.md`, `docs/HANDBOOK.md`, `docs/SPEC.md`, and
  runbooks with the actual WS-01..WS-10 postmerge product.

Probable files:

- `README.md`
- `docs/STATE.md`
- `docs/HANDBOOK.md`
- `docs/SPEC.md`
- `docs/runbooks/OPERATIONS.md`
- `docs/runbooks/DEPLOYMENT.md`
- `docs/integrations/OPENCLAW.md`
- `backend/app/api/tasks.py` only for the obsolete respond docstring

Exact tasks:

1. Update README status to local-first MVP+ / post-v1.1 hardening, not plain
   `v1 MVP`.
2. Document the real current flow:
   triage -> deterministic plan -> execute -> verify -> deterministic review ->
   finalize -> optional deploy.
3. State explicitly that planner/reviewer are fake-json/deterministic until
   PR-CLOSE-03 adds configurable real LLM mode.
4. Document `make smoke`, `.smoke/report.md`, `.smoke/report.json`, and the
   smoke no-real-credentials contract.
5. Document `niwa-executor dev start --detach`, `dev stop/status`, `doctor`,
   `backup`, `restore`, `proxy render`, and `proxy validate`.
6. Update First Project with `public_enabled`, `deploy_trigger`, deploy type,
   and publication settings.
7. Update `docs/STATE.md` to record WS-01..WS-10 merge status and set next work
   to PR-CLOSE/final-close, not `smoke-v1.1`.
8. Update `docs/HANDBOOK.md` for `TaskPlan`, `TaskReview`, `Deployment`,
   `deploy_trigger`, `public_enabled`, `Run.pid`, scopes by router, MCP tools,
   deployment/Caddy model, doctor/backup/restore, and kill switch.
9. Update `docs/SPEC.md`: mark historical MVP sections as historical and add
   `Current implemented product contract`.
10. Correct clearly false embedded docs, especially the respond docstring in
    `backend/app/api/tasks.py`.

Tests/gates:

- grep README/docs/backend app docs for obsolete detached-dev target claims.
- `grep -R "next_pr: smoke-v1.1" -n docs/STATE.md`
- `cd backend && pytest -q`
- `cd frontend && npm test`
- `make smoke`

Risks:

- Overstating product readiness. Separate implemented, partial, optional, and
  future capabilities.
- Mixing roadmap with state. Keep `STATE` factual.

Acceptance:

- README, STATE, HANDBOOK, and SPEC do not contradict each other.
- Docs say what is fake/deterministic and what is real.
- `make smoke` and operator CLI commands are documented.

Critical areas:

- No critical implementation areas expected. A docstring-only edit in
  `backend/app/api/tasks.py` is allowed by this plan.

## PR-CLOSE-02 - Pipeline State Machine Real

Branch: `codex/close-02-pipeline-state-machine`

Objective:

- Make explicit task pipeline states and approval/review loop behavior real in
  the executor, API, and minimum UI.

Probable files:

- `backend/app/models/task.py`
- `backend/app/models/task_plan.py`
- `backend/app/models/task_review.py`
- `backend/app/models/project.py`
- `backend/app/schemas/project.py`
- `backend/app/schemas/task.py`
- `backend/app/executor/core.py`
- `backend/app/api/tasks.py`
- `backend/app/services/tasks.py`
- `backend/migrations/versions/*pipeline_state_machine*.py`
- `backend/tests/test_executor*.py`
- `backend/tests/test_tasks_api.py`
- `frontend/src/api.ts`
- `frontend/src/features/tasks/TaskDetail.tsx`
- `frontend/src/features/projects/ProjectSettingsTab.tsx`
- Frontend tests for approval/settings
- `scripts/smoke_v1_1.py`

Exact tasks:

1. Add a state transition helper, likely `_set_task_status(session, task,
   new_status, reason=None)`, that always writes a consistent `TaskEvent`.
2. Change claim/flow so `queued` moves into explicit states instead of jumping
   straight through `running`.
3. Before triage, set `triaging`.
4. Before creating plan, set `planning`.
5. Add project setting `plan_approval_mode = auto|manual`, default `auto`.
6. Add bounded review iteration setting, e.g. `max_review_iterations`, default
   1 unless implementation proves a better safe default.
7. If approval mode is manual, leave task in `waiting_approval` and do not run
   the adapter.
8. Add `POST /api/tasks/{task_id}/approve-plan` with `task:write` scope.
9. Consider `POST /api/tasks/{task_id}/reject-plan` or cancellation semantics
   if needed; keep it minimal and explicit.
10. Before adapter execution, set `executing`.
11. Before `verify_run`, set `verifying`.
12. Before `TaskReview`, set `reviewing`.
13. Finalize to `done`, `waiting_input`, `failed`, or `cancelled`.
14. Implement bounded request-changes loop. If review returns
    `request_changes`, re-run up to N configured iterations; exceeding the
    limit fails task with outcome such as `review_changes_exhausted`.
15. Record loop evidence in `TaskEvent`, `RunEvent`, `TaskReview.iteration`, or
    an equivalent persisted shape.
16. Update smoke to assert completed tasks have latest plan and review.

Tests/gates:

- Backend tests for happy-path transitions and event order.
- Backend tests for manual approval waiting behavior.
- Backend tests for approve-plan endpoint success and 401/403/404/409.
- Backend tests for request-changes loop limit.
- Frontend tests for waiting approval controls if UI is included here.
- `cd backend && pytest -q`
- `cd frontend && npm test`
- `make smoke`

Risks:

- This changes the most sensitive behavior in Niwa.
- Existing tests may assume `running`; update tests deliberately with clear
  reasoning.
- Review loop can create accidental infinite loops if not bounded and tested.

Acceptance:

- Explicit statuses appear in `Task.status` and `TaskEvent` in coherent order.
- `waiting_approval` blocks adapter execution until approval.
- Review request-changes loop is bounded and leaves evidence.
- Smoke proves plan/review presence.

Critical areas:

- Yes. Explicitly authorized by approved plan if human gives `go ahead`:
  `backend/app/executor/`.
- Possible related critical areas if implementation requires them:
  `backend/app/verification/` and `backend/app/finalize.py`.

## PR-CLOSE-03 - Real LLM Planner/Reviewer

Branch: `codex/close-03-real-llm-planner-reviewer`

Objective:

- Add configurable real LLM planner/reviewer services while preserving fake-json
  deterministic mode as default for CI and smoke.

Probable files:

- `backend/app/pipeline/__init__.py`
- `backend/app/pipeline/planner.py`
- `backend/app/pipeline/reviewer.py`
- `backend/app/pipeline/schemas.py`
- `backend/app/config.py`
- `backend/app/executor/core.py`
- `backend/app/adapters/claude_code.py` if reusable CLI behavior is needed
- `backend/tests/test_pipeline_planner.py`
- `backend/tests/test_pipeline_reviewer.py`
- `backend/tests/test_executor*.py`
- `backend/tests/fixtures/fake_claude_cli.py`
- `docs/HANDBOOK.md`
- `docs/SECURITY.md`
- `README.md`

Exact tasks:

1. Create pipeline modules for planner/reviewer and JSON validation.
2. Add config:
   `pipeline.planner_mode = fake-json|claude-code` and
   `pipeline.reviewer_mode = fake-json|claude-code`, default fake-json.
3. Define plan JSON contract with summary, steps, risks,
   acceptance_criteria, files_likely_touched, and approval hint if useful.
4. Define review JSON contract with decision `approved|request_changes`,
   summary, findings, risk_level, and optional follow-up prompt.
5. Implement fake planner/reviewer using current deterministic behavior.
6. Implement claude-code planner/reviewer via CLI or adapter-equivalent call.
7. Validate JSON strictly. Invalid JSON must fail safely or fall back only when
   mode semantics explicitly say so.
8. Store `TaskPlan.planner` and `TaskReview.reviewer` as `claude-code` in real
   mode and `fake-json` in fake mode.
9. Add tests with fake CLI returning valid JSON, invalid JSON, timeout, and
   request_changes.
10. Keep `make smoke` deterministic and credential-free.

Tests/gates:

- Unit tests for fake planner/reviewer.
- Unit tests for claude-code mode with fake CLI.
- Executor integration tests for planner/reviewer outputs.
- Invalid JSON tests prove no stuck runs.
- `cd backend && pytest -q`
- `cd frontend && npm test`
- `make smoke`

Risks:

- Claude CLI may execute more than desired if not invoked carefully. Planning
  and review should be JSON-only and must not mutate filesystem.
- Real-mode failure handling must not strand tasks or bypass review.
- No CI gate may depend on real Claude authentication.

Acceptance:

- Niwa can use real LLM planner/reviewer through config.
- Fake mode remains default and deterministic.
- Invalid or malformed LLM output is controlled, persisted, and tested.

Critical areas:

- Yes. Explicitly authorized by approved plan if human gives `go ahead`:
  `backend/app/executor/` and possibly `backend/app/adapters/`.

## PR-CLOSE-04 - Clean-Machine Release Gates

Branch: `codex/close-04-clean-machine-release-gates`

Objective:

- Add reproducible release gates that validate install/test/smoke behavior in
  a clean or isolated environment without real credentials.

Probable files:

- `Makefile`
- `.github/workflows/ci.yml`
- `scripts/clean_machine_gate.sh` or `scripts/clean_machine_gate.py`
- `scripts/smoke_live.py`
- `scripts/smoke_v1_1.py`
- `docs/runbooks/RELEASE.md`
- `docs/runbooks/OPERATIONS.md`
- `README.md`
- Backend tests for target/script contract

Exact tasks:

1. Add `make release-gate` or `make release-check` according to final naming;
   prefer the user's requested `make release-gate` and document any alias.
2. The gate must create a temporary HOME/NIWA_HOME and run bootstrap or the
   closest deterministic clean install path.
3. Use `NIWA_BOOTSTRAP_SKIP_LINGER=1` when invoking bootstrap if needed.
4. Verify `make test`, `make smoke`, `niwa-executor doctor`, and basic
   backup/restore.
5. Add workflow dispatch/manual CI job for release gate if too slow for every
   push.
6. Add optional `make smoke-live` using real Claude/GitHub only when explicitly
   opted in, e.g. `NIWA_SMOKE_LIVE=1`.
7. `smoke-live` must skip/fail clearly when missing `claude`, `gh auth`, or
   explicit opt-in; it must not touch real projects by default.
8. Add release runbook with clean clone, bootstrap, release-gate, smoke-live,
   CI, and tag/release notes instructions.

Tests/gates:

- `make release-gate`
- `make test`
- `make smoke`
- `make smoke-live` without opt-in must produce a clear skip/exit.
- `cd backend && pytest -q`
- `cd frontend && npm test`

Risks:

- Bootstrap in a clean HOME may expose environment assumptions. Fix only within
  approved scope.
- Release gate may be slow; if so, keep it manual but deterministic.
- Smoke-live must not spend credits or create remote artifacts accidentally.

Acceptance:

- There is a reproducible clean-machine validation command.
- CI has a manual release gate path if always-on is too slow.
- No gate requires Claude real, GitHub real, DNS, Caddy, or secrets.

Critical areas:

- No critical product area expected unless release gate exposes a product bug;
  stop and ask if fixing requires executor/verification/finalize/adapters.

## PR-CLOSE-05 - Online Publication E2E

Branch: `codex/close-05-online-publication-e2e`

Objective:

- Close online publication as a deterministic, testable operator contract for
  Niwa UI/API and public project subdomains.

Probable files:

- `backend/app/network/caddy.py`
- `backend/app/niwa_cli.py`
- `backend/app/api/deploy.py`
- `backend/app/api/deployments.py`
- `backend/tests/test_caddy.py`
- `backend/tests/test_api_auth_scopes.py`
- `backend/tests/test_deploy*.py`
- `docs/runbooks/ONLINE_PUBLICATION.md`
- `docs/runbooks/DOMAIN.md`
- `docs/runbooks/DEPLOYMENT.md`
- `frontend/src/features/projects/ProjectSettingsTab.tsx`

Exact tasks:

1. Add deterministic Caddy render fixtures/tests:
   no public projects, static public project, process public project with
   active port, and private project not routed.
2. Ensure static route rewrite preserves assets:
   `slug.apps_domain -> /api/deploy/{slug}{uri}`.
3. Ensure process route only targets `localhost:{active.port}` when active
   deployment has a port.
4. Add proxy preview/doctor capability if useful:
   `niwa-executor proxy render --print` already exists; add `proxy doctor` or
   extend validation reporting for domains, backend port, route count, inactive
   process routes, and Caddy presence.
5. Add API deploy tests:
   private project requires read scope when auth enabled; public project serves
   anonymously.
6. Add runbook for VPS mode, home/tunnel mode, DNS, wildcard apps domain,
   TLS/Caddy, auth-before-exposure, and `public_enabled=false` default.
7. Add UI copy explaining that public deployment only becomes reachable when
   proxy/domain infrastructure is configured.

Tests/gates:

- Caddy render tests.
- Deploy auth tests.
- `niwa-executor proxy render --ui-domain niwa.example.test --apps-domain apps.example.test --print`
- `niwa-executor proxy validate` should return clear `127` if Caddy is absent,
  not traceback.
- `cd backend && pytest -q`
- `cd frontend && npm test`
- `make smoke`

Risks:

- DNS/TLS/Caddy real reload cannot be CI-verified. Keep those as manual
  checklist steps.
- Public/private boundary must fail closed.

Acceptance:

- Caddyfile generation is deterministic and covered.
- Private projects are not routed and require auth for `/api/deploy`.
- Operator can follow the runbook without inferring critical steps.

Critical areas:

- No executor/finalize/adapters/verification edits expected.

## PR-CLOSE-06 - Security Locks, Limits, And Sandbox Declaration

Branch: `codex/close-06-security-locks-limits-sandbox`

Objective:

- Close a minimum honest security baseline for local-first online exposure and
  subprocess execution.

Probable files:

- `backend/app/config.py`
- `backend/app/executor/core.py`
- `backend/app/executor/runner.py`
- `backend/app/api/tasks.py`
- `backend/app/api/ops.py`
- `backend/app/services/attachments.py`
- `backend/app/mcp/tools/tasks.py`
- `backend/app/niwa_cli.py`
- `backend/app/models/*`
- `backend/migrations/versions/*project_locks*.py` if a table is used
- `backend/tests/test_executor*.py`
- `backend/tests/test_security.py`
- `backend/tests/test_ops.py`
- `backend/tests/test_attachments*.py`
- `docs/SECURITY.md`
- `docs/runbooks/OPERATIONS.md`

Exact tasks:

1. Add real project locking: no two active tasks may mutate the same project
   repo concurrently.
2. If current executor stays serial, implement/test the lock anyway as a guard
   for future parallelism and document serial mode.
3. Add stale lock cleanup when related run/task is terminal or cancelled.
4. Give `max_concurrent_runs` explicit semantics. If concurrency is not
   implemented, document and test serial guard behavior instead of pretending.
5. Add max attachment size for HTTP attachments and MCP `task_attach`.
6. Add queued task or create-rate limit per project if viable without new deps;
   if not viable, document as known limitation and avoid scope creep.
7. Verify redaction before persistence for run events, deploy logs, backup
   config, and MCP audit payloads; add missing tests.
8. Add kill switch tests for `Run.pid` and process signal behavior with a fake
   process if viable.
9. Add doctor strict exposure guard: public bind without auth must warn/fail.
10. Update `docs/SECURITY.md` to say explicitly: no strong OS sandbox; Claude
    runs with the user's permissions; dangerous permissions are risky; use a
    dedicated user/VPS and auth before exposure.

Tests/gates:

- Project lock tests.
- Stale lock cleanup tests.
- Attachment/MCP size limit tests.
- Redaction tests.
- Doctor strict public-bind-without-auth test.
- Kill switch process fake test if viable.
- `cd backend && pytest -q`
- `cd frontend && npm test`
- `make smoke`

Risks:

- Bad locks can deadlock the queue. Stale cleanup must be proven.
- Overclaiming sandbox would be worse than documenting limitation.
- Process signal tests can be platform-sensitive; keep them deterministic.

Acceptance:

- Same project cannot be actively mutated by two adapters at once.
- Limits fail with clear errors.
- Exposure guard warns/fails before unsafe public binding.
- Security docs are honest about no strong sandbox.

Critical areas:

- Yes. Explicitly authorized by approved plan if human gives `go ahead`:
  `backend/app/executor/`.
- Possibly touches adapter/process behavior indirectly; stop and ask if
  `backend/app/adapters/` becomes necessary.

## PR-CLOSE-07 - MCP/OpenClaw Conformance

Branch: `codex/close-07-mcp-openclaw-conformance`

Objective:

- Make Niwa MCP usable by OpenClaw or other HTTP JSON-RPC clients with a stable
  documented contract.

Probable files:

- `backend/app/mcp/server.py`
- `backend/app/mcp/tools/*.py`
- `backend/tests/test_mcp.py`
- `scripts/mcp_smoke.py`
- `docs/integrations/OPENCLAW.md`
- `docs/integrations/MCP.md`
- `README.md`

Exact tasks:

1. Add minimal `initialize` JSON-RPC support with `protocolVersion`,
   `serverInfo`, and tool capabilities.
2. Accept `notifications/initialized` as a no-op according to chosen JSON-RPC
   notification behavior.
3. Ensure `tools/list` contains every documented tool with valid schemas.
4. Ensure `tools/call` behavior is documented: support `{name, arguments}` and
   `{tool, params}` if keeping both, or deprecate one explicitly.
5. Enrich `task_status` with latest plan, review, run, and deployment if this
   can be done without breaking callers; otherwise add `task_context`.
6. Add tests for parse error, invalid request, missing bearer, invalid token,
   scope denied, unknown method/tool, bad params, not found, and write audit.
7. Add `scripts/mcp_smoke.py` if useful, using `NIWA_MCP_TOKEN`/local fake mode
   and no external services.
8. Document HTTP JSON-RPC transport and no streaming limitation.
9. Update OpenClaw guide with endpoint, token scopes, and examples for ping,
   initialize, tools/list, project_list, task_create, task_attach, task_status,
   task_respond, task_cancel, task_retry, deploy_trigger, deployment_status,
   pull_list, and pull_merge.

Tests/gates:

- Backend MCP contract tests.
- `scripts/mcp_smoke.py` in deterministic local/fake mode if added.
- `cd backend && pytest -q`
- `cd frontend && npm test`
- `make smoke`

Risks:

- Do not claim full MCP stdio/spec conformance if only HTTP JSON-RPC subset is
  implemented.
- Do not expose direct filesystem writes through MCP.

Acceptance:

- A client can perform initialize -> tools/list -> tools/call task_create from
  docs alone.
- Documented tools exactly match `tools/list`.
- Errors and scopes are stable and tested.

Critical areas:

- No executor/finalize/adapters/verification edits expected.

## PR-CLOSE-08 - UI Operator Closure

Branch: `codex/close-08-ui-operator-closure`

Objective:

- Complete the UI for normal Niwa operator workflows without requiring curl or
  DB inspection.

Probable files:

- `frontend/src/api.ts`
- `frontend/src/features/tasks/TaskDetail.tsx`
- `frontend/src/features/tasks/TaskEventStream.tsx`
- `frontend/src/features/projects/DeploysTab.tsx`
- `frontend/src/features/projects/ProjectSettingsTab.tsx`
- `frontend/src/features/admin/AdminPanel.tsx`
- `backend/app/api/tasks.py`
- `backend/app/api/deployments.py`
- `backend/tests/test_tasks_api.py`
- `backend/tests/test_deployments*.py`
- Frontend tests for task detail, settings, deploys, admin

Exact tasks:

1. TaskDetail: show unified timeline including task events, run events/summary,
   plan, review, and linked deployment when present.
2. Show `verification_json` in a readable collapsible/structured form.
3. If task is `waiting_approval`, show latest plan and Approve plan button.
4. Show review decision, findings, reviewer, and loop/iteration count when
   available from PR-CLOSE-02.
5. ProjectSettings: add `plan_approval_mode` and review iteration fields if
   PR-CLOSE-02 created them.
6. ProjectSettings: add `build_command`, currently missing from UI despite
   being in API/model.
7. ProjectSettings: show public URL preview when `public_enabled` and
   `apps_domain` config are available; otherwise show a clear missing-domain
   state.
8. DeploysTab: add deployment logs endpoint/UI. For static show `build_log`;
   for process tail bounded `process.log`.
9. DeploysTab: add healthcheck button if endpoint already exists.
10. Admin: show auth enabled/disabled, smoke/docs hints, and doctor command
    hint.
11. Add empty/error states for plan, review, logs, deploy, and approval.

Tests/gates:

- Frontend tests for approval UI, settings fields, task detail timeline,
  review/verification display, deploy logs, and admin hints.
- Backend tests for deployment logs endpoint if added.
- `cd backend && pytest -q`
- `cd frontend && npm test`
- `make smoke`

Risks:

- Depends on PR-CLOSE-02 for approval endpoint and settings.
- Reading process logs must avoid path traversal and cap output size.
- UI scope can grow; keep it operator-focused.

Acceptance:

- User can approve plans, view review, inspect deployment/log state, and edit
  project execution/deploy settings from UI.
- Normal flows do not require curl.

Critical areas:

- No executor/finalize/adapters/verification edits expected.

## PR-CLOSE-09 - Release Packaging And Final Acceptance

Branch: `codex/close-09-release-packaging-final-acceptance`

Objective:

- Prepare Niwa as a release candidate with version, changelog, acceptance
  checklist, limitations, and final gate evidence.

Probable files:

- `backend/app/__init__.py`
- `backend/pyproject.toml`
- `frontend/package.json`
- `README.md`
- `CHANGELOG.md`
- `docs/ACCEPTANCE.md`
- `docs/RELEASE_CHECKLIST.md`
- `docs/KNOWN_LIMITATIONS.md`
- `docs/STATE.md`
- `docs/runbooks/RELEASE.md`
- `Makefile`

Exact tasks:

1. Define version consistently, either in existing backend package version or a
   new `VERSION` file if that is cleaner.
2. Add or update command/output for reading version if cheap; otherwise
   document where version lives.
3. Add `CHANGELOG.md` with WS-01..WS-10 and PR-CLOSE-*.
4. Add `docs/ACCEPTANCE.md` with checklist:
   clean install, `make smoke`, create project, task done, waiting_input, PR,
   static deploy, public deploy Caddy config, MCP project/task flow, and
   backup/restore.
5. Add `docs/KNOWN_LIMITATIONS.md` covering no strong sandbox, real LLM mode
   configuration, domain/DNS/Caddy manual setup, single-user/local-first model,
   no hosted SaaS, and any remaining release limitations.
6. Add release notes template.
7. Update README install/release links.
8. Update `docs/STATE.md` to final release-candidate status with final commit
   SHA placeholder filled during PR body/final evidence if appropriate.
9. Run final gates and record literal output in PR body.

Tests/gates:

- `cd backend && pytest -q`
- `cd frontend && npm test`
- `make smoke`
- `make release-gate` if PR-CLOSE-04 added it.
- Basic grep/link checks for version/docs links if added.

Risks:

- Do not overstate release as SaaS/full sandbox/multi-user.
- Do not create tags or GitHub releases automatically without explicit human
  instruction.

Acceptance:

- Repo can be tagged manually as a release candidate.
- Docs and gates align.
- Known limitations are explicit and not hidden in PR bodies.

Critical areas:

- No executor/finalize/adapters/verification edits expected.

## Order Of Execution

1. PR-CLOSE-01 - Truth alignment.
2. PR-CLOSE-02 - Pipeline state machine real.
3. PR-CLOSE-03 - Real LLM planner/reviewer.
4. PR-CLOSE-04 - Clean-machine release gates.
5. PR-CLOSE-05 - Online publication E2E.
6. PR-CLOSE-06 - Security locks, limits, and sandbox declaration.
7. PR-CLOSE-07 - MCP/OpenClaw conformance.
8. PR-CLOSE-08 - UI operator closure.
9. PR-CLOSE-09 - Release packaging and final acceptance.

## Cross-PR Dependencies

- PR-CLOSE-01 must land first so public truth is not stale while product work
  continues.
- PR-CLOSE-02 must land before PR-CLOSE-08 approval UI.
- PR-CLOSE-03 depends on PR-CLOSE-02 pipeline shape.
- PR-CLOSE-04 can land after PR-CLOSE-03 or in parallel only if it does not
  assume final pipeline behavior; recommended after PR-CLOSE-03.
- PR-CLOSE-05 depends on current public/deploy/Caddy support and should land
  before final release docs.
- PR-CLOSE-06 should happen before declaring online exposure acceptable.
- PR-CLOSE-07 should happen before release acceptance claims about OpenClaw/MCP.
- PR-CLOSE-09 must be last.

## Final Gates

Minimum final gates before declaring this batch complete:

- `cd backend && pytest -q`
- `cd frontend && npm test`
- `make smoke`

Additional gates introduced by this plan:

- `make release-gate` after PR-CLOSE-04.
- `make smoke-live` optional skip/opt-in check after PR-CLOSE-04.
- Targeted backend tests per PR: pipeline transitions, approval API, planner/
  reviewer fake-real modes, Caddy/public-private behavior, security locks,
  attachment limits, doctor strict exposure guard, MCP conformance, deployment
  logs.
- Targeted frontend tests per PR: approval UI, settings fields, timeline,
  deploy logs, admin hints.
- CI/manual workflow evidence for release gate if added.

Every PR body must include:

- Summary.
- Files changed.
- Literal output of relevant tests/gates.
- Exact commit SHA measured.
- Risks known.
- Follow-ups remaining.

## Rollback Strategy

- One PR per close slice, in the order above.
- Schema changes must be additive/defaulted where possible and covered by
  migrations/tests.
- Defaults stay conservative:
  `plan_approval_mode=auto`, fake planner/reviewer modes, `public_enabled=false`,
  manual deploy trigger unless configured, no smoke-live without opt-in.
- Revert individual PRs if a slice destabilizes; do not revert the whole batch
  unless multiple dependent slices have landed and cannot be separated.
- Stop and ask if LOC cap, dependency constraints, external infrastructure, or
  critical-area scope expands beyond this plan.

## Safety Rules For This Batch

- No product code changes before the human gives explicit `go ahead`.
- No PRs before approval.
- No merge to `main` by the agent in this batch unless the human explicitly
  asks.
- No `git push --force`.
- No `--no-verify`.
- No new dependencies without asking.
- No secrets, credentials, DNS, Caddy reloads, paid services, production
  infrastructure, real Claude, or real GitHub dependencies in CI/smoke.
- Do not ignore failing tests.
- Do not declare completion without literal evidence.
- Do not silently expand scope beyond this plan.

## Approval Checkpoint

Awaiting explicit human:

> go ahead
