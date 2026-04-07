# Installing Niwa

## Requirements

| Item | Min version | Required for | Notes |
|---|---|---|---|
| OS | macOS 12+, Linux | core | Windows via WSL2 untested |
| Docker | 20.10+ | core | OrbStack, Docker Desktop, Colima, rootful Podman |
| Python | 3.9+ | core | `python3 --version` |
| git | any | clone the repo | — |
| `claude` / `llm` / `gemini` CLI | any | **only if** you enable the executor | One of them, authenticated |
| `cloudflared` | any | **only if** you want public exposure | Plus a Cloudflare account + tunnel |
| Claude Code (`claude` CLI) | any | **only if** you want auto-register with it | Free with Anthropic account |
| OpenClaw | any | **only if** you have it and want auto-register | — |

**Niwa core works with just Docker + Python + git.** Everything else is opt-in.

## Quickest install (3 commands)

```bash
git clone https://github.com/yumewagener/niwa
cd niwa
./niwa install
```

The wizard walks you through 13 steps. Sensible defaults — for a first install you can press Enter on most prompts. ~3-5 minutes total (the slow part is `docker build`).

## What the wizard asks (13 steps)

### Step 0 — Pre-flight detection (automatic)
Verifies Docker, finds the socket (OrbStack/Docker Desktop/Colima/rootless), checks Python version, detects optional integrations (OpenClaw, Claude Code, cloudflared).

### Step 1 — Naming
- **Instance name** (default `niwa`) — prefixes container/image/network names. Use a different one if running multiple installs on the same machine.
- **Install location** (default `~/.niwa` or `~/.<instance>`)
- **Customize MCP server names?** (default `n`) — if yes, you rename the 4 default identifiers (`tasks`, `notes`, `platform`, `filesystem`) that the LLM sees in `tools/list`.

### Step 2 — Database
- **Fresh** (default) — creates an empty `niwa.sqlite3` with the full schema
- **Existing** — point at an existing DB. **No migrations run** — only use this if you know the schema is current.

### Step 3 — Filesystem MCP scope
Two host directories the LLM gets read+write access to:
- **Workspace** (default `<install>/data`) → exposed as `/workspace`
- **Memory** (default `<install>/memory`) → exposed as `/memory`

### Step 4 — Platform MCP restart whitelist
Auto-detects running containers via `docker ps` (excluding the Niwa stack itself). You toggle which ones the `container_restart` tool is allowed to touch.

If empty, `container_restart` is disabled at runtime with a clear error.

### Step 5 — Tokens
Two bearer tokens:
- `NIWA_LOCAL_TOKEN` (reserved, future use)
- `NIWA_REMOTE_TOKEN` (validated by Caddy for public access)

Default: auto-generate (256-bit each). You can paste your own.

### Step 6 — Niwa app login
Username + password for the web UI. Stored in `secrets/mcp.env`. Default username `arturo`.

### Step 7 — Ports
Four host ports, all bound to `127.0.0.1`:
- Gateway streaming HTTP (default 18810)
- Gateway SSE legacy (default 18812)
- Caddy reverse proxy (default 18811)
- Niwa app web UI (default 8080)

The wizard detects collisions and warns you.

### Step 8 — Autonomous task execution (optional)
Opt-in. If `y`:
- Pick LLM provider:
  1. **Claude** (Anthropic `claude` CLI) — needs `claude` in PATH and authenticated. Run `claude` once interactively before installing Niwa.
  2. **llm CLI** (Simon Willison's tool) — supports OpenAI, Anthropic, Gemini, etc. via plugins. Set `OPENAI_API_KEY` or `llm keys set openai` first.
  3. **Gemini** (Google `gemini` CLI) — needs `gemini auth`.
  4. **Custom** — provide your own command. The prompt is appended as the last argument.
- The wizard verifies the binary exists. Installs the executor as a launchd agent (macOS) or user systemd unit (Linux), keep-alive.
- The executor polls the DB every 30s, picks tasks with `status='pendiente'`, runs the LLM in the project's directory, captures output, marks `hecha` or `bloqueada`.

**To submit a task to the executor**: create it via the Niwa app (or via the `tasks.task_create` MCP verb) and set `status='pendiente'`. The executor picks it up. To prevent auto-execution, leave it as `inbox`.

### Step 9 — Register projects (optional)
The executor uses each project's `directory` field as the cwd for the LLM. You can register projects now (loop: name + slug + directory) or add them later via the Niwa app web UI.

If you skip this step but enable the executor, only tasks without a `project_id` (or with a project that has no directory) get a fallback cwd of `~`.

### Step 10 — Public exposure (optional)
Opt-in. If `y`:
- Public domain (e.g. `mcp.example.com`)
- Tunnel mode: provide existing tunnel ID (recommended) or skip and configure manually
- The wizard adds the hostname to `~/.cloudflared/config.yml` (with `.bak`), creates the DNS route, and reloads cloudflared

**Prereqs**: `cloudflared` installed, `cloudflared login` already done, the tunnel already created via `cloudflared tunnel create`.

### Step 11 — Auto-register MCP clients
Only shown if Claude Code or OpenClaw are detected.
- **Claude Code**: `claude mcp add --scope user --transport http <tasks_name> http://localhost:<port>/mcp`
- **OpenClaw**: `openclaw mcp set <tasks_name> '{"type":"sse","url":"http://localhost:<port>/sse"}'`

### Step 12 — Summary + confirmation
Shows everything you picked. Last chance to abort with `n`.

### Step 13 — Build + start (automatic)
- Creates `~/.niwa/{config,data,logs,secrets,caddy,bin}/`
- Generates `secrets/mcp.env` (chmod 600), `docker-compose.yml`, `niwa-catalog.yaml`
- Bootstraps fresh DB if requested
- Builds 4 Docker images (`tasks-mcp`, `notes-mcp`, `platform-mcp`, `app`)
- Pulls `mcp/filesystem` from the official catalog
- `docker compose up -d`
- Healthchecks gateway + app
- Registers cloudflared, claude, openclaw if applicable

## What gets created on disk

```
~/.niwa/                          # default install location
├── docker-compose.yml            # generated from template
├── secrets/
│   └── mcp.env                   # tokens, credentials, config (chmod 600)
├── config/
│   ├── niwa-catalog.yaml         # MCP catalog
│   └── niwa-config.yaml
├── caddy/
│   └── Caddyfile                 # reverse proxy config
├── data/
│   └── niwa.sqlite3              # the database
├── memory/                       # filesystem MCP /memory mount
├── logs/                         # gateway, caddy, executor logs
└── bin/
    └── task-executor.py          # only if executor enabled
```

Plus 4 Docker images (`<instance>-tasks-mcp`, `<instance>-notes-mcp`, `<instance>-platform-mcp`, `<instance>-app`) and 5 running containers.

If executor enabled: a launchd plist at `~/Library/LaunchAgents/com.niwa.<instance>.executor.plist` (macOS) or `~/.config/systemd/user/niwa-<instance>-executor.service` (Linux).

## Verifying the install

```bash
./niwa status
```

Should show 5 containers Up, gateway healthcheck OK, Niwa app healthcheck OK.

Manual sanity checks:

```bash
curl -s http://localhost:8080/health
# {"ok": true}

curl -s -X POST http://localhost:18810/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
# Should return JSON with serverInfo: Docker AI MCP Gateway

open http://localhost:8080
# Login with the credentials from Step 6
```

## Using from Claude Code

After install (with Claude Code auto-register `y`):

```
claude mcp list
# tasks: http://localhost:18810/mcp (HTTP) - ✓ Connected
```

In any Claude Code session:

> Use the tasks MCP to show me my pipeline status

Claude will call `tasks.pipeline_status` and reply with totals.

Try:
- *"Create a task to add tests to my-project"*
- *"Save this idea: build a CLI tool for X"*
- *"What containers are running?"*
- *"Read /workspace/README.md"*

## CLI commands

```bash
./niwa install              # interactive install (default)
./niwa status               # show status of an existing install
./niwa restart              # docker compose restart
./niwa logs [service]       # tail logs (default: mcp-gateway)
./niwa uninstall            # tear down (containers + images + install dir)
./niwa uninstall --keep-data    # keep DB, configs, and images; only stop containers
./niwa uninstall -y         # skip confirmation
```

`niwa logs` accepts: `mcp-gateway`, `mcp-gateway-sse`, `caddy`, `app`, `socket-proxy`, `executor` (host-side launchd/systemd log).

All commands accept `--dir <path>` to point at a non-default install location.

## Troubleshooting

### "Docker is not installed"
Install one: OrbStack (`brew install orbstack`), Docker Desktop, Colima, or Podman rootful.

### "Port X appears to be in use"
The wizard prompts for alternatives. To find what's using a port: `lsof -nP -iTCP:<port>` (macOS/Linux).

### "docker compose up failed"
Run without `-d` to see logs: `docker compose -f ~/.niwa/docker-compose.yml up`

### Gateway returns 502 from Caddy
Check that all 5 containers are running: `docker ps | grep <instance>-`. If `mcp-gateway` is missing, check `docker logs <instance>-mcp-gateway`.

### Niwa app shows blank page
Hard-refresh the browser (`Cmd+Shift+R` / `Ctrl+Shift+R`). The frontend caches aggressively.

### Executor not picking up tasks
Check: `./niwa logs executor`. Common issues:
- LLM CLI not authenticated (e.g. `claude` needs you to run it once interactively first)
- Task is in `inbox` status, not `pendiente` — only `pendiente` triggers the executor
- Project's `directory` field doesn't exist on the host

### Login redirects to wrong URL
Check `NIWA_APP_PUBLIC_BASE_URL` in `~/.niwa/secrets/mcp.env`. Default is `http://localhost:<app_port>`. If you put it behind a reverse proxy, update it accordingly.

## Updating

For now: `git pull && ./niwa uninstall --keep-data && ./niwa install` (reusing your previous answers — the wizard does NOT remember them yet, but the DB and configs are preserved with `--keep-data`).

A real `./niwa upgrade` is a planned follow-up.

## Multiple installs on the same machine

Pick different `INSTANCE_NAME` and ports. Each install gets its own:
- Container names (`<instance>-mcp-gateway`, etc.)
- Network (`<instance>-net`)
- Image tags (`<instance>-tasks-mcp`, etc.)
- Install dir (default `~/.<instance>`)

They don't interfere.

## What's NOT in this version

- **Schema migrations** for existing DBs (only fresh installs are supported)
- **GUI** for the wizard (CLI only)
- **Token rotation** command (edit `secrets/mcp.env` manually and `niwa restart`)
- **Backup** command (back up `~/.niwa/data/niwa.sqlite3` yourself)
- **Built-in upgrade** (manual pull + reinstall for now)
- **Multi-user / RBAC** (single user always)
- **Pinned image versions** (uses `:latest` for upstream images — bump risk)
