# Installing Niwa

## Requirements

| Item | Min version | Notes |
|---|---|---|
| OS | macOS 12+, Linux | Windows via WSL2 may work, untested |
| Docker | 20.10+ | OrbStack, Docker Desktop, Colima, or rootful Podman |
| Python | 3.9+ | `python3 --version` |
| git | any | for cloning the repo |

## 5-minute install

```bash
git clone https://github.com/yumewagener/niwa
cd niwa
./niwa install
```

The wizard walks you through 9 steps. Defaults are sensible — for a first install, accept everything except the password. ~3-5 min total (most of it is `docker build`).

## What the wizard asks

### Step 0 — Pre-flight detection
Automatic. Verifies docker, finds the socket, detects optional integrations (OpenClaw, Claude Code, cloudflared).

### Step 1 — Naming
- **Instance name** (default `niwa`): prefixes container/image/network names. Pick something else (`atlas`, `garden`, …) if you want multiple installs on the same machine.
- **Install location** (default `~/.niwa`): where configs, DB, logs, secrets go.
- **Customize MCP server names?** (default `n`): if yes, you can rename the 4 server identifiers (tasks=`niwa`, notes=`isu`, platform=`platform`, filesystem=`filesystem`) to anything you like. The LLM sees these names when it lists tools.

### Step 2 — Database
- **Fresh** (default): creates an empty SQLite DB at `<install>/data/desk.sqlite3` with the Isu schema applied (10 tables, all enums, all indices, ready for the 44 tools).
- **Existing**: point at an existing `desk.sqlite3`. The installer does NOT migrate older schemas — if your DB doesn't have the Phase 5 columns (`notes.type`, `linked_tasks`, etc.), the Niwa MCP servers will fail. Use `fresh` unless you know what you're doing.

### Step 3 — Filesystem MCP scope
The filesystem server gives the LLM read+write access to two host directories:
- **Workspace** (default `<install>/data`): general working directory exposed as `/workspace`
- **Memory** (default `<install>/memory`): a separate location for long-term notes, exposed as `/memory`

You can change either to any path. Both will be created if they don't exist.

### Step 4 — Platform MCP restart whitelist
The platform server can restart containers via `container_restart`, but only those in a hardcoded whitelist. The wizard:
1. Lists all running containers on your machine
2. Excludes anything that looks like a Niwa stack container (suffixes `-mcp-gateway`, `-socket-proxy`, `-caddy`)
3. Lets you toggle which ones to allow

If you have no other containers, leave it empty — `container_restart` will be disabled with a clear error message at runtime.

### Step 5 — Tokens
Two bearer tokens:
- **Local trusted**: reserved for local use. Currently unused at runtime (the gateway disables auth in container mode). Will be used in P8.
- **Remote restricted**: validated by Caddy when accessing via the public reverse proxy. P8 will wire this into a Cloudflare Tunnel.

Default = auto-generate (256-bit each via `secrets.token_hex`). You can paste your own if you're migrating from another install.

### Step 6 — Isu web login
Username + password for the Isu web UI. The password is visible on screen — pick something temporary or write it down. Stored in `niwa.env`. Defaults: username `arturo`, no password default.

### Step 7 — Ports
4 host ports, all bound to `127.0.0.1`:
- Gateway streaming HTTP (default 18810)
- Gateway SSE legacy (default 18812)
- Caddy reverse proxy (default 18811)
- Isu web UI (default 8080)

The wizard detects collisions and warns you. Pick alternative ports if you have a niwa already running or anything else on those.

### Step 8 — Auto-register MCP clients
Only shown if Claude Code or OpenClaw are detected. Default `Y` for both. If yes:
- **Claude Code**: `claude mcp add --scope user --transport http <tasks_name> http://localhost:<port>/mcp`
- **OpenClaw**: `openclaw mcp set <tasks_name> '{"type":"sse","url":"http://localhost:<port>/sse"}'`

### Step 9 — Summary + confirmation
Last chance to abort. Shows everything you picked. Type `n` to abort, `Y` to install.

## What gets created

After confirmation:

```
~/.niwa/                           # default install location
├── docker-compose.yml             # generated from template
├── secrets/
│   └── mcp.env                    # tokens, credentials, config (chmod 600)
├── config/
│   ├── niwa-catalog.yaml          # MCP catalog (templated)
│   └── niwa-config.yaml
├── caddy/
│   └── Caddyfile                  # copied from repo
├── data/
│   └── desk.sqlite3               # the database
├── memory/                        # filesystem MCP /memory mount
└── logs/                          # gateway and caddy logs
```

Plus 4 Docker images:
- `<instance>-tasks-mcp:latest`
- `<instance>-notes-mcp:latest`
- `<instance>-platform-mcp:latest`
- `<instance>-isu:latest`

Plus 5 running containers:
- `<instance>-mcp-gateway` (streaming)
- `<instance>-mcp-gateway-sse` (legacy)
- `<instance>-caddy`
- `<instance>-socket-proxy`
- `<instance>-isu`

## Verifying the install

```bash
./niwa status
```

Should show: 5 containers Up, gateway healthcheck OK, Isu healthcheck OK.

You can also test the gateway directly:
```bash
curl -s -X POST http://localhost:18810/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

You should get a 200 with `serverInfo: Docker AI MCP Gateway`.

And test Isu:
```bash
curl -s http://localhost:8080/health
# {"ok": true}
```

Open `http://localhost:8080` in your browser and log in with the credentials you set.

## Using from Claude Code

After install (with Claude Code auto-register `y`), open any new Claude Code session:

```
claude mcp list
# niwa: http://localhost:18810/mcp (HTTP) - ✓ Connected
```

Then ask Claude:
> Use the niwa MCP to show me my pipeline status

Claude will call `niwa.pipeline_status` and show you the totals.

Try also:
- *"Create a task to add tests to my-project"*
- *"Save this idea: build a CLI tool for X. Add it to my notes."*
- *"What containers are running?"*
- *"Read the file /workspace/README.md"*

## Using from OpenClaw

After install (with OpenClaw auto-register `y`):

```bash
openclaw mcp list
# - <tasks_server_name>
```

Whatever conversational agent OpenClaw runs can now call the niwa tools.

## Troubleshooting

### "Docker is not installed"
The installer requires `docker` in PATH. If you have Docker Desktop, it should be there automatically. For OrbStack, install via `brew install orbstack`. For Linux, install Docker Engine.

### "Port X appears to be in use"
The wizard detects collisions. Pick a different port. To find what's using a port: `lsof -nP -iTCP:<port>` (macOS/Linux).

### "docker compose up failed"
Most common cause: you haven't logged into Docker Hub but the image pulls require auth. Try `docker login` first.

Run `docker compose -f ~/.niwa/docker-compose.yml up` (without `-d`) to see logs in the foreground.

### "Gateway healthcheck failed"
Check the logs:
```bash
./niwa logs mcp-gateway
```

If you see "Authentication disabled (running in container)" — that's expected and not an error.

### Isu UI shows blank page
Hard-refresh the browser (Cmd+Shift+R / Ctrl+Shift+R). Isu's frontend caches aggressively.

### Login redirects to wrong URL
Check `DESK_PUBLIC_BASE_URL` in `~/.niwa/secrets/mcp.env`. Default is `http://localhost:<isu_port>`. If you put it behind a reverse proxy (P8), update accordingly.

## Updating

For now: `git pull && ./niwa uninstall --keep-data && ./niwa install` (a real `./niwa upgrade` is P9 follow-up). Your DB and configs are preserved with `--keep-data`; only containers and images get rebuilt.

## Uninstalling

```bash
./niwa uninstall            # interactive — confirms before deleting
./niwa uninstall -y         # no confirmation
./niwa uninstall --keep-data    # keep DB, configs, logs; only stop containers
```

The uninstall:
1. Stops and removes the 5 containers via `docker compose down`
2. Removes the 4 Docker images
3. Unregisters from Claude Code / OpenClaw **only if this install registered them** (won't touch other installs' registrations)
4. Deletes `~/.niwa/` (unless `--keep-data`)

## Multiple installs on the same machine

Pick different `INSTANCE_NAME` and ports during install. Each install gets its own:
- Container names (`<instance>-mcp-gateway` etc.)
- Network (`<instance>-mcp`)
- Image tags
- Install directory (default `~/.<instance>`)

You can run as many parallel installs as you want; they don't interfere.

## What's NOT in this version

- **Public exposure via Cloudflare Tunnel** (P8 coming)
- **Schema migrations for existing DBs** (only fresh installs supported now)
- **GUI for the wizard** (CLI only)
- **The other 5 Isu views** (calendar, email, agents, connections, terminal — stripped from the port)
- **OAuth Google/Outlook integrations** (intentionally removed for portability)
- **Multi-user / RBAC** (single user always)
