# ADR 0001 — Niwa is independent of Yume

**Status:** accepted
**Date:** 2026-04-08
**Deciders:** Arturo

## Context

Niwa grew out of a personal system (formerly "Yume Platform" / "Desk") where one agent ("Yume") and one task pipeline lived intertwined in `~/.openclaw/workspace/`. Routines, scheduling, the task executor, the watchdog, the conversational interface, the Telegram bot, the persona, and the project automation were all part of the same blob.

When that blob was ported into a portable Docker stack ("Niwa"), the README declared an intent to keep the agents out of the install ("the agents themselves stay in your other systems") but never formalized **what** belongs in Niwa and **what** belongs in the agent layer.

The lack of a clear rule has produced concrete failures. Examples observed on 2026-04-07/08:

- `idle-project-review` is configured as a `routine.json` that, every hour, **wakes an isolated Yume session** to run a deterministic bash script. The Yume session occasionally hallucinates that the script "doesn't exist or is broken" and kills it, even though the script is on disk and runnable. Telegram log on 2026-04-08 06:02 captured this verbatim.
- The same antipattern is suspected for `daily-backup`, `daily-improvement-arturo`, `desk-yume-15min-review`, `daily-task-summary`, `morning-brief`.
- The task watchdog and task executor live in the openclaw/Yume scripts directory but are functionally part of Niwa's responsibility.

The user wants a documented separation, both as a decision in the Niwa project and as a working memory for the agents that touch this code.

## Decision

**Niwa is the autonomous project manager. Yume (and any other conversational front-end) is an optional consumer that talks to Niwa over MCP. Niwa MUST function fully without Yume.**

The dividing line:

> **If an action is "every X time, the system does Y to project Z without anyone talking to it", it belongs to Niwa.**
> **If an action is "the user (or an agent representing the user) decides to do Y now", it belongs to the agent layer (Yume) and is materialized in Niwa via MCP.**

### Niwa owns

- Task lifecycle: `pendiente → en_progreso → hecha / bloqueada / dividida`
- Task executor (host-side launchd/systemd worker)
- Task watchdog (recover stuck tasks)
- Schema: `tasks`, `projects`, `notes`, `decisions`, `ideas`, `research`, `diary`
- 4 MCP servers (44 tools) for any LLM client
- Niwa web UI
- **Autonomous routines**: idle-project-review, daily-backup, daily-improvement, healthchecks — anything Niwa runs on a schedule **by itself**
- Its own scheduler: a dedicated cron container or host crontab inside the install. **Never** an LLM-agent isolated session as a cron runner.
- Internal LLM calls when reasoning is required: a routine's bash script invokes `claude -p`, `llm`, `gemini`, or the configured CLI directly. No conversational session involved.

### Yume (and other agents) own

- Conversational interface: Telegram, voice, chat web
- Translating human intent into MCP calls against Niwa (`/anota`, `/idea`, "qué tengo pendiente", voice commands)
- Pushing notifications, daily briefs, alerts to the user
- Persona, tone, multimodal interaction, memory of the relationship with the user
- One-off decisions that genuinely require conversational judgment

**Yume consumes Niwa via MCP. Yume does not replicate Niwa logic. Yume does not run Niwa routines.**

### Anti-pattern: "agent as cron runner"

A periodic task MUST NOT be implemented by waking a conversational agent session to execute a script. Reasons:

1. **Reliability**: an LLM agent makes flaky judgment calls. A cron returns an exit code. The 2026-04-08 incident is a textbook example: the agent decided the script was broken and killed it, when the script was fine.
2. **Cost**: spawning an LLM session every hour to run `bash X.sh` burns tokens for no reason.
3. **Observability**: cron failures show up as exit codes and logs. Agent failures show up as confabulated Telegram messages.
4. **Separation of concerns**: agents are interfaces and reasoning surfaces. Schedulers are infrastructure. Mixing them couples Niwa to a specific agent ecosystem and breaks portability.

If a routine genuinely needs LLM reasoning (e.g. "given this list of idle projects, generate 1-3 improvement tasks"), the routine's script invokes the LLM CLI directly with a tightly-scoped prompt. The LLM is a tool here, not a session.

## Consequences

### Positive

- Niwa stays installable on a fresh machine without dragging the openclaw/Yume ecosystem
- Routines become deterministic and observable (exit codes, container logs)
- Token spend on periodic automation drops to "actual work needed", not "conversational session overhead"
- The agent layer (Yume) becomes thinner and easier to evolve
- Multiple front-ends (Yume, a future CLI, a future Slack bot) can coexist over the same Niwa install without conflict

### Negative / cost

- Existing routines under `~/.openclaw/workspace/routines/*/routine.json` need to be migrated to Niwa-native cron jobs. Touch points to audit:
  - `idle-project-review` (highest priority — already broken)
  - `daily-backup`
  - `daily-improvement-arturo`
  - `desk-yume-15min-review`
  - `daily-task-summary`
  - `morning-brief`
- The current `task-executor.sh` and `task-watchdog.sh` in `~/.openclaw/workspace/scripts/` are conceptually Niwa but live in the Yume tree. They need to be moved into the Niwa install (`bin/task-executor.py` already exists in the repo as the canonical version — verify and consolidate).
- The fix applied on 2026-04-08 to add a heartbeat thread to `task-worker-v3.sh` is a Niwa concern that lives in Yume's tree. When migration happens, the same fix must be present in `bin/task-executor.py` (or its worker equivalent).

### Neutral

- The `routine.json` format is not inherently bad; it just needs to be wired to Niwa's scheduler (e.g. a `niwa-cron` container that reads routine definitions and runs scripts on schedule), not to a Yume agent session.

## Migration plan (high level — separate ADRs may follow)

1. **Verify**: confirm `bin/task-executor.py` in Niwa is the canonical executor and that the `~/.openclaw/workspace/scripts/task-executor.sh` is legacy.
2. **Port the heartbeat fix** from `task-worker-v3.sh` (2026-04-08) to whichever worker Niwa ships.
3. **Migrate `idle-project-review`** as a pilot: move the bash script into the Niwa install, create a Niwa cron entry, replace the LLM-reasoning step with a direct `claude -p` call from the script.
4. **Validate one week** in production.
5. **Migrate the remaining routines** one by one.
6. **Decommission `routine.json` + Yume isolated sessions** for any routine that has been migrated.
7. **Document the cron mechanism** in the Niwa README under "Autonomous routines".

## Notes

- This ADR formalizes what the README already hinted at. It does not change Niwa's external interface.
- The agent-side memory file `project_niwa_yume_separation.md` mirrors this decision in language tailored for the conversational agents that read this codebase.
- "Yume" in this document refers specifically to the openclaw conversational agent. Replace with any other agent name if Niwa is reused with a different front-end.
