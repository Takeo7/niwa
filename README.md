# Niwa

> Personal MCP gateway with built-in task management, notes, platform ops and filesystem access — installable on any machine with Docker.

**Status:** beta — feature-complete (install/uninstall/status, autonomous task execution, public exposure via Cloudflare). Validated on macOS (OrbStack). Linux paths included but not yet tested on a real fresh Linux machine.

## What is Niwa

Niwa is a self-contained Docker stack you install on your machine. It gives you:

- **44 MCP tools** that any Claude/LLM client can call to manage your tasks, notes, projects, containers, and files.
- **A web UI** (Niwa app) with 6 views: dashboard, kanban, projects, notes, history, system.
- **Two MCP gateway transports** (streamable HTTP + legacy SSE) so it works with both modern and older MCP clients (Claude Code, OpenClaw, custom builds).
- **A bearer-authed reverse proxy** (Caddy) for optional public exposure via Cloudflare Tunnel.
- **Optional task executor** (host-side launchd/systemd worker) that runs pending tasks via Claude / GPT (via `llm` CLI) / Gemini / custom command.
- **Aislamiento Docker** via socket-proxy: only one container ever touches the Docker socket.

It runs as 5 long-lived containers (`mcp-gateway`, `mcp-gateway-sse`, `caddy`, `socket-proxy`, `app`) + spawns ephemeral MCP server containers per tool call. With the optional executor enabled, also a host-side launchd/systemd worker that polls the DB.

## What you can do with it

Once installed, any LLM client connected to the gateway can:

- `task_list / task_create / task_update_status / pipeline_status / project_list ...` — full task pipeline management
- `note_list / note_create / decision_create / idea_create / research_create / diary_append_today ...` — typed notes (ADRs, ideas, research logs, diary) with bidirectional task↔idea links
- `container_list / container_logs / container_health / container_restart` — Docker ops on a whitelisted set of containers
- `read_file / write_file / list_directory / search_files ...` — filesystem access scoped to two paths you pick
- Full list: see [docs/TOOL-REFERENCE.md](./docs/TOOL-REFERENCE.md) (coming)

The killer feature: **persistent context across LLM conversations**. Create an idea today, ask Claude to refine it next week, and it has the full history.

## Quick install

You need:
- macOS or Linux
- Docker (OrbStack, Docker Desktop, Colima, or rootful Podman work)
- Python 3.9+

```bash
git clone https://github.com/yumewagener/niwa
cd niwa
./niwa install
```

The installer asks ~10 questions (instance name, install location, database, ports, restart whitelist, tokens, credentials, optional client registration) and then:

1. Generates `~/.niwa/` with config files and a fresh SQLite DB (or uses an existing one)
2. Builds 4 Docker images
3. Starts 5 containers (`docker compose up -d`)
4. Healthchecks the gateway
5. Optionally registers itself with Claude Code (via `claude mcp add`) and OpenClaw (via `openclaw mcp set`)
6. Prints endpoints and tokens

Total: **3-5 minutes** on a warm cache.

## CLI commands

```bash
./niwa install              # interactive install (default)
./niwa status               # show status of an existing install
./niwa restart              # docker compose restart
./niwa logs [service]       # tail container logs (default: mcp-gateway)
./niwa uninstall            # tear down (containers + images + install dir)
./niwa uninstall --keep-data    # keep DB and configs
./niwa uninstall -y         # skip confirmation
```

All commands accept `--dir <path>` to point at a non-default install location.

## Architecture

```
                          Local clients
                          (Claude Code, OpenClaw, n8n, custom)
                                  │
                       ┌──────────┴──────────┐
                       │                     │
                       ▼                     ▼
            127.0.0.1:18810/mcp    127.0.0.1:18812/sse
            (streaming HTTP)        (SSE legacy)
                       │                     │
                       └──────────┬──────────┘
                                  │
                          mcp-gateway (×2 twin)
                                  │
                                  │  DOCKER_HOST=tcp://socket-proxy:2375
                                  ▼
                        socket-proxy (only container with /var/run/docker.sock)
                                  │
                                  │  spawn on-demand (--rm)
                                  ▼
                  ┌───────────┬───────────┬───────────┐
                  │           │           │           │
              tasks-mcp     notes-mcp    platform-mcp  mcp/filesystem
              (7 tools)    (22 tools)  (4 tools)    (11 tools)
                  │           │           │           │
                  ▼           ▼           ▼           ▼
                niwa.sqlite3 (RW)    socket-proxy   /workspace + /memory
                                                    (scoped paths)


            niwa-app (web UI, port 8080)   caddy (reverse proxy, bearer auth)
            ─────────────────────────       ─────────────────────────────────
            <instance>-app:latest           caddy:2-alpine
            backend/app.py                  fronts mcp-gateway for public access
            frontend (vanilla JS SPA)       validates Authorization: Bearer

            task-executor (host-side, optional, launchd/systemd)
            ────────────────────────────────────────────────────
            bin/task-executor.py
            polls niwa.sqlite3 for status='pendiente' tasks
            dispatches via configured LLM CLI (claude/llm/gemini/custom)
```

## Renameable

The 4 MCP servers are nameable per install. Defaults: `tasks`, `notes`, `platform`, `filesystem`. You can rename them in the wizard. The instance name (default `niwa`) prefixes container/image/network names so multiple installs can coexist on the same machine.

## Project structure

```
niwa/
├── README.md                      # this file
├── INSTALL.md                     # detailed install guide
├── niwa                           # CLI wrapper (bash → setup.py)
├── setup.py                       # interactive installer (~1500 lines, stdlib only)
├── docker-compose.yml.tmpl        # template (filled at install time)
├── niwa.env.example               # example env vars
├── caddy/Caddyfile                # reverse proxy config
├── bin/
│   └── task-executor.py           # host-side executor (optional)
├── servers/
│   ├── tasks-mcp/                 # tasks/projects MCP (Python + mcp SDK)
│   ├── notes-mcp/                 # typed notes MCP (decision/idea/research/diary)
│   └── platform-mcp/              # docker ops MCP
├── niwa-app/                      # web UI (Python stdlib, no framework)
│   ├── backend/app.py             # all routes + handlers
│   ├── frontend/                  # vanilla JS SPA, 6 views
│   ├── db/schema.sql              # authoritative schema
│   └── Dockerfile
└── docs/
    ├── PORTABILITY-PLAN.md        # internal: design history
    └── ISU-AUDIT.md               # internal: strip plan
```

## What's in / out of the install

**Installed by default:**
- 4 MCP servers (44 tools)
- Niwa app web UI on port 8080 (configurable)
- Caddy reverse proxy on port 18811
- Two MCP gateway twins (streaming + SSE) on 18810/18812

**Not installed (optional, ask in the wizard):**
- Cloudflare Tunnel for public exposure (needs cloudflared + a tunnel ID)
- Task executor (needs an LLM CLI: claude / llm / gemini / custom command)
- GitHub MCP catalog server (needs PAT, currently skipped)
- Auto-registration with Claude Code or OpenClaw (only if detected and you say yes)

**Excluded entirely from the portable version:**
- The 5 legacy views removed during the port: calendar, email, agents, connections, terminal
- Google/Outlook OAuth flows
- The full original Yume agent ecosystem (this pack ships the schema and the web UI; the agents themselves stay in your other systems)

## Known limitations

- **No fresh-machine test on Linux** yet. macOS + OrbStack is the validated path. Linux paths (systemd unit, rootless socket detection) are written but unverified end-to-end.
- **Schema migrations**: only "fresh DB" or "use as-is" — no auto-migrate of an old DB to the latest schema.
- **Image tags use `:latest`** for upstream containers (`docker/mcp-gateway`, `caddy:2-alpine`, `tecnativa/docker-socket-proxy`, `mcp/filesystem`). Bump risk — pin in compose if you need stability.
- **No backup or upgrade subcommand** yet. Back up `~/.niwa/data/niwa.sqlite3` yourself; update via `git pull && ./niwa uninstall --keep-data && ./niwa install`.
- **Token rotation** not exposed as a command. Edit `~/.niwa/secrets/mcp.env` and `niwa restart`.
- Single-user, single-instance per install location.

## Security model

- All ports bind to `127.0.0.1` by default. Niwa is **not** publicly reachable until you opt in.
- Tokens are 256-bit (`secrets.token_hex(32)`), stored in `~/.niwa/secrets/mcp.env` (chmod 600, dir chmod 700).
- The gateway disables its own bearer-auth in container mode (limitation of `docker/mcp-gateway`); Caddy is the enforcement layer for any future remote exposure.
- `platform-mcp` cannot restart containers in the Niwa stack itself (chicken-and-egg protection — hardcoded suffix exclusions in the wizard).
- Read-only DB access is enforced in 3 layers: SQLite URI mode, helper functions, and tool input schemas.

## License

TBD

## Credits

Built on top of:
- [Docker MCP Gateway](https://github.com/docker/mcp-gateway) — official, used as the gateway
- [tecnativa/docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy) — socket isolation
- [Caddy](https://caddyserver.com/) — reverse proxy
- [@modelcontextprotocol/server-filesystem](https://hub.docker.com/r/mcp/filesystem) — filesystem MCP
- The web app is a stripped-down derivative of a personal kanban app, ported and parameterized for portability.

---

🌿 *Niwa* (庭) means "garden" in Japanese — the place where the personal system grows.
