# Niwa Security Model

Last updated: 2026-05-01

## Overview

Niwa executes Claude Code CLI against local git repositories. This document describes the threat model, existing mitigations, and known gaps.

**Niwa does NOT promise a perfect sandbox.** Claude Code CLI runs code with the same OS permissions as the executor process. This is by design for a single-user local tool; the security controls here reduce blast radius but do not replace OS-level isolation.

## Assets

| Asset | Description | Sensitivity |
|-------|-------------|-------------|
| Git repositories | Project codebases on disk | High |
| GitHub tokens | `gh` auth, `GITHUB_TOKEN` env | Critical |
| Anthropic API key | Claude CLI auth | Critical |
| Niwa DB (`niwa-v1.sqlite3`) | Tasks, runs, audit log, tokens | High |
| `~/.niwa/auth/` | Admin password hash, API tokens | Critical |
| Build logs / run events | May contain secrets from env | High |
| Deployed artifacts | Staged dist/ directories | Medium |
| PRs and branches | Niwa-created branches | Medium |

## Threat Model

### T1 — Malicious task description (prompt injection)
**Scenario:** User or MCP client creates a task with instructions designed to exfiltrate tokens or corrupt the repo.  
**Impact:** Token leak, repo corruption, unauthorized PR merge.  
**Mitigations:** Verification step checks artifacts and tests; `safe` mode requires human PR review; task cancellation available.  
**Gap:** No content filter on task description; Claude Code executes arbitrary instructions.

### T2 — Compromised MCP client
**Scenario:** An MCP client with a valid token creates malicious tasks.  
**Impact:** Same as T1.  
**Mitigations:** API token scope `task:create` required; `task:write` for mutations; audit log records all MCP actions; `NIWA_MAX_QUEUED_TASKS_PER_PROJECT` caps queued task buildup per project.
**Gap:** Limits are process-level application guards, not a distributed quota system.

### T3 — Token leakage in logs
**Scenario:** Build command outputs a token to stdout; it gets stored in `build_log` or `run_events`.  
**Impact:** Token visible in UI/DB.  
**Mitigations:** `security.redaction.redact()` applied before persisting long logs (build runner + run events).  
**Gap:** Redaction is pattern-based; novel token formats may not match.

### T4 — Path traversal in static deploy
**Scenario:** `healthcheck_path` or URL path contains `../` to read files outside artifact dir.  
**Impact:** Arbitrary file read on the server.  
**Mitigations:** `Path.resolve() + relative_to()` guard in `deploy.py` and `health.py`.  
**Gap:** Symlinks inside artifact dir that point outside are resolved and rejected; this is correct.

### T5 — Runaway process (deploy)
**Scenario:** Process deployment starts a long-running process that doesn't stop.  
**Impact:** Port exhaustion, resource drain.  
**Mitigations:** `stop_process` sends SIGTERM then SIGKILL after 5s; port allocator checks OS-bound ports; the ops kill switch marks active runs cancelled and sends SIGTERM to recorded run process groups when available; `executor.max_concurrent_runs` blocks new claims when the configured run limit is reached.
**Gap:** Executor mode is still designed for a local serial worker. The project lock is enforced against active `running` runs and is not a strong distributed lock for multiple independent worker fleets.

### T6 — Public endpoint exposure
**Scenario:** Niwa is deployed on a public server without auth enabled.  
**Impact:** Anyone can create tasks, read data, trigger deploys.  
**Mitigations:** Auth module (Phase 5) requires password hash file to be present; when absent, all routes are accessible (intentional for local dev).  
**Warning:** Always enable auth before exposing Niwa outside localhost.

### T7 — Auto-merge in dangerous mode
**Scenario:** `autonomy_mode = "dangerous"` on a project auto-merges PRs without review.  
**Impact:** Unreviewed code merged to main.  
**Mitigations:** Explicit per-project opt-in; UI shows loud red banner; audit log records merges.  
**Gap:** No rate limit on auto-merges.

### T8 — Shell injection in build/start commands
**Scenario:** Project `build_command` contains `; rm -rf /`.  
**Impact:** Arbitrary command execution.  
**Mitigations:** `shlex.split()` used instead of `shell=True` — commands are tokenized and executed without a shell, preventing injection.  
**Gap:** The first token is the executable; a malicious path could still be used if the user controls `build_command` (which they do, as the project owner).

### T9 — Oversized attachment upload
**Scenario:** UI or MCP clients upload very large attachments to fill disk.
**Impact:** Disk exhaustion, slow task preparation.
**Mitigations:** `NIWA_MAX_ATTACHMENT_BYTES` defaults to 10 MiB and rejects oversized uploads before creating DB rows; MCP returns a stable JSON-RPC error.
**Gap:** The limit is per attachment, not a total storage quota per project.

## Risk Matrix

| Threat | Likelihood | Impact | Mitigation Status |
|--------|-----------|--------|-------------------|
| T1 Prompt injection | Medium | High | Partial (verify step) |
| T2 MCP token abuse | Low | High | Good (scopes + audit) |
| T3 Token in logs | Medium | High | Good (redaction) |
| T4 Path traversal | Low | High | Good (resolve guard) |
| T5 Runaway process | Low | Medium | Good (SIGKILL) |
| T6 Public exposure | High if deployed | Critical | Good (auth module) |
| T7 Auto-merge | Low (opt-in) | Medium | Good (UI warning) |
| T8 Shell injection | Low (trusted user) | Critical | Good (shlex.split) |
| T9 Oversized attachment | Medium | Medium | Good (per-file limit) |

## Security Checklist for Production Deployment

- [ ] Set password: `niwa-executor set-password`
- [ ] Generate MCP token with minimal scopes if using MCP
- [ ] Enable auth before exposing to network
- [ ] Do NOT use `autonomy_mode = "dangerous"` without understanding implications
- [ ] Keep `~/.niwa/` permissions restricted (`chmod 700 ~/.niwa`);
      `make release-gate` runs `niwa-executor doctor --strict` to enforce this
      for fresh installs
- [ ] Set explicit `executor.max_concurrent_runs` for your host capacity
- [ ] Tune `NIWA_MAX_ATTACHMENT_BYTES` and `NIWA_MAX_QUEUED_TASKS_PER_PROJECT`
- [ ] Review `audit_events` table periodically
- [ ] Use Caddy with TLS for any network exposure (Phase 5)

## Reporting Vulnerabilities

Open a GitHub issue marked `[SECURITY]`. Do not share exploit details publicly before a fix is available.
