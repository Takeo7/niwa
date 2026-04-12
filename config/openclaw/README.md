# OpenClaw Integration

This directory contains files used to configure OpenClaw when it's installed alongside Niwa.

## Files

- `niwa-skill.md` — OpenClaw skill that teaches the agent how to use Niwa's MCP tools.
  Automatically installed to `~/.config/openclaw/skills/niwa.md` during setup.

## How It Works

When you install Niwa with OpenClaw enabled:
1. `setup.py` installs OpenClaw via npm
2. Registers Niwa's MCP gateway as a server (`openclaw mcp set niwa ...`)
3. Installs the Niwa skill to OpenClaw's skills directory
4. Updates `openclaw.json` with the MCP server config
5. Verifies the connection

After that, OpenClaw can use Niwa tools automatically.
