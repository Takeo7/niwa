# Smoke contract — Niwa v1.1

## Scope

Validate the full task lifecycle **without real credentials**:

1. Backend boots and passes `/api/health`.
2. Project created (`smoke-web`, `web-deployable`).
3. Task created (simple one-file change).
4. Executor (`--once`) runs the fake Claude CLI, produces a commit on a `niwa/task-*` branch, and moves the task to `done`.
5. Static deploy handler serves `dist/index.html` from the fixture project.
6. A split triage produces the expected subtasks and the parent reaches a terminal state.
7. A `waiting_input` cycle pauses on the first run and resumes after `POST /api/tasks/{id}/respond`.
8. Attachment upload gates correctly (allowed before execution starts, frozen after).
9. Fake `gh` CLI supports `pr create / pr list / pr merge`; finalize produces a `pr_url`.
10. Reports (`.smoke/report.md`, `.smoke/report.json`) are written on every run.

## Constraints

- `make smoke` must be **deterministic, networkless and credentialless**.
- The smoke runs in a temporary HOME (`/tmp/niwa-smoke-*`) and never touches `~/.niwa`.
- Fake Claude is `backend/tests/fixtures/fake_claude_cli.py`.
- Fake `gh` is `scripts/fake_gh.py` (appended to `PATH` during smoke).
- DB is initialized via `alembic -x db_url=... upgrade head`.
- Each check is logged to `.smoke/logs/<check>.log`.
- Exit code: `0` all pass, `1` any fail.

## Non-goals

- Real Claude Code CLI.
- Real GitHub API.
- DNS, TLS, Caddy.
- Any feature not in v1.1 (planning, review loop, MCP, multi-domain deploy).

## Reference

Documents: `00-fase-0-smoke-automatizado.md`, `00-roadmap-maestro.md`.
