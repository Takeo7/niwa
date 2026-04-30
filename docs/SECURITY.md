# Niwa Security Model

Last updated: 2026-04-30

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
**Mitigations:** API token scope `task:create` required; `task:write` for mutations; audit log records all MCP actions.  
**Gap:** A `task:create` token can create unlimited tasks.

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
**Mitigations:** `stop_process` sends SIGTERM then SIGKILL after 5s; port allocator checks OS-bound ports.  
**Gap:** No global max-process limit yet (Phase 8, QA-07).

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

## Security Checklist for Production Deployment

- [ ] Set password: `niwa-executor set-password`
- [ ] Generate MCP token with minimal scopes if using MCP
- [ ] Enable auth before exposing to network
- [ ] Do NOT use `autonomy_mode = "dangerous"` without understanding implications
- [ ] Keep `~/.niwa/` permissions restricted (`chmod 700 ~/.niwa`)
- [ ] Review `audit_events` table periodically
- [ ] Use Caddy with TLS for any network exposure (Phase 5)

## Reporting Vulnerabilities

Open a GitHub issue marked `[SECURITY]`. Do not share exploit details publicly before a fix is available.
