Supersedes/extends: none. Related: 0001-niwa-yume-separation.md

# ADR 0002 — Niwa v0.2 Architecture: Execution Layer and Dual-Mode Operation

**Status:** accepted
**Date:** 2026-04-12
**Deciders:** Arturo

## Context

Niwa v0.1 shipped as a self-contained Docker stack with a React web app, 21 MCP tools, and a 3-tier autonomous executor (Haiku/Opus/Sonnet). It works, but several architectural decisions from v0.1 need to be corrected before the system can support real multi-backend execution:

1. **False multi-model routing.** The executor accepts multiple LLM CLI providers (claude, llm, gemini) but internally funnels everything through `claude -p --model ...`. The model selection in the UI is cosmetic — the underlying adapter is always Claude Code CLI. This is misleading and blocks real Codex integration.

2. **`assigned_to_claude` as routing semantics.** The boolean column `assigned_to_claude` on the `tasks` table is used as the signal to trigger automatic execution. This conflates "a human wants this task executed" with "the backend is Claude". When Codex (or any other backend) is added, this flag becomes semantically wrong.

3. **`waiting_input` vs `revision` confusion.** `task_request_input` (the MCP tool that pauses a task to ask the human a question) sets status to `revision`, but `revision` was designed for human review of completed work. The result: `_pipeline_status()` doesn't count tasks waiting for input as active, and the UI doesn't distinguish "needs your answer" from "review this deliverable".

4. **`backend_run` doesn't exist.** There is no record of individual execution attempts. If a task fails and retries, the retry overwrites the previous attempt's state. No audit trail, no fallback chain, no way to compare runs.

5. **`--dangerously-skip-permissions` in the default path.** The executor and some setup paths use this flag without requiring explicit user approval. This is a security concern that must be gated behind capability profiles and approvals.

6. **OpenClaw coupling via SSE.** The install wizard registers OpenClaw using the SSE transport (`openclaw mcp set ... '{"type":"sse","url":"..."}'`), which is the legacy gateway. The modern standard is `streamable-http`. Additionally, `mcp set` does not validate the connection — the install assumes success without a smoke test.

7. **Terminal web with host access by default.** The ttyd terminal container runs with `pid: host`, `privileged: true`, and `network_mode: host`. This gives full host access from the browser, which is inappropriate for the default install path.

## Decision

### D1 — Niwa core standalone + Assistant mode optional

Niwa operates in two modes:

- **Core mode**: Niwa standalone. Web UI, task execution, MCP tools, observability. No external dependencies beyond Docker + Python + git.
- **Assistant mode**: Niwa + OpenClaw. OpenClaw provides the conversational layer (Telegram, chat). Niwa remains the system of record and execution engine.

**Rule:** OpenClaw is not a hard global dependency. Core mode must function fully without it. Assistant mode is opt-in at install time.

### D2 — OpenClaw boundary: conversation vs execution

- OpenClaw decides the conversational model (which LLM handles chat, tone, persona).
- Niwa decides the execution backend (which LLM/tool runs the task).
- These two decisions must not share a table or a router.

### D3 — `assigned_to_claude` ceases to be routing semantics

The columns `assigned_to_claude` and `assigned_to_yume` on the `tasks` table are deprecated as routing signals. They remain in the schema (not deleted) but are marked as legacy. New columns `requested_backend_profile_id` and `selected_backend_profile_id` replace them for routing.

A task's execution is triggered by its status transition (`pendiente` -> picked up by a worker), not by a boolean flag naming a specific backend.

### D4 — `waiting_input` is the canonical state for tasks needing human input

- `waiting_input` is the status used when a task (or its backend run) needs input from the human before it can continue.
- `revision` is reserved exclusively for final human review of completed deliverables, or eliminated from automated flows entirely.
- `task_request_input` (the MCP tool) must set status to `waiting_input`, not `revision`.
- `_pipeline_status()` must count `waiting_input` as an active/pending-intervention state.

### D5 — `backend_run` is born at execution start, not at routing

- A `routing_decision` is created when a task transitions to `pendiente` (the router evaluates which backend should handle it).
- A `backend_run` is created only when a worker actually claims and begins execution.
- Fallback creates a new run with `relation_type='fallback'`, linked to the failed run.
- Resume creates a new run with `relation_type='resume'`, linked to the prior run.
- Retry creates a new run with `relation_type='retry'`, linked to the prior run.
- This means a single task can have multiple runs with a clear, auditable chain.

### D6 — Streamable HTTP is the standard transport for Assistant mode

- OpenClaw registration must use `streamable-http`, not SSE.
- The SSE gateway container (`mcp-gateway-sse`) remains for backward compatibility with older MCP clients, but documentation and install wizards must teach `streamable-http` as the primary path.
- After `mcp set` (or equivalent registration), the install must perform a real smoke test to verify connectivity. Do not assume success because the config file was written.

### D7 — Terminal disabled by default

The web terminal (`ttyd`) with host-level access (`pid: host`, `privileged: true`, `network_mode: host`) is moved out of the default install path and into an advanced/operator mode. `install --quick` does not enable it.

## Consequences

### Positive

- Clear separation between Niwa's execution engine and OpenClaw's conversational layer.
- Every execution attempt is recorded as a `backend_run` with full audit trail.
- Fallback/resume/retry chains are first-class, linked records.
- The router becomes backend-agnostic — Claude Code and Codex (and future backends) are peers, not special cases.
- `waiting_input` and `revision` have distinct, unambiguous semantics.
- Security posture improves: terminal gated, `--dangerously-skip-permissions` gated behind approval.
- Install wizard teaches the modern MCP transport with real verification.

### Negative / cost

- Deprecating `assigned_to_claude` / `assigned_to_yume` requires updating all code paths that read these columns (executor, MCP tools, UI). This is migration work across PR-01 through PR-04.
- Existing installs that rely on SSE for OpenClaw will need to re-register with `streamable-http`. A migration note in INSTALL.md is needed.
- The terminal being off by default may surprise operators who relied on it. Documentation must explain how to enable it in advanced mode.

### Neutral

- The SSE gateway container stays running for clients that need it. No containers are removed.
- The 3-tier executor architecture (Haiku/Opus/Sonnet) from v0.1 is replaced by the backend adapter system in v0.2. The v0.1 executor continues working until PR-03/PR-04 land the new adapters.
