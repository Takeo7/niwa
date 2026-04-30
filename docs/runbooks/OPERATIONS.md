# Niwa Operations Runbook

Last updated: 2026-04-30

Day-to-day operations for a running Niwa instance.

## Service control

```bash
niwa-executor start      # load + start service
niwa-executor stop       # stop + unload
niwa-executor restart    # reload service file + restart
niwa-executor status     # current state
niwa-executor logs -f    # tail ~/.niwa/logs/executor.log
```

## Updates

```bash
niwa-executor update            # pull origin/main, pip install, alembic upgrade, restart
niwa-executor update --no-restart  # do everything but don't bounce the service
```

## Cleanup (retention)

Run periodically (daily cron is fine):

```bash
niwa-executor cleanup --dry-run        # preview
niwa-executor cleanup                  # actually delete
niwa-executor cleanup --audit-days 30  # tighter audit retention
```

Defaults: 90d audit, 30d runs, 30d completed/failed/cancelled tasks. Sessions and revoked tokens are always purged.

Suggested crontab:

```
0 3 * * * /home/$USER/.niwa/venv/bin/niwa-executor cleanup >> /home/$USER/.niwa/logs/cleanup.log 2>&1
```

## Kill switch

If a task is stuck or runaway:

1. UI: `Admin → Ops → Kill switch` (requires login).
2. API: `POST /api/ops/kill-switch` with auth.

This cancels every queued, waiting_input, and running task. The audit log records the action.

## Monitoring

- `GET /api/health` — liveness, returns version
- `GET /api/readiness` — db, claude CLI, git, gh status (requires no auth)
- `GET /api/metrics` — counts per status, active runs

Alert on:
- `active_runs > N` for >M minutes (stuck runs)
- `tasks_by_status.failed` growth
- `/api/health` 5xx

## Backup

Critical files:

- `data/niwa-v1.sqlite3` — the DB
- `~/.niwa/auth/password.hash` — admin password
- `~/.niwa/config.toml` — runtime config

A simple nightly backup:

```bash
cp data/niwa-v1.sqlite3 backups/niwa-$(date +%F).sqlite3
tar czf backups/niwa-home-$(date +%F).tgz ~/.niwa
```

## Restore

1. Stop the executor: `niwa-executor stop`
2. Replace `data/niwa-v1.sqlite3` with the backup
3. Restore `~/.niwa/auth/` and `~/.niwa/config.toml`
4. Start: `niwa-executor start`

DB schema migrations are forward-only; do not restore a backup older than the current schema without first downgrading via `alembic downgrade`.

## Audit log inspection

```bash
sqlite3 data/niwa-v1.sqlite3 \
  "SELECT created_at, actor_type, action, target_type, target_id FROM audit_events ORDER BY id DESC LIMIT 50;"
```

Or via API: `GET /api/audit/events?limit=100&actor_type=mcp`.

## Common issues

### Executor not picking up tasks

Check `niwa-executor status`. If running but idle, check:

```bash
sqlite3 data/niwa-v1.sqlite3 "SELECT id, status FROM tasks WHERE status IN ('queued','running');"
```

If a task is stuck in `running` for >timeout, run the kill switch and inspect the run logs.

### MCP tokens not authenticating

```bash
curl -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"ping"}' \
  http://localhost:8000/api/mcp
```

If `ping` returns `pong:true` but other methods fail with `-32001`, the token lacks scope. Check `GET /api/auth/tokens`.

### DB locked

SQLite writes are serialized. If you see `database is locked`, ensure only one executor process is running (`niwa-executor status`).
