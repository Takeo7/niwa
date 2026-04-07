# Niwa

> Personal MCP gateway with built-in task management, notes, platform ops and filesystem access — installable on any machine with Docker.

**Status:** alpha — under construction. See [docs/PORTABILITY-PLAN.md](./docs/PORTABILITY-PLAN.md) for the roadmap.

## What is Niwa

Niwa packages an MCP (Model Context Protocol) gateway with 4 servers and 44 tools, plus a lite version of the Isu web UI for personal task/note management. It runs as a Docker stack on your local machine and exposes itself to:

- Local LLM clients (Claude Code, OpenClaw, custom MCP clients)
- Optionally to remote clients (ChatGPT, mobile, integrations) via Cloudflare Tunnel + bearer auth

## Quick install

> Not yet ready — coming after Phase 1-7 of the portability plan.

```bash
git clone https://github.com/yumewagener/niwa
cd niwa
./niwa install
```

The interactive installer asks for:
- Where to install (default `~/.niwa`)
- Database (use existing or create fresh)
- Filesystem scope
- Restart whitelist for Docker containers
- Tokens (auto-generate or paste your own)
- Domain + Cloudflare Tunnel (only if you want remote access)
- Whether to register with detected MCP clients (Claude Code, OpenClaw)

## What you get

- **4 MCP servers, 44 tools** (tasks, notes, container ops, filesystem)
- **Isu lite**: web UI with 6 views (dashboard, kanban, projects, notes, history, system)
- **Local-only by default**, opt-in remote exposure
- **Bearer-authed reverse proxy** (Caddy) when remote enabled
- **Aislamiento Docker** via socket-proxy
- **Cero hardcoded paths** — todo configurable

## Documentation

- [PORTABILITY-PLAN.md](./docs/PORTABILITY-PLAN.md) — roadmap and design
- [ISU-AUDIT.md](./docs/ISU-AUDIT.md) — what gets stripped from Isu and why
- INSTALL.md — coming
- N8N-INTEGRATION.md — coming

## License

TBD

---

🌿 Niwa = "garden" in Japanese. The place where the personal system grows.
