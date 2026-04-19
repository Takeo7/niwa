# Installing Niwa

## Requirements

| Item | Min version | Required for | Notes |
|---|---|---|---|
| OS | macOS 12+, Linux | core | Windows via WSL2 untested |
| Docker | 20.10+ | core | OrbStack, Docker Desktop, Colima, rootful Podman |
| RAM | 4 GB | core (VPS) | 8 GB recommended for Mac mini running local models |
| Python | 3.9+ | core | `python3 --version` |
| git | any | clone the repo | — |
| `claude` / `llm` / `gemini` CLI | any | **only if** you enable the executor | One of them, authenticated |
| `cloudflared` | any | **only if** you want public exposure | Plus a Cloudflare account + tunnel |
| Claude Code (`claude` CLI) | any | **only if** you want auto-register with it | Free with Anthropic account |
| OpenClaw | any | **required for** `--mode assistant` | Optional for `--mode core` |

**Niwa core works with just Docker + Python + git.** Everything else is opt-in.

**Ports opened locally by default:** `18810` (gateway streaming), `18811` (Caddy), `18812` (gateway SSE legacy), `8080` (web app). All bound to `127.0.0.1` unless you pass `--public-url`. Collisions are auto-resolved by incrementing the port.

**Hardware envelope (SPEC v0.2 §6 DoD):**
- **VPS 4–8 GB** — supports Niwa as a control plane with remote CLI/API backends. **Not** for local model inference (no room for Haiku/Sonnet/Codex running in-process).
- **Mac mini (M-series)** — supports the same control plane *plus* the local executor path if you have the `claude`/`codex` CLIs configured.

## Quick install — PR-11 (recommended)

Two non-interactive modes. Both bind everything to `127.0.0.1` unless `--public-url` is passed.

### Core mode — Niwa standalone

```bash
git clone https://github.com/Takeo7/niwa
cd niwa
./niwa install --quick --mode core --yes
```

Installs Niwa on its own: web UI, task routing v0.2, Claude + Codex backend adapters. No OpenClaw. Terminal service is disabled by default (the advanced overlay is available, see below).

Expected time: **under 10 minutes** on a warm machine (Docker already installed, images cached). The slow part is `docker build` of the `niwa-app` image.

### Assistant mode — Niwa + OpenClaw

```bash
./niwa install --quick --mode assistant --yes
```

Same as core, plus:
 1. OpenClaw CLI detection. **Hard prereq** — if `openclaw` is not on `PATH`, the installer exits with code `2` and instructions. Install it first (`npm i -g openclaw@latest`, or see <https://openclaw.ai/install>).
 2. Registers Niwa's MCP endpoint with OpenClaw using `streamable-http` (the modern MCP transport — SSE is legacy).
 3. Filters the MCP surface to the 11 v02-assistant tools (`config/mcp-contract/v02-assistant.json`).
 4. Runs `bin/niwa-mcp-smoke` after the stack is up to verify the assistant-mode contract end-to-end.

If the LLM is not yet configured, the MCP smoke reports `roundtrip_assistant_turn_skip` and the install still completes successfully — you can set up the conversational brain later in the web UI (System → Agentes) without reinstalling.

### CLI flags

```
./niwa install --quick --mode {core,assistant} [options]

  -y, --yes                 Skip the confirmation prompt (for scripting/CI).
  --workspace PATH          Directory exposed to the filesystem MCP as
                            /workspace. Default: <install>/data.
  --public-url URL          Bind ports to 0.0.0.0 and record this domain
                            (e.g. https://niwa.example.com). No TLS is
                            configured by the installer; put Caddy or a
                            Cloudflare Tunnel in front.
  --admin-user USER         Niwa web UI username (default: niwa).
  --admin-password PW       Niwa web UI password (default: auto-generated
                            and printed at the end of the install).
  --dir PATH                Install location (default: ~/.niwa).
```

### Exit codes

| Code | Meaning |
|---|---|
| `0`  | Install and post-install smoke both passed. |
| `1`  | Install completed but the post-install smoke failed. Stack stays up for debugging. |
| `2`  | Blocked by missing prereqs (Docker missing, or `--mode assistant` without OpenClaw), **or mode mismatch with an existing install** (re-run with the matching `--mode`, or pass `--force`). |
| `130`| Aborted at the confirmation prompt (Ctrl-C or `n`). |

### Idempotence

The three reinstall scenarios supported:

| Scenario | Behavior |
|---|---|
| **Same mode** (core→core, assistant→assistant) | Update-in-place. Schema is idempotent (`CREATE TABLE IF NOT EXISTS`, `INSERT OR IGNORE`), `docker compose up -d` replaces containers without losing the data volume. **Tokens and the admin password in `secrets/mcp.env` are rotated** (a `warn()` is printed before the install). Pass `--admin-user` / `--admin-password` to pin them across runs. |
| **Different mode** (core↔assistant) | **Aborts with exit code `2`.** The installer refuses to silently switch modes. Options printed: (1) re-run with the matching `--mode`, (2) add `--force` to overwrite the existing config (DB data preserved; tokens rotate; previously registered MCP clients will need to re-accept the new token), (3) `./niwa uninstall --dir <path>` first. |
| **Fresh install** (no `secrets/mcp.env`) | Runs normally. |

The current mode is detected from `NIWA_MCP_CONTRACT` inside `secrets/mcp.env`. Value `v02-assistant` ⇒ assistant; anything else ⇒ core.

### Overriding the pinned `docker/mcp-gateway` image

The installer pins `docker/mcp-gateway` to the fixed semver tag `v0.40.4` (PR-11 Dec 1). To use a different tag:

```bash
NIWA_MCP_GATEWAY_IMAGE=docker/mcp-gateway:v0.41.0 ./niwa install --quick --mode core --yes
```

The value is written to `secrets/mcp.env` and the generated compose file; `niwa restart` keeps it.

## Interactive install (13 steps)

The classic interactive wizard is still there — drop `--quick`:

```bash
./niwa install
```

It walks you through 13 steps. Sensible defaults — for a first install you can press Enter on most prompts. ~3-5 minutes total (the slow part is `docker build`).

## What the wizard asks (13 steps)

### Step 0 — Pre-flight detection (automatic)
Verifies Docker, finds the socket (OrbStack/Docker Desktop/Colima/rootless), checks Python version, detects optional integrations (OpenClaw, Claude Code, cloudflared).

### Step 1 — Naming
- **Install location** (default `~/.niwa`)
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
- **OpenClaw**: `openclaw mcp set <tasks_name> '{"type":"streamable-http","url":"http://localhost:<port>/mcp"}'`

> **v0.2 — streamable-http is the standard MCP transport.** OpenClaw registration uses `streamable-http`, not SSE. The SSE gateway remains at port 18812 for legacy MCP clients that still rely on it, but no new integration should target it. For the `install --quick --mode assistant` path this is enforced — the only endpoint registered with OpenClaw is the streamable-http one.
>
> **`mcp set` does not validate the connection.** The installer runs `bin/niwa-mcp-smoke` after registration to verify the endpoint actually responds and the contract matches. If the smoke fails, the installer warns you and leaves the stack up for debugging.

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

Plus 4 Docker images (`niwa-tasks-mcp`, `niwa-notes-mcp`, `niwa-platform-mcp`, `niwa-app`) and 5 running containers.

If executor enabled: a launchd plist at `~/Library/LaunchAgents/com.niwa.executor.plist` (macOS) or `~/.config/systemd/user/niwa-executor.service` (Linux).

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
./niwa install --quick --mode core --yes     # quick non-interactive install
./niwa install --quick --mode assistant      # same, plus OpenClaw registration
./niwa install                               # interactive 14-step wizard
./niwa install --quick --mode <m> --rotate-secrets   # forzar rotación de tokens + admin pw
./niwa status                                # status del install
./niwa restart                               # docker compose restart
./niwa logs [service]                        # tail logs
./niwa update                                # pull → backup → rebuild → restart → health + auto-revert
./niwa restore --from=<path>                 # restaurar DB + rollback de código
./niwa restore --from=<path> --db-only       # solo DB, sin tocar código
./niwa backup                                # snapshot manual de SQLite
./niwa uninstall                             # tear down (containers + images + install dir)
./niwa uninstall --keep-data                 # keep DB, configs, images; only stop containers
./niwa uninstall -y                          # skip confirmation
```

Tras el primer install, el instalador intenta dejar `niwa` como
symlink en `PATH` (`/usr/local/bin/niwa` con sudo; `~/.local/bin/niwa`
rootless). Si lo consigue, todos los comandos de arriba se pueden
ejecutar sin el `./`. Si no, el install imprime el path absoluto
alternativo — la UI (Sistema → Actualizar) también muestra el comando
exacto que funciona para esta instalación.

**Preservación de secretos en reinstall:** por defecto, un reinstall
same-mode **preserva** tokens, admin password y session secret. Esto
evita romper el login y las integraciones cada vez que ejecutas
`install`. Usa `--rotate-secrets` para forzar rotación completa.

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
Check that all 5 containers are running: `docker ps | grep niwa-`. If `mcp-gateway` is missing, check `docker logs niwa-mcp-gateway`.

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

## What's NOT in this version

- **Schema migrations** for existing DBs (only fresh installs are supported)
- **GUI** for the wizard (CLI only)
- **Token rotation** command (edit `secrets/mcp.env` manually and `niwa restart`)
- **Backup** command (back up `~/.niwa/data/niwa.sqlite3` yourself)
- **Built-in upgrade** (manual pull + reinstall for now)
- **Multi-user / RBAC** (single user always)
