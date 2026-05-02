# OpenClaw ↔ Niwa Integration Guide

This guide explains how to connect OpenClaw (or any other MCP client) to a Niwa instance.

## Overview

Niwa exposes an MCP server at `POST /api/mcp`. All communication is JSON-RPC 2.0 over HTTP with Bearer token authentication.

The MCP server is a thin layer over Niwa's internal services — it does not expose filesystem access or shell execution directly.

Current truth: this is an HTTP JSON-RPC tool surface, not stdio MCP. It supports
`ping`, `tools/list`, `tools/call`, and the tools listed below. Minimal
`initialize`/client conformance hardening is planned for PR-CLOSE-07.

## Requirements

- Niwa v1.1+ running locally or on a VPS
- An API token with appropriate scopes (see below)
- MCP client that supports HTTP transport (not stdio)

## Authentication

All tools (except `ping`) require a Bearer token.

### Creating a Token

1. Via the Niwa UI: Settings → API Tokens → Create
2. Via the API:
   ```bash
   curl -X POST http://localhost:8000/api/auth/tokens \
     -H "Content-Type: application/json" \
     -d '{"name": "openclaw", "scopes": ["read", "task:create", "task:write"]}'
   ```
   The `token` field in the response is shown **only once**. Store it securely.

3. Via env var (dev/bootstrap): set `NIWA_MCP_TOKEN=<secret>` in the server environment.

### Scopes

| Scope | Grants |
|-------|--------|
| `read` | project_list, project_get, task_list, task_status |
| `task:create` | task_create, task_attach |
| `task:write` | task_respond, task_cancel, task_retry |
| `merge` | pull_merge |
| `deploy` | deploy_trigger |
| `admin` | All scopes |

Recommended scopes for OpenClaw task management: `read task:create task:write`.
Add `deploy` only for clients that should be allowed to publish a project.

## MCP Configuration

Add to your MCP client config (e.g. Claude Desktop `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "niwa": {
      "transport": "http",
      "url": "http://localhost:8000/api/mcp",
      "headers": {
        "Authorization": "Bearer <your-token>"
      }
    }
  }
}
```

For a remote Niwa instance, replace `localhost:8000` with your domain (e.g. `https://niwa.example.com`).

## Available Tools

### Project Tools

**`ping`** — Check connectivity. No auth required.
```json
{"method": "ping", "params": {}}
```

**`project_list`** — List all projects. Scope: `read`.
```json
{"method": "project_list", "params": {}}
```

**`project_get`** — Get project details. Scope: `read`.
```json
{"method": "project_get", "params": {"slug": "my-project"}}
```

### Task Tools

**`task_create`** — Create a task. Scope: `task:create`.
```json
{
  "method": "task_create",
  "params": {
    "project_slug": "my-project",
    "title": "Add rate limiting to /api/users",
    "description": "Use slowapi library. Tests in tests/test_rate_limit.py."
  }
}
```

**`task_status`** — Poll task progress. Scope: `read`.
```json
{"method": "task_status", "params": {"task_id": 42}}
```

Returns: `{id, title, status, branch_name, pr_url, pending_question, ...}`

**`task_attach`** — Attach text or base64 content to a queued task. Scope:
`task:create`.
```json
{
  "method": "task_attach",
  "params": {
    "task_id": 42,
    "filename": "spec.md",
    "content_type": "text/markdown",
    "encoding": "text",
    "content": "# Requirements\n..."
  }
}
```

For binary content, set `"encoding": "base64"`. Niwa stores attachments
through its attachment service; MCP clients never receive direct filesystem
write access.

**`task_respond`** — Unblock a waiting_input task. Scope: `task:write`.
```json
{
  "method": "task_respond",
  "params": {
    "task_id": 42,
    "response": "Use the existing UserService class from app/services/users.py"
  }
}
```

**`task_cancel`** — Cancel a queued/waiting task. Scope: `task:write`.
```json
{"method": "task_cancel", "params": {"task_id": 42}}
```

**`task_retry`** — Re-queue a failed/cancelled task. Scope: `task:write`.
```json
{"method": "task_retry", "params": {"task_id": 42}}
```

### Deployment Tools

**`deploy_trigger`** — Trigger a deployment for a project. Scope: `deploy`.
```json
{"method": "deploy_trigger", "params": {"project_slug": "my-project"}}
```

**`deployment_status`** — Fetch a deployment by id, or the latest deployment
for a project. Scope: `read`.
```json
{"method": "deployment_status", "params": {"deployment_id": 12}}
```
```json
{"method": "deployment_status", "params": {"project_slug": "my-project"}}
```

## Recommended Workflow

```
1. project_get → verify project exists and is healthy
2. task_create → returns task_id
3. loop task_status every 10s:
   - status == "waiting_input" → task_respond with decision
   - status == "done" → read pr_url and review
   - status == "failed" → inspect, optionally task_retry
4. (human reviews PR)
```

## Security Limits

- Niwa executes Claude Code with the OS permissions of the executor process
- MCP tokens do NOT grant filesystem access directly
- The `task:create` scope allows creating tasks but the executor decides if/when to run them
- Do NOT use `admin` scope for automated clients; use minimal scopes
- Audit all MCP activity via `GET /api/audit/events` (admin only)

## Troubleshooting

**401 Unauthorized**: Token is invalid, expired, or revoked. Create a new token.

**403 Forbidden**: Token lacks required scope. Check token scopes via `GET /api/auth/tokens`.

**404 Not Found**: Project slug or task ID does not exist.

**409 Conflict**: `task_respond` called on a task not in `waiting_input` state; `task_retry` on a non-failed task.

**`-32001` JSON-RPC error**: Auth failure (same as 401 in HTTP terms).

**`-32601` JSON-RPC error**: Unknown method.

**`-32602` JSON-RPC error**: Invalid or missing parameters.

**`-32003` JSON-RPC error**: Scope/authz failure.

**`-32004` JSON-RPC error**: Project, task, or deployment not found.

**`-32009` JSON-RPC error**: State conflict, for example responding to a task
that is not waiting for input.

**`-32000` JSON-RPC error**: Internal error. Check Niwa server logs.
