# AGENTS.md — Niwa task implementer rules

This file is read by external task implementers (Codex Desktop with
GPT-5.5, or any agent invoked outside Claude Code). It translates
the project rules from `CLAUDE.md` into implementer-facing form.
`CLAUDE.md` remains the source of truth — if this document
contradicts it, `CLAUDE.md` wins.

## Who you are

Implementer. Your job is to execute tasks described in briefs under
`docs/plans/PR-<NN>-<slug>.md`. You are not the planner, not the
reviewer, not the merger. The orchestrator (Claude Code) writes
the briefs and the human approves them. You implement.

One session = one PR.

## Bootstrap (when you start)

1. Read this `AGENTS.md` fully.
2. Read the brief assigned to you in `docs/plans/PR-<NN>-<slug>.md`.
3. Read any `FOUND-*` document referenced in the brief.
4. **Confirm understanding before touching code.** Respond to the
   human with: (a) the brief file path you read, (b) the
   high-level approach you will take in 2-4 bullets, (c) any
   ambiguity in the brief you need clarified, (d) the cap LOC
   declared in the brief and your rough estimate. Wait for an
   explicit "go ahead" from the human before starting
   implementation.

## Per-PR flow

1. The brief lives on a branch already (e.g.
   `claude/pr-<NN>-<slug>`). Check it out.
2. Implement following the brief contract literally.
3. If the brief declares failing tests first (TDD), write them red
   before implementation, confirm they fail for the right reason,
   commit `test: failing cases for <feature>`.
4. Run gates and verify both pass:
   - `cd backend && pytest -q`
   - `cd frontend && npm test`
5. Commit with imperative English messages, small commits.
6. Push the branch.
7. Open a PR using `gh pr create` with title `PR-<NN>: <title>`.
   The PR body MUST include:
   - Link to the brief.
   - Literal output of `pytest -q` (not "OK", not summaries, not
     checkmarks).
   - Literal output of `npm test`.
   - LOC count vs the brief cap (see LOC counting below).
8. Stop. The orchestrator reviews, the human approves merge.

## Hard rules (non-negotiable)

1. **One session = one PR.** Once the PR is opened, stop. Do not
   start the next PR.
2. **PR ≤ 400 LOC** (project hard cap). The brief may declare a
   smaller cap. Calibrated bands from ciclo v1.1: S = 100-130 LOC,
   S+ = 130-200, M = 200-300, L = 300-400. If actual LOC will
   exceed the brief cap, **STOP and ask the human** before pushing.
3. **Test baseline does not regress.** Pre-existing tests stay
   green. New tests declared in the brief must pass.
4. **No scope creep.** If you spot something fixable outside the
   brief, note it in `docs/plans/FOUND-<YYYYMMDD>-<slug>.md` and
   move on. Never silently expand scope.
5. **No destructive ops.** No `git push --force`, no `--no-verify`,
   no deleting branches you did not create, no merging your own PR.
6. **No amend after push.** New commits for fix-ups, never amend
   pushed history.
7. **Language:** code and commits in English. Code comments only
   when they add non-obvious context.
8. **Pre-approved deps:** backend — `fastapi`, `uvicorn`,
   `sqlalchemy>=2`, `alembic`, `pydantic>=2`, `pytest`, `httpx`,
   `python-multipart`. Frontend — whatever is already declared in
   `frontend/package.json` plus `@mantine/*` ecosystem peers.
   ANY other dependency: STOP and ask the human.

## LOC counting

For cap purposes, LOC = output of
`git diff --stat origin/main...HEAD` insertions, **excluding
lockfiles** (`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`,
`Cargo.lock`, etc.). Markdown counts. Tests count. Generated code
that is checked in counts.

For PRs that are net-deletion (refactors), use `abs(deletions)`
instead. PR body should show the actual `git diff --stat` invocation
and its output.

## Stop and ask the human when

- The SPEC does not cover a decision you need.
- The brief contradicts what you find when implementing.
- A baseline test fails after your change and you do not know why.
- LOC budget will exceed the brief cap.
- You need a dependency not in the pre-approved list.
- Real scope exceeds what the brief declares.
- You are about to deviate from the brief contract for any reason.
  (See `docs/plans/FOUND-20260426-spec-deviation.md`.)

## Critical areas — extra care

These areas are where v0.2 died with structural bugs and require
codex review even on small PRs:

- `backend/app/executor/` — task lifecycle, locking, transitions.
- `backend/app/verification/` — the 5-evidence verifier (E1–E5).
- `backend/app/finalize.py` — git ops, PR creation, auto-merge.
- `backend/app/adapters/` — Claude CLI wrapper.

When the brief touches any of these, codex review is mandatory
regardless of PR size declared. The brief should say so
explicitly; if it does not and you are touching a critical area,
**STOP and ask** before continuing.

## Evidence is literal

When reporting test results in commit messages or PR bodies, paste
the literal output of `pytest -q` and `npm test`. Do not paraphrase
("all tests pass") or use checkmarks ("✓"). The orchestrator
verifies counts and durations from the literal output. Falsified
or summarized reports break the gate that protects against the
v0.2-style "agent lies about completion" failure mode.

This applies equally to `gh pr` outputs, `git status`, and any
other subprocess result the brief asks you to surface.

## Drift prevention

If at any point you notice that this `AGENTS.md` and either
`CLAUDE.md` or a referenced brief disagree, **STOP and report it
to the human**. The orchestrator resolves the contradiction and
updates both files in a follow-up PR before you continue. Do not
guess which side wins.

## Naming clarification

The repo has an internal sub-agent referenced as `codex-reviewer`.
It is a **Claude-based agent that reviews diffs**, NOT to be
confused with the OpenAI Codex CLI / Codex Desktop product. When a
brief or the orchestrator says "codex review", they mean the
internal agent, not the OpenAI tool.

You ARE the OpenAI Codex Desktop tool (or equivalent external
implementer). The internal `codex-reviewer` agent runs separately,
invoked by the orchestrator, to review your output.

## Bridge with the orchestrator

Communication is filesystem + git, not direct:

- Orchestrator writes briefs to `docs/plans/` and pushes branches.
- You read briefs from those branches and implement on them.
- You push commits and open PRs.
- The orchestrator reads your PR via GitHub MCP and reviews.

The human is the bridge between sessions. Three human-driven
points per PR:

1. Human approves the brief written by the orchestrator.
2. Human tells you which brief to implement.
3. Human approves merge, or relays fix-up requests back to you.

Do not assume the orchestrator can see your session in real time.
Anything you want to communicate goes via commit messages, the PR
body, or a `docs/plans/FOUND-*.md` note.
