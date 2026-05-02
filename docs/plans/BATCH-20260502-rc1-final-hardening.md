# BATCH-20260502 — RC1 Final Hardening

Activation phrase: `RUN BATCH ORCHESTRATOR MODE`

Human goal: review `main` after `0.2.0-rc.1` and make only the final hardening that remains. This is not a new product batch and must stay limited to concrete post-merge risks.

## Startup Status

- Branch inspected: `main`.
- Version inspected: `0.2.0-rc.1`.
- Required files read:
  - `AGENTS.md`
  - `README.md`
  - `VERSION`
  - `CHANGELOG.md`
  - `docs/ACCEPTANCE.md`
  - `docs/STATE.md`
  - `docs/HANDBOOK.md`
  - `docs/SPEC.md`
  - `docs/SECURITY.md`
  - `docs/runbooks/RELEASE_GATES.md`
  - `docs/runbooks/ONLINE_PUBLICATION.md`
  - `Makefile`
  - `scripts/clean_machine_gate.sh`
  - `scripts/smoke_live.sh`
  - `backend/app/config.py`
  - `backend/app/executor/core.py`
  - `backend/app/pipeline/planner.py`
  - `backend/app/pipeline/reviewer.py`
  - `backend/app/niwa_cli.py`
  - `backend/app/services/attachments.py`
  - `backend/app/services/tasks.py`
  - `backend/app/mcp/server.py`
  - `.github/workflows/ci.yml`
  - `.github/workflows/release-gate.yml`

## Current Repo State

What exists:

- `make smoke` exists and runs deterministic smoke without real Claude, GitHub, DNS, TLS, Caddy, or external infrastructure.
- `make release-gate` exists through `scripts/clean_machine_gate.sh`.
- `niwa-executor doctor --strict` exists and fails on warnings.
- `make smoke-live` exists through `scripts/smoke_live.sh`, gated by `NIWA_SMOKE_LIVE=1`.
- Pipeline planner/reviewer modes exist in config: `fake-json` and `claude-code`.
- MCP is implemented as HTTP JSON-RPC, not streaming and not stdio.
- Documentation generally acknowledges no strong sandbox and manual online publication.

What is partially aligned:

- The release gate runs `niwa-executor doctor`, but not `doctor --strict`.
- `bootstrap.sh` creates `~/.niwa` indirectly through subdirectories and can leave it at default permissions such as `0o755`.
- `scripts/smoke_live.sh` is a real tool/auth check, but the name can imply a live end-to-end product smoke.
- `docs/ACCEPTANCE.md` is useful as a checklist, but it does not clearly separate automated evidence, optional live checks, manual infrastructure checks, and final release decision.

What is stale or misleading:

- `docs/SPEC.md` still contains historical PR-CLOSE planning language saying pipeline state, real planner/reviewer modes, MCP conformance, and release gates are planned rather than implemented.
- `docs/HANDBOOK.md` still contains fake-only planner/reviewer wording and pending PR-CLOSE references that are no longer true after the close batch.
- Some docs still need sharper wording that `claude-code` reviewer is not a full semantic/security audit and that DNS/TLS/Caddy reloads are operator-managed, not managed by Niwa.

What is broken or risky:

- `make release-gate` can pass while `doctor` prints `WARN insecure NIWA_HOME permissions: 0o755`.
- `claude-code` reviewer currently receives task and verification evidence, but `backend/app/pipeline/reviewer.py` does not include a git diff/status in the review prompt.
- `make smoke-live` can be mistaken for an E2E live deployment/GitHub/Claude smoke, but it currently only checks tool availability and GitHub auth.

## PR Strategy

Recommendation: use exactly 3 small ordered PRs.

Reasoning:

- Each risk is separable and testable.
- The first PR hardens the release gate before later PRs rely on it as final evidence.
- The second PR touches reviewer behavior and should stay isolated.
- The third PR closes acceptance/live-smoke truth alignment and stale documentation without mixing it with behavior changes.
- This avoids a single integration PR and keeps each review surface below the project cap.

No PR should merge itself. Push and PR creation are allowed after implementation approval; merge requires explicit human instruction.

## Execution Order

1. PR-RC1-HARDEN-01 — Strict release gate and NIWA_HOME permissions.
2. PR-RC1-HARDEN-02 — Reviewer diff awareness.
3. PR-RC1-HARDEN-03 — Acceptance/live-smoke clarity.

## PR-RC1-HARDEN-01 — Strict Release Gate And NIWA_HOME Permissions

Branch: `codex/rc1-harden-01-release-gate-permissions`

Objective:

Make the release gate reject insecure `NIWA_HOME` permissions instead of passing with a warning.

Probable files:

- `bootstrap.sh`
- `scripts/clean_machine_gate.sh`
- `backend/tests/...` existing CLI/doctor test area
- `docs/runbooks/RELEASE_GATES.md`
- `docs/SECURITY.md`

Exact tasks:

1. Inspect the existing bootstrap path for `~/.niwa` creation.
2. Ensure bootstrap-created `NIWA_HOME` is `0700`.
3. Prefer a small, conservative permission fix:
   - create `NIWA_HOME` explicitly before child directories;
   - `chmod 700 "$NIWA_HOME"`;
   - avoid broad recursive chmod unless a test or existing code shows it is needed.
4. Consider `umask 077` or explicit chmod inside `scripts/clean_machine_gate.sh` only if bootstrap alone does not guarantee strict doctor success.
5. Change `scripts/clean_machine_gate.sh` to run `niwa-executor doctor --strict`.
6. Add or update tests for `doctor --strict` on secure and insecure `NIWA_HOME`, following the existing backend test style.
7. Update release/security docs so `release-gate` says it runs strict doctor and requires secure `NIWA_HOME`.

Tests/gates:

- `cd backend && pytest -q`
- `cd frontend && npm test -- --run`
- `make smoke`
- `make release-gate`

Risks:

- Bootstrap may run on existing installs where `~/.niwa` already exists with loose permissions. The change should fix the directory mode when possible, but not destructively rewrite user files.
- Shell tests can become platform-sensitive if they assert too much about inherited umask. Keep assertions focused on `NIWA_HOME` mode and doctor behavior.

Acceptance criteria:

- `make release-gate` passes without an insecure `NIWA_HOME` warning.
- `niwa-executor doctor --strict` is executed inside release gate.
- Any remaining warnings are intentional, documented, and still make strict mode fail unless explicitly justified.

Critical areas:

- None of the AGENTS critical areas are expected.

## PR-RC1-HARDEN-02 — Reviewer Diff Awareness

Branch: `codex/rc1-harden-02-reviewer-diff-awareness`

Objective:

Make `pipeline.reviewer_mode=claude-code` review evidence plus actual repo changes, or a safe bounded representation of them. Keep `fake-json` deterministic.

Probable files:

- `backend/app/pipeline/reviewer.py`
- backend tests for pipeline planner/reviewer behavior
- `README.md`
- `docs/HANDBOOK.md`
- `docs/SPEC.md`
- possibly `CHANGELOG.md`

Exact tasks:

1. Add a helper in `backend/app/pipeline/reviewer.py` to collect review context from `run.artifact_root`.
2. Use `subprocess.run` without shell.
3. Use a short timeout.
4. Include bounded output such as:
   - `git status --short`;
   - `git diff --stat`;
   - `git diff --patch --no-color --no-ext-diff`, truncated to a reasonable character limit.
5. Fail safely if `artifact_root` is missing, not a git repo, git is unavailable, or the diff command times out.
6. Include the bounded diff/status context in `_review_prompt` for `claude-code`.
7. Do not change `fake-json` smoke behavior.
8. Add tests:
   - prompt/context includes diff when a git repo has changes;
   - reviewer still works when no repo exists or git diff fails;
   - invalid JSON fallback behavior remains safe.
9. Update docs precisely:
   - `fake-json` reviews deterministic verification evidence;
   - `claude-code` receives verification evidence plus bounded git status/diff context;
   - this is not a complete semantic/security audit.

Tests/gates:

- `cd backend && pytest -q`
- `cd frontend && npm test -- --run`
- `make smoke`

Risks:

- Diff prompts can become too large. The helper must truncate deterministically and say when truncation occurred.
- Untracked files may matter. Including `git status --short` makes untracked files visible even if their content is not included.
- This PR should avoid touching `backend/app/executor/core.py`; `run.artifact_root` is already available to the reviewer.

Acceptance criteria:

- `claude-code` reviewer prompt has diff/status awareness.
- `fake-json` behavior stays deterministic and smoke-compatible.
- Docs no longer overstate reviewer capability.

Critical areas:

- User-critical: `backend/app/pipeline/reviewer.py`.
- AGENTS critical areas are not expected. If implementation requires `backend/app/executor/`, stop and ask before expanding scope.

## PR-RC1-HARDEN-03 — Acceptance And Live-Smoke Clarity

Branch: `codex/rc1-harden-03-acceptance-live-smoke`

Objective:

Make final acceptance evidence clear and prevent `smoke-live` or manual acceptance docs from implying unexecuted guarantees.

Probable files:

- `scripts/smoke_live.sh`
- `scripts/acceptance_summary.py` if kept small and useful
- `docs/ACCEPTANCE.md`
- `docs/runbooks/RELEASE_GATES.md`
- `docs/runbooks/ONLINE_PUBLICATION.md`
- `README.md`
- `CHANGELOG.md`
- `docs/STATE.md`
- `docs/HANDBOOK.md`
- `docs/SPEC.md`
- possibly `Makefile` only if adding a small explicit target is clearer

Exact tasks:

1. Keep `make smoke-live` unless a rename is clearly worth the churn.
2. Change `scripts/smoke_live.sh` output/docs to call it an optional "live tools check".
3. Ensure `make smoke-live` skips cleanly without `NIWA_SMOKE_LIVE=1`.
4. Do not make mandatory tests depend on real Claude, GitHub, Caddy, DNS, TLS, or a domain.
5. Add `scripts/acceptance_summary.py` only if it stays small and stdlib-only:
   - read `.smoke/report.json` when present;
   - print automated gates known to exist;
   - print optional live gates and manual infrastructure checks;
   - never claim a gate ran unless evidence exists.
6. Restructure `docs/ACCEPTANCE.md` into:
   - automated gates;
   - optional live gates;
   - manual infrastructure checks;
   - release decision record.
7. Fix stale truth claims in docs found during startup:
   - `docs/SPEC.md` PR-CLOSE planned language;
   - `docs/HANDBOOK.md` fake-only planner/reviewer language;
   - `docs/STATE.md` next-step wording if it still points at already merged close PRs.
8. Ensure docs explicitly state:
   - DNS/TLS/Caddy reloads are not tested in CI;
   - Claude/GitHub real integrations are optional/live checks;
   - MCP is HTTP JSON-RPC, not streaming or stdio;
   - Niwa is not a strong sandbox;
   - reviewer diff awareness is bounded and not a full semantic/security audit.

Tests/gates:

- `python3 -m py_compile scripts/acceptance_summary.py` if the script is added.
- `make smoke-live` without `NIWA_SMOKE_LIVE=1` must skip cleanly.
- `cd backend && pytest -q`
- `cd frontend && npm test -- --run`
- `make smoke`
- `make release-gate`

Risks:

- Docs-only truth alignment can creep into broad rewriting. Keep edits targeted to misleading or stale claims.
- Adding an acceptance summary script should not become another release framework. Keep it informational and evidence-based.

Acceptance criteria:

- `smoke-live` is clearly described as a live tools check unless explicitly extended later.
- Acceptance docs distinguish automated evidence from optional live/manual checks.
- No docs claim managed DNS/TLS, strong sandboxing, MCP streaming/stdio, or full semantic/security review.

Critical areas:

- None expected.

## Final Batch Gates

Before final delivery after all PRs:

- `cd backend && pytest -q`
- `cd frontend && npm test -- --run`
- `make smoke`
- `make release-gate`
- `make smoke-live` without `NIWA_SMOKE_LIVE=1`, expected to skip cleanly
- `python3 -m py_compile scripts/acceptance_summary.py` if that script is added

Each PR body must include:

- summary;
- files changed;
- tests executed;
- literal output of tests/gates;
- commit SHA measured;
- known risks;
- follow-ups if any remain.

## Rollback Strategy

- PR 1 rollback: revert bootstrap/release-gate permission changes and docs updates. No data migration expected.
- PR 2 rollback: revert reviewer diff-context helper and docs. `fake-json` remains the default, so operational fallback is straightforward.
- PR 3 rollback: revert docs/live-smoke wording and optional summary script. No product state impact expected.

## Status Log

- 2026-05-02: Batch plan created after reading required files. Waiting for explicit human `go ahead` before any product-code changes.
- 2026-05-02: PR-RC1-HARDEN-01 implementation started on `codex/rc1-harden-01-release-gate-permissions`.
- 2026-05-02: PR-RC1-HARDEN-01 updated bootstrap to enforce `0700` on `NIWA_HOME`, switched release gate to `doctor --strict`, and added bootstrap/docs coverage.
- 2026-05-02: PR-RC1-HARDEN-01 opened as https://github.com/Takeo7/niwa/pull/178 after backend/frontend/smoke/release-gate passed on `a5d29625031da9608fb69290c83a9e9b11229cb1`.
- 2026-05-02: PR-RC1-HARDEN-02 implementation started on `codex/rc1-harden-02-reviewer-diff-awareness`.
- 2026-05-02: PR-RC1-HARDEN-02 added bounded git status/diff context to `claude-code` reviewer prompts, fallback tests, and reviewer capability docs.
