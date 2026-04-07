"""
Platform MCP server — Phase 2

Verbs:
  - container_list   list all containers (running + stopped) with name, status, image
  - container_health get inspect-style state for one container
  - container_logs   tail of stdout/stderr (default 50, max 500)
  - container_restart restart a container — whitelisted to known names only

Talks to the Docker socket via tecnativa/docker-socket-proxy on the niwa-mcp network
(DOCKER_HOST=tcp://socket-proxy:2375). Uses the docker Python SDK.
"""

import asyncio
import json
import os
from typing import Any

import docker
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Whitelist of containers that can be restarted via this MCP.
# Loaded from env var PLATFORM_RESTART_WHITELIST (comma-separated container names).
# Anything not in this set is rejected with an explicit error.
#
# IMPORTANT: the Niwa stack containers (mcp-gateway, socket-proxy, caddy) should
# NEVER be in this list — the gateway must not be able to restart its own
# infrastructure (would kill the in-flight MCP session and create chicken-and-egg
# recovery problems). The setup script enforces this exclusion when generating
# the env value.
def _load_whitelist() -> set[str]:
    raw = os.environ.get("PLATFORM_RESTART_WHITELIST", "").strip()
    if not raw:
        return set()
    return {name.strip() for name in raw.split(",") if name.strip()}


RESTART_WHITELIST = _load_whitelist()

server = Server("platform")


def _client() -> docker.DockerClient:
    # DOCKER_HOST is set in env (tcp://socket-proxy:2375)
    return docker.from_env()


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="container_list",
            description="List all Docker containers (running + stopped) with name, status, image, ports.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="container_health",
            description="Inspect a single container and return its state, restart count, started_at, exit_code.",
            inputSchema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        ),
        Tool(
            name="container_logs",
            description="Tail the most recent logs of a container. Default 50 lines, max 500.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "lines": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="container_restart",
            description=(
                "Restart a container by name. Only containers in the whitelist are allowed; "
                "any other name is rejected. Returns the new status after restart."
            ),
            inputSchema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        ),
    ]


def _container_list() -> list[dict[str, Any]]:
    cli = _client()
    out = []
    for c in cli.containers.list(all=True):
        attrs = c.attrs
        ports_raw = attrs.get("NetworkSettings", {}).get("Ports") or {}
        ports = sorted({p.split("/")[0] for p in ports_raw.keys()})
        out.append(
            {
                "name": c.name,
                "id": c.short_id,
                "image": (c.image.tags[0] if c.image.tags else c.image.short_id),
                "status": c.status,
                "state": attrs.get("State", {}).get("Status"),
                "started_at": attrs.get("State", {}).get("StartedAt"),
                "ports": ports,
            }
        )
    out.sort(key=lambda x: x["name"])
    return out


def _container_health(name: str) -> dict[str, Any]:
    cli = _client()
    c = cli.containers.get(name)
    state = c.attrs.get("State", {})
    return {
        "name": c.name,
        "status": state.get("Status"),
        "running": state.get("Running"),
        "restart_count": c.attrs.get("RestartCount"),
        "started_at": state.get("StartedAt"),
        "finished_at": state.get("FinishedAt"),
        "exit_code": state.get("ExitCode"),
        "error": state.get("Error") or None,
        "health": (state.get("Health") or {}).get("Status"),
    }


def _container_logs(name: str, lines: int = 50) -> dict[str, Any]:
    cli = _client()
    c = cli.containers.get(name)
    n = max(1, min(int(lines), 500))
    raw = c.logs(tail=n, timestamps=False, stdout=True, stderr=True)
    text = raw.decode("utf-8", errors="replace")
    return {"name": c.name, "lines": n, "logs": text}


def _container_restart(name: str) -> dict[str, Any]:
    if not RESTART_WHITELIST:
        raise ValueError(
            "container_restart is disabled — no whitelist configured. "
            "Set PLATFORM_RESTART_WHITELIST env var on the platform-mcp container "
            "(comma-separated container names) to enable restarts."
        )
    if name not in RESTART_WHITELIST:
        raise ValueError(
            f"container '{name}' is not in the restart whitelist. "
            f"Allowed: {sorted(RESTART_WHITELIST)}"
        )
    cli = _client()
    c = cli.containers.get(name)
    c.restart(timeout=10)
    c.reload()
    return {"name": c.name, "status": c.status, "restarted": True}


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        args = arguments or {}
        if name == "container_list":
            payload: Any = _container_list()
        elif name == "container_health":
            payload = _container_health(args["name"])
        elif name == "container_logs":
            payload = _container_logs(args["name"], args.get("lines", 50))
        elif name == "container_restart":
            payload = _container_restart(args["name"])
        else:
            return [TextContent(type="text", text=json.dumps({"error": f"unknown tool: {name}"}))]
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, default=str))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e), "tool": name}))]


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
