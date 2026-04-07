#!/usr/bin/env python3
"""
Niwa installer — interactive setup wizard.

Usage:
    ./setup.py install      # interactive install (default)
    ./setup.py status       # show running status of an existing install
    ./setup.py uninstall    # tear down an existing install (P9, future)

Zero external deps — uses Python stdlib only. Tested on Python 3.10+.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import socket
import string
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# ────────────────────────── pretty output ──────────────────────────
NO_COLOR = os.environ.get("NO_COLOR") or not sys.stdout.isatty()
RESET = "" if NO_COLOR else "\033[0m"
BOLD = "" if NO_COLOR else "\033[1m"
DIM = "" if NO_COLOR else "\033[2m"
GREEN = "" if NO_COLOR else "\033[32m"
RED = "" if NO_COLOR else "\033[31m"
YELLOW = "" if NO_COLOR else "\033[33m"
CYAN = "" if NO_COLOR else "\033[36m"


def info(msg: str) -> None:
    print(f"{CYAN}ℹ{RESET}  {msg}")


def ok(msg: str) -> None:
    print(f"{GREEN}✓{RESET}  {msg}")


def warn(msg: str) -> None:
    print(f"{YELLOW}⚠{RESET}  {msg}")


def err(msg: str) -> None:
    print(f"{RED}✗{RESET}  {msg}", file=sys.stderr)


def header(msg: str) -> None:
    print(f"\n{BOLD}{msg}{RESET}")
    print(f"{DIM}{'─' * len(msg)}{RESET}")


# ────────────────────────── prompts ──────────────────────────
def prompt(question: str, default: Optional[str] = None, validator=None) -> str:
    suffix = f" {DIM}[{default}]{RESET}" if default is not None else ""
    while True:
        try:
            answer = input(f"{question}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            err("aborted by user")
            sys.exit(130)
        if not answer and default is not None:
            answer = default
        if not answer:
            warn("required field — please enter a value")
            continue
        if validator:
            error_msg = validator(answer)
            if error_msg:
                warn(error_msg)
                continue
        return answer


def prompt_bool(question: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        try:
            answer = input(f"{question} {suffix}: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(130)
        if not answer:
            return default
        if answer in ("y", "yes", "s", "si", "sí"):
            return True
        if answer in ("n", "no"):
            return False
        warn("answer y or n")


def prompt_choice(question: str, options: list[str], default: int = 0) -> int:
    print(question)
    for i, opt in enumerate(options, 1):
        marker = "*" if (i - 1) == default else " "
        print(f"  [{i}]{marker} {opt}")
    while True:
        try:
            answer = input(f"choice [{default + 1}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(130)
        if not answer:
            return default
        try:
            n = int(answer) - 1
            if 0 <= n < len(options):
                return n
        except ValueError:
            pass
        warn(f"enter a number between 1 and {len(options)}")


def prompt_multiselect(question: str, options: list[tuple[str, bool]]) -> list[str]:
    """Each option is (name, default_selected). Returns list of selected names."""
    print(question)
    print(f"  {DIM}Enter comma-separated indices to toggle, or empty to accept defaults{RESET}")
    selected = {i for i, (_, default) in enumerate(options) if default}
    while True:
        for i, (name, _) in enumerate(options, 1):
            mark = f"{GREEN}[x]{RESET}" if (i - 1) in selected else "[ ]"
            print(f"  {mark} {i}. {name}")
        try:
            answer = input("toggle: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(130)
        if not answer:
            return [name for i, (name, _) in enumerate(options) if i in selected]
        try:
            for token in answer.split(","):
                token = token.strip()
                if not token:
                    continue
                idx = int(token) - 1
                if 0 <= idx < len(options):
                    if idx in selected:
                        selected.remove(idx)
                    else:
                        selected.add(idx)
        except ValueError:
            warn("enter comma-separated numbers")


# ────────────────────────── validators ──────────────────────────
def valid_instance_name(name: str) -> Optional[str]:
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", name):
        return "use lowercase letters, digits, hyphens; start with a letter; 2-31 chars"
    return None


def valid_server_name(name: str) -> Optional[str]:
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,30}", name):
        return "use lowercase letters, digits, underscores, hyphens; start with a letter"
    return None


def valid_path(p: str) -> Optional[str]:
    try:
        Path(p).expanduser()
    except Exception as e:
        return f"invalid path: {e}"
    return None


def valid_port(p: str) -> Optional[str]:
    try:
        n = int(p)
        if not (1024 <= n <= 65535):
            return "port must be between 1024 and 65535"
    except ValueError:
        return "port must be a number"
    return None


# ────────────────────────── detection ──────────────────────────
def which(name: str) -> Optional[str]:
    return shutil.which(name)


def detect_docker() -> dict:
    docker_bin = which("docker")
    if not docker_bin:
        return {"available": False}
    try:
        version_out = subprocess.run(
            ["docker", "--version"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        info_out = subprocess.run(
            ["docker", "info", "--format", "{{.OperatingSystem}}|{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=8,
        )
        runtime = "unknown"
        if info_out.returncode == 0:
            os_info = info_out.stdout.split("|")[0].strip()
            if "OrbStack" in os_info:
                runtime = "OrbStack"
            elif "Docker Desktop" in os_info:
                runtime = "Docker Desktop"
            elif "colima" in os_info.lower():
                runtime = "Colima"
            else:
                runtime = os_info
        return {"available": True, "version": version_out, "runtime": runtime}
    except Exception as e:
        return {"available": False, "error": str(e)}


def detect_socket_path() -> Optional[str]:
    candidates = [
        Path.home() / ".orbstack" / "run" / "docker.sock",
        Path("/var/run/docker.sock"),
        Path.home() / ".colima" / "default" / "docker.sock",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def detect_port_free(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


# ────────────────────────── filesystem helpers ──────────────────────────
REPO_ROOT = Path(__file__).resolve().parent


def substitute_template(text: str, vars: dict[str, str]) -> str:
    """Replace ${KEY} placeholders with vars[KEY]."""
    def repl(match):
        key = match.group(1)
        if key not in vars:
            raise KeyError(f"template variable not set: ${{{key}}}")
        return vars[key]
    return re.sub(r"\$\{([A-Z_][A-Z0-9_]*)\}", repl, text)


def write_env_file(path: Path, vars: dict[str, str]) -> None:
    lines = ["# Niwa install env — auto-generated by setup.py", ""]
    for key, value in vars.items():
        # Quote values with spaces or special chars
        if any(c in value for c in " \"'$"):
            value = '"' + value.replace('"', '\\"') + '"'
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)


# ────────────────────────── catalog generation ──────────────────────────
def generate_catalog_yaml(
    server_names: dict[str, str],
    db_path: str,
    fs_workspace: str,
    fs_memory: str,
    instance_name: str,
) -> str:
    """Generate the niwa-catalog.yaml content with the user's chosen server names."""
    tasks_name = server_names["tasks"]
    notes_name = server_names["notes"]
    platform_name = server_names["platform"]
    fs_name = server_names["filesystem"]
    return f"""version: 2
name: {instance_name}
displayName: {instance_name.capitalize()} local catalog
registry:
  {tasks_name}:
    description: "Read+write access to tasks/projects DB"
    title: "{tasks_name.capitalize()}"
    type: "server"
    image: "{instance_name}-niwa-mcp:latest"
    tools:
      - name: "task_list"
      - name: "task_get"
      - name: "project_list"
      - name: "project_get"
      - name: "pipeline_status"
      - name: "task_create"
      - name: "task_update_status"
    volumes:
      - "{db_path}:/data/desk.sqlite3"
    metadata:
      category: "{instance_name}"
      tags: [{tasks_name}, tasks]

  {notes_name}:
    description: "Personal notes (typed) and inbox"
    title: "{notes_name.capitalize()}"
    type: "server"
    image: "{instance_name}-isu-mcp:latest"
    tools:
      - name: "note_list"
      - name: "note_get"
      - name: "note_create"
      - name: "note_update"
      - name: "decision_create"
      - name: "idea_create"
      - name: "idea_append"
      - name: "idea_set_status"
      - name: "idea_promote_to_task"
      - name: "research_create"
      - name: "research_append_finding"
      - name: "research_set_conclusion"
      - name: "research_link_to_decision"
      - name: "research_list"
      - name: "decision_list"
      - name: "idea_list"
      - name: "diary_append_today"
      - name: "diary_get_today"
      - name: "diary_get"
      - name: "diary_list"
      - name: "inbox_list"
      - name: "inbox_create"
    volumes:
      - "{db_path}:/data/desk.sqlite3"
    metadata:
      category: "{instance_name}"
      tags: [{notes_name}, notes]

  {platform_name}:
    description: "Container ops (list, logs, health, restart)"
    title: "{platform_name.capitalize()}"
    type: "server"
    image: "{instance_name}-platform-mcp:latest"
    tools:
      - name: "container_list"
      - name: "container_health"
      - name: "container_logs"
      - name: "container_restart"
    env:
      - name: "DOCKER_HOST"
        value: "tcp://{instance_name}-socket-proxy:2375"
      - name: "PLATFORM_RESTART_WHITELIST"
        value: "${{PLATFORM_RESTART_WHITELIST}}"
    metadata:
      category: "{instance_name}"
      tags: [{platform_name}, docker, ops]

  {fs_name}:
    description: "Filesystem access scoped to workspace and memory"
    title: "{fs_name.capitalize()}"
    type: "server"
    image: "mcp/filesystem:latest"
    command:
      - "/workspace"
      - "/memory"
    volumes:
      - "{fs_workspace}:/workspace"
      - "{fs_memory}:/memory"
    metadata:
      category: "{instance_name}"
      tags: [{fs_name}, files]
"""


# ────────────────────────── token generation ──────────────────────────
def generate_token() -> str:
    return secrets.token_hex(32)


# ────────────────────────── wizard ──────────────────────────
class WizardConfig:
    def __init__(self):
        self.detected: dict = {}
        self.instance_name: str = "niwa"
        self.niwa_home: Path = Path.home() / ".niwa"
        self.db_mode: str = "fresh"  # or "existing"
        self.db_path: Path = Path()
        self.fs_workspace: Path = Path()
        self.fs_memory: Path = Path()
        self.restart_whitelist: list[str] = []
        self.server_names: dict[str, str] = {
            "tasks": "niwa",
            "notes": "isu",
            "platform": "platform",
            "filesystem": "filesystem",
        }
        self.gateway_streaming_port: int = 18810
        self.gateway_sse_port: int = 18812
        self.caddy_port: int = 18811
        self.isu_port: int = 8080
        self.tokens: dict[str, str] = {}
        self.username: str = "arturo"
        self.password: str = ""
        self.register_claude: bool = False
        self.register_openclaw: bool = False
        self.mode: str = "local-only"  # or "remote"
        self.public_domain: str = ""
        self.cloudflared_tunnel_id: str = ""
        self.cloudflared_config_path: Path = Path.home() / ".cloudflared" / "config.yml"


def step_detection(cfg: WizardConfig) -> None:
    header("Step 0 — Pre-flight detection")
    docker = detect_docker()
    if not docker.get("available"):
        err("Docker is not installed or not in PATH. Install OrbStack/Docker Desktop/Colima first.")
        sys.exit(1)
    ok(f"Docker: {docker['version']} ({docker.get('runtime', 'unknown')})")

    sock = detect_socket_path()
    if not sock:
        err("Could not find a Docker socket. Looked at ~/.orbstack, /var/run, ~/.colima.")
        sys.exit(1)
    ok(f"Docker socket: {sock}")
    cfg.detected["docker_socket"] = sock

    if sys.version_info < (3, 9):
        err(f"Python 3.9+ required, you have {sys.version_info.major}.{sys.version_info.minor}")
        sys.exit(1)
    ok(f"Python: {sys.version_info.major}.{sys.version_info.minor}")

    cfg.detected["openclaw"] = which("openclaw") is not None
    cfg.detected["claude"] = which("claude") is not None
    cfg.detected["cloudflared"] = which("cloudflared") is not None

    integrations = []
    if cfg.detected["openclaw"]:
        integrations.append("OpenClaw ✓")
    if cfg.detected["claude"]:
        integrations.append("Claude Code ✓")
    if cfg.detected["cloudflared"]:
        integrations.append("cloudflared ✓")
    if integrations:
        ok("Optional integrations detected: " + ", ".join(integrations))
    else:
        info("No optional integrations detected (OpenClaw, Claude Code, cloudflared) — that's fine")


def step_naming(cfg: WizardConfig) -> None:
    header("Step 1 — Naming")
    print("Pick names for your install. Defaults are fine for most users.")
    cfg.instance_name = prompt(
        "Instance name (used for container/image/network prefix)",
        default="niwa",
        validator=valid_instance_name,
    )
    cfg.niwa_home = Path(prompt(
        "Install location",
        default=str(Path.home() / f".{cfg.instance_name}"),
        validator=valid_path,
    )).expanduser()

    if prompt_bool("Customize MCP server names? (the names the LLM sees in tools/list)", default=False):
        cfg.server_names["tasks"] = prompt(
            "Tasks server name", default="niwa", validator=valid_server_name
        )
        cfg.server_names["notes"] = prompt(
            "Notes server name", default="isu", validator=valid_server_name
        )
        cfg.server_names["platform"] = prompt(
            "Platform server name", default="platform", validator=valid_server_name
        )
        cfg.server_names["filesystem"] = prompt(
            "Filesystem server name", default="filesystem", validator=valid_server_name
        )


def step_database(cfg: WizardConfig) -> None:
    header("Step 2 — Database")
    print("Niwa needs a SQLite database with the Isu schema (tasks, projects, notes, etc.).")
    choice = prompt_choice(
        "Database source:",
        ["Create a fresh empty database (recommended for new installs)",
         "Use an existing database"],
        default=0,
    )
    if choice == 0:
        cfg.db_mode = "fresh"
        cfg.db_path = cfg.niwa_home / "data" / "desk.sqlite3"
        info(f"Will create a fresh DB at {cfg.db_path}")
    else:
        cfg.db_mode = "existing"
        existing = prompt("Path to existing desk.sqlite3", validator=valid_path)
        cfg.db_path = Path(existing).expanduser().resolve()
        if not cfg.db_path.exists():
            err(f"File not found: {cfg.db_path}")
            sys.exit(1)
        warn(
            "Heads-up: the installer will not migrate existing schemas. "
            "If your DB is missing the Phase 5 columns (notes.type, etc.), "
            "the Niwa MCP servers may fail at runtime."
        )


def step_filesystem(cfg: WizardConfig) -> None:
    header("Step 3 — Filesystem MCP scope")
    print("The filesystem MCP server gives the LLM read+write access to specific dirs.")
    cfg.fs_workspace = Path(prompt(
        "Workspace path (exposed as /workspace)",
        default=str(cfg.niwa_home / "data"),
        validator=valid_path,
    )).expanduser()
    cfg.fs_memory = Path(prompt(
        "Memory path (exposed as /memory)",
        default=str(cfg.niwa_home / "memory"),
        validator=valid_path,
    )).expanduser()


def step_restart_whitelist(cfg: WizardConfig) -> None:
    header("Step 4 — Platform MCP restart whitelist")
    print("Which containers should the LLM be allowed to restart via container_restart?")
    print(f"{DIM}(The Niwa stack containers are excluded automatically.){RESET}")
    try:
        out = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=8,
        )
        running = [n for n in out.stdout.strip().split("\n") if n]
    except Exception:
        running = []

    # Exclude any container that is part of a niwa pack stack (current or other installs).
    # We match by suffix because the prefix is the install's instance name.
    forbidden_suffixes = ("-mcp-gateway", "-mcp-gateway-sse", "-socket-proxy", "-caddy")
    def is_niwa_stack(n: str) -> bool:
        return any(n.endswith(s) for s in forbidden_suffixes)
    options = [(name, True) for name in running if not is_niwa_stack(name)]
    if not options:
        info("No eligible containers detected — restart whitelist will be empty.")
        info("You can add it later by editing PLATFORM_RESTART_WHITELIST in niwa.env")
        cfg.restart_whitelist = []
        return
    cfg.restart_whitelist = prompt_multiselect(
        "Toggle containers to allow (defaults marked):",
        options,
    )


def step_tokens(cfg: WizardConfig) -> None:
    header("Step 5 — Auth tokens")
    print("Niwa uses 2 bearer tokens (local-trusted and remote-restricted).")
    if prompt_bool("Generate them automatically?", default=True):
        cfg.tokens["NIWA_LOCAL_TOKEN"] = generate_token()
        cfg.tokens["NIWA_REMOTE_TOKEN"] = generate_token()
        cfg.tokens["MCP_GATEWAY_AUTH_TOKEN"] = cfg.tokens["NIWA_LOCAL_TOKEN"]
        ok("2 tokens generated (256-bit each)")
    else:
        cfg.tokens["NIWA_LOCAL_TOKEN"] = prompt("Local trusted token (paste)")
        cfg.tokens["NIWA_REMOTE_TOKEN"] = prompt("Remote restricted token (paste)")
        cfg.tokens["MCP_GATEWAY_AUTH_TOKEN"] = cfg.tokens["NIWA_LOCAL_TOKEN"]


def step_credentials(cfg: WizardConfig) -> None:
    header("Step 6 — Isu web login")
    print("Set credentials for the Isu web UI (you'll log in with these in the browser).")
    cfg.username = prompt("Username", default="arturo")
    cfg.password = prompt("Password (visible — write it down or pick something temporary)")


def step_ports(cfg: WizardConfig) -> None:
    header("Step 7 — Ports")
    print("All ports are bound to 127.0.0.1 (loopback only) by default.")
    defaults = [
        ("Gateway streaming HTTP", "gateway_streaming_port", 18810),
        ("Gateway SSE legacy", "gateway_sse_port", 18812),
        ("Caddy reverse proxy", "caddy_port", 18811),
        ("Isu web UI", "isu_port", 8080),
    ]
    for label, attr, default in defaults:
        in_use = not detect_port_free(default)
        suffix = f" {YELLOW}(default in use!){RESET}" if in_use else ""
        while True:
            answer = prompt(f"{label} port{suffix}", default=str(default), validator=valid_port)
            n = int(answer)
            if not detect_port_free(n):
                if n == default and not prompt_bool(
                    f"  Port {n} appears to be in use. Continue anyway?", default=False
                ):
                    continue
                if n != default:
                    warn(f"  Port {n} appears to be in use. Pick another.")
                    continue
            setattr(cfg, attr, n)
            break


def step_remote(cfg: WizardConfig) -> None:
    header("Step 8 — Public exposure (optional)")
    print("By default, Niwa is local-only (loopback). To access from outside (mobile,")
    print("ChatGPT, n8n in another machine), you can opt in to remote exposure via")
    print("Cloudflare Tunnel + Caddy bearer auth.")
    print()
    if not prompt_bool("Enable remote access via Cloudflare Tunnel?", default=False):
        cfg.mode = "local-only"
        return

    if not cfg.detected.get("cloudflared"):
        warn("cloudflared is NOT installed. You can:")
        print("  - Install it (brew install cloudflared / apt install cloudflared)")
        print("  - Or skip remote for now and run './niwa install' again later")
        if not prompt_bool("Continue with remote setup anyway?", default=False):
            cfg.mode = "local-only"
            return

    cfg.mode = "remote"
    cfg.public_domain = prompt(
        "Public domain (must be on a Cloudflare-managed zone you own)",
        validator=lambda v: None if "." in v and " " not in v else "must be a valid domain like mcp.example.com",
    )

    print()
    print("Cloudflare Tunnel:")
    choice = prompt_choice(
        "How do you want to provide the tunnel?",
        [
            "Use an existing tunnel (you provide the tunnel ID)",
            "Skip — I'll configure cloudflared manually after install",
        ],
        default=0,
    )
    if choice == 0:
        cfg.cloudflared_tunnel_id = prompt(
            "Tunnel ID (UUID, find with 'cloudflared tunnel list')",
            validator=lambda v: None if re.fullmatch(r"[0-9a-f-]{36}", v) else "must be a UUID like 590d0340-d087-402b-a813-32e7e239c863",
        )
    else:
        cfg.cloudflared_tunnel_id = ""
        info("You can wire the tunnel manually after install. The Caddy reverse proxy")
        info(f"will be ready at http://localhost:{cfg.caddy_port}/mcp — point your tunnel there.")


def step_clients(cfg: WizardConfig) -> None:
    header("Step 9 — Auto-register MCP clients")
    if cfg.detected["claude"]:
        cfg.register_claude = prompt_bool(
            "Register Niwa with Claude Code (user scope, claude mcp add)?", default=True
        )
    if cfg.detected["openclaw"]:
        cfg.register_openclaw = prompt_bool(
            "Register Niwa with OpenClaw (openclaw mcp set)?", default=True
        )
    if not cfg.detected["claude"] and not cfg.detected["openclaw"]:
        info("No MCP clients detected to register. You can wire any client manually using:")
        info(f"  Streaming HTTP: http://localhost:{cfg.gateway_streaming_port}/mcp")
        info(f"  SSE legacy:     http://localhost:{cfg.gateway_sse_port}/sse")


def step_summary(cfg: WizardConfig) -> bool:
    header("Step 10 — Summary")
    print(f"  Instance name:      {cfg.instance_name}")
    print(f"  Install location:   {cfg.niwa_home}")
    print(f"  Database:           {cfg.db_mode} at {cfg.db_path}")
    print(f"  Filesystem scope:   {cfg.fs_workspace} → /workspace")
    print(f"                      {cfg.fs_memory} → /memory")
    print(f"  Server names:       tasks={cfg.server_names['tasks']}, "
          f"notes={cfg.server_names['notes']}, platform={cfg.server_names['platform']}, "
          f"fs={cfg.server_names['filesystem']}")
    print(f"  Restart whitelist:  {', '.join(cfg.restart_whitelist) if cfg.restart_whitelist else '(empty — restarts disabled)'}")
    print(f"  Ports:              gateway={cfg.gateway_streaming_port}, "
          f"sse={cfg.gateway_sse_port}, caddy={cfg.caddy_port}, isu={cfg.isu_port}")
    print(f"  Tokens:             auto-generated, stored in niwa.env (chmod 600)")
    print(f"  Isu login:          {cfg.username}")
    print(f"  Mode:               {cfg.mode}")
    if cfg.mode == "remote":
        print(f"  Public domain:      {cfg.public_domain}")
        print(f"  Tunnel ID:          {cfg.cloudflared_tunnel_id or '(skip — manual config)'}")
    print(f"  Register Claude:    {cfg.register_claude}")
    print(f"  Register OpenClaw:  {cfg.register_openclaw}")
    print()
    return prompt_bool("Proceed with install?", default=True)


# ────────────────────────── execution ──────────────────────────
def execute_install(cfg: WizardConfig) -> None:
    header("Step 10 — Building install")
    cfg.niwa_home.mkdir(parents=True, exist_ok=True)
    (cfg.niwa_home / "config").mkdir(parents=True, exist_ok=True)
    (cfg.niwa_home / "data").mkdir(parents=True, exist_ok=True)
    (cfg.niwa_home / "logs").mkdir(parents=True, exist_ok=True)
    (cfg.niwa_home / "secrets").mkdir(mode=0o700, parents=True, exist_ok=True)
    (cfg.niwa_home / "caddy").mkdir(parents=True, exist_ok=True)
    cfg.fs_workspace.mkdir(parents=True, exist_ok=True)
    cfg.fs_memory.mkdir(parents=True, exist_ok=True)
    ok(f"Install dirs created at {cfg.niwa_home}")

    # Build env vars dict
    env_vars = {
        "NIWA_MODE": cfg.mode,
        "NIWA_PUBLIC_DOMAIN": cfg.public_domain,
        "NIWA_CLOUDFLARE_TUNNEL_ID": cfg.cloudflared_tunnel_id,
        "INSTANCE_NAME": cfg.instance_name,
        "NIWA_HOME": str(cfg.niwa_home),
        "NIWA_LOGS_DIR": str(cfg.niwa_home / "logs"),
        "NIWA_SECRETS_DIR": str(cfg.niwa_home / "secrets"),
        "NIWA_DB_PATH": str(cfg.db_path),
        "NIWA_FILESYSTEM_WORKSPACE": str(cfg.fs_workspace),
        "NIWA_FILESYSTEM_MEMORY": str(cfg.fs_memory),
        "NIWA_GATEWAY_STREAMING_PORT": str(cfg.gateway_streaming_port),
        "NIWA_GATEWAY_SSE_PORT": str(cfg.gateway_sse_port),
        "NIWA_CADDY_PORT": str(cfg.caddy_port),
        "NIWA_ISU_PORT": str(cfg.isu_port),
        "NIWA_ENABLED_SERVERS": ",".join(cfg.server_names[k] for k in ("tasks", "notes", "platform", "filesystem")),
        "NIWA_TASKS_SERVER_NAME": cfg.server_names["tasks"],
        "NIWA_NOTES_SERVER_NAME": cfg.server_names["notes"],
        "NIWA_PLATFORM_SERVER_NAME": cfg.server_names["platform"],
        "NIWA_FILESYSTEM_SERVER_NAME": cfg.server_names["filesystem"],
        "MCP_GATEWAY_AUTH_TOKEN": cfg.tokens["MCP_GATEWAY_AUTH_TOKEN"],
        "NIWA_LOCAL_TOKEN": cfg.tokens["NIWA_LOCAL_TOKEN"],
        "NIWA_REMOTE_TOKEN": cfg.tokens["NIWA_REMOTE_TOKEN"],
        "PLATFORM_RESTART_WHITELIST": ",".join(cfg.restart_whitelist),
        "DESK_USERNAME": cfg.username,
        "DESK_PASSWORD": cfg.password,
        "DESK_SESSION_SECRET": generate_token(),
        "DESK_PUBLIC_BASE_URL": f"http://localhost:{cfg.isu_port}",
        "DESK_AUTH_REQUIRED": "1",
        "NIWA_REGISTERED_CLAUDE": "1" if cfg.register_claude else "0",
        "NIWA_REGISTERED_OPENCLAW": "1" if cfg.register_openclaw else "0",
    }

    # Write secrets file
    write_env_file(cfg.niwa_home / "secrets" / "mcp.env", env_vars)
    ok("Wrote secrets/mcp.env (chmod 600)")

    # Generate docker-compose.yml from template
    template = (REPO_ROOT / "docker-compose.yml.tmpl").read_text()
    compose_yaml = substitute_template(template, env_vars)
    (cfg.niwa_home / "docker-compose.yml").write_text(compose_yaml)
    ok("Generated docker-compose.yml")

    # Copy Caddyfile
    shutil.copy(REPO_ROOT / "caddy" / "Caddyfile", cfg.niwa_home / "caddy" / "Caddyfile")
    ok("Copied Caddyfile")

    # Generate catalog yaml
    catalog = generate_catalog_yaml(
        cfg.server_names,
        str(cfg.db_path),
        str(cfg.fs_workspace),
        str(cfg.fs_memory),
        cfg.instance_name,
    )
    (cfg.niwa_home / "config" / "niwa-catalog.yaml").write_text(catalog)
    # Generate niwa-config.yaml (still needed by gateway --config flag)
    (cfg.niwa_home / "config" / "niwa-config.yaml").write_text(
        f"# Catalog config — placeholder, actual values are templated into the catalog itself\n"
        f"{cfg.server_names['tasks']}:\n  enabled: true\n"
    )
    ok("Generated catalog and config")

    # Bootstrap fresh DB if needed
    if cfg.db_mode == "fresh":
        info("Bootstrapping fresh database with Isu schema...")
        schema_sql = (REPO_ROOT / "isu-app" / "db" / "schema.sql").read_text()
        import sqlite3
        with sqlite3.connect(str(cfg.db_path)) as conn:
            conn.executescript(schema_sql)
            # Seed default kanban columns and a default project
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            kanban = [
                ("col-inbox", "inbox", "Inbox", 0, "secondary", 0),
                ("col-pendiente", "pendiente", "Pendiente", 1, "primary", 0),
                ("col-en-progreso", "en_progreso", "En Progreso", 2, "tertiary", 0),
                ("col-bloqueada", "bloqueada", "Bloqueada", 3, "error", 0),
                ("col-revision", "revision", "Revisión", 4, "warning", 0),
                ("col-hecha", "hecha", "Hecha", 5, "primary", 1),
                ("col-archivada", "archivada", "Archivada", 6, "outline", 1),
            ]
            for col_id, status, label, position, color, is_terminal in kanban:
                conn.execute(
                    "INSERT OR IGNORE INTO kanban_columns (id, status, label, position, color, is_terminal, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (col_id, status, label, position, color, is_terminal, ts, ts),
                )
            conn.execute(
                "INSERT OR IGNORE INTO projects (id, slug, name, area, description, active, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                ("proj-default", "default", "Default", "proyecto", f"Default project for {cfg.instance_name}", 1, ts, ts),
            )
            conn.commit()
        ok(f"Fresh DB created at {cfg.db_path}")

    # Build images
    header("Step 13 — Building Docker images")
    images = [
        ("niwa-mcp", REPO_ROOT / "servers" / "niwa-mcp", f"{cfg.instance_name}-niwa-mcp:latest"),
        ("isu-mcp", REPO_ROOT / "servers" / "isu-mcp", f"{cfg.instance_name}-isu-mcp:latest"),
        ("platform-mcp", REPO_ROOT / "servers" / "platform-mcp", f"{cfg.instance_name}-platform-mcp:latest"),
        ("isu-app", REPO_ROOT / "isu-app", f"{cfg.instance_name}-isu:latest"),
    ]
    for name, ctx, tag in images:
        info(f"Building {name} → {tag}")
        result = subprocess.run(
            ["docker", "build", "-t", tag, str(ctx)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            err(f"Build failed for {name}:")
            print(result.stderr[-2000:])
            sys.exit(1)
        ok(f"Built {tag}")

    # Pull mcp/filesystem
    info("Pulling mcp/filesystem (official catalog)...")
    subprocess.run(["docker", "pull", "mcp/filesystem:latest"], check=False, capture_output=True)
    ok("Pulled mcp/filesystem")

    # docker compose up
    header("Step 14 — Starting the stack")
    result = subprocess.run(
        ["docker", "compose", "-f", str(cfg.niwa_home / "docker-compose.yml"), "up", "-d"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        err("docker compose up failed:")
        print(result.stderr)
        sys.exit(1)
    ok("Containers started")
    time.sleep(5)

    # Healthcheck
    info("Running healthcheck...")
    try:
        with urllib.request.urlopen(f"http://localhost:{cfg.gateway_streaming_port}/mcp", timeout=5) as r:
            ok(f"Gateway responding on port {cfg.gateway_streaming_port}")
    except urllib.error.HTTPError as e:
        # 4xx is OK — means server is up but rejected the GET (expected for /mcp without proper handshake)
        if e.code in (400, 405, 406):
            ok(f"Gateway responding on port {cfg.gateway_streaming_port} (HTTP {e.code} expected for GET)")
        else:
            warn(f"Gateway returned HTTP {e.code} — check 'docker logs {cfg.instance_name}-mcp-gateway'")
    except Exception as e:
        warn(f"Gateway health check failed: {e}")
        warn(f"  Run: docker logs {cfg.instance_name}-mcp-gateway")

    # Configure cloudflared if remote mode
    if cfg.mode == "remote" and cfg.cloudflared_tunnel_id:
        configure_cloudflared(cfg)

    # Register clients
    if cfg.register_claude:
        info("Registering with Claude Code...")
        result = subprocess.run(
            ["claude", "mcp", "add", "--scope", "user", "--transport", "http",
             cfg.server_names["tasks"], f"http://localhost:{cfg.gateway_streaming_port}/mcp"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            ok(f"Registered '{cfg.server_names['tasks']}' with Claude Code (user scope)")
        else:
            warn(f"Claude Code registration failed: {result.stderr}")

    if cfg.register_openclaw:
        info("Registering with OpenClaw...")
        sse_url = f"http://localhost:{cfg.gateway_sse_port}/sse"
        result = subprocess.run(
            ["openclaw", "mcp", "set", cfg.server_names["tasks"],
             json.dumps({"type": "sse", "url": sse_url})],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            ok(f"Registered '{cfg.server_names['tasks']}' with OpenClaw (SSE)")
        else:
            warn(f"OpenClaw registration failed: {result.stderr}")

    print_summary(cfg)


def print_summary(cfg: WizardConfig) -> None:
    header("✅ Niwa is up")
    print()
    print(f"  {BOLD}Endpoints:{RESET}")
    print(f"    Local (streaming HTTP):  http://localhost:{cfg.gateway_streaming_port}/mcp")
    print(f"    Local (SSE legacy):      http://localhost:{cfg.gateway_sse_port}/sse")
    print(f"    Caddy reverse proxy:     http://localhost:{cfg.caddy_port}/mcp (bearer auth)")
    print(f"    Isu web UI:              http://localhost:{cfg.isu_port}")
    if cfg.mode == "remote" and cfg.public_domain:
        print(f"    Public (remote):         https://{cfg.public_domain}/mcp (bearer NIWA_REMOTE_TOKEN)")
    print()
    print(f"  {BOLD}Tokens:{RESET}")
    print(f"    Remote (for public/external clients): {cfg.tokens['NIWA_REMOTE_TOKEN'][:16]}...")
    print(f"    Full tokens are in: {cfg.niwa_home / 'secrets' / 'mcp.env'}")
    print()
    print(f"  {BOLD}MCP servers:{RESET} {', '.join(cfg.server_names.values())}")
    print()
    print(f"  {BOLD}Next steps:{RESET}")
    print(f"    - Open the Isu UI:    open http://localhost:{cfg.isu_port}")
    if cfg.register_claude:
        print(f"    - Test from Claude Code:  ask it to use the '{cfg.server_names['tasks']}' MCP")
    print(f"    - View logs:          docker logs {cfg.instance_name}-mcp-gateway")
    print(f"    - Stop:               docker compose -f {cfg.niwa_home / 'docker-compose.yml'} down")
    print(f"    - Restart:            docker compose -f {cfg.niwa_home / 'docker-compose.yml'} restart")
    print()


# ────────────────────────── subcommands ──────────────────────────
def configure_cloudflared(cfg: WizardConfig) -> None:
    """Add Niwa hostname to cloudflared config and create the DNS route."""
    info("Configuring cloudflared tunnel...")
    config_path = cfg.cloudflared_config_path
    if not config_path.exists():
        warn(f"cloudflared config not found at {config_path}")
        warn("Skipping tunnel config — wire it manually after install:")
        warn(f"  Add to {config_path} ingress: hostname={cfg.public_domain} → http://localhost:{cfg.caddy_port}")
        return

    # Read current config (simple parser — assume well-formed)
    content = config_path.read_text()
    new_entry = f"  - hostname: {cfg.public_domain}\n    service: http://localhost:{cfg.caddy_port}\n"

    if cfg.public_domain in content:
        info(f"Hostname {cfg.public_domain} already in cloudflared config — skipping ingress add")
    else:
        # Insert after "ingress:" line
        if "\ningress:\n" in content or content.startswith("ingress:\n"):
            lines = content.split("\n")
            out = []
            inserted = False
            for line in lines:
                out.append(line)
                if line.strip() == "ingress:" and not inserted:
                    out.append(new_entry.rstrip())
                    inserted = True
            if inserted:
                # Backup before write
                config_path.with_suffix(".yml.bak").write_text(content)
                config_path.write_text("\n".join(out))
                ok(f"Added {cfg.public_domain} to cloudflared ingress (backup at .yml.bak)")
            else:
                warn("Could not find 'ingress:' anchor in cloudflared config")
                return
        else:
            warn("cloudflared config has no 'ingress:' section — skipping")
            return

    # DNS route
    info(f"Creating DNS route for {cfg.public_domain}...")
    result = subprocess.run(
        ["cloudflared", "tunnel", "route", "dns",
         cfg.cloudflared_tunnel_id, cfg.public_domain],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        ok(f"DNS route created: {cfg.public_domain} → tunnel {cfg.cloudflared_tunnel_id[:8]}...")
    else:
        warn(f"DNS route failed: {result.stderr.strip()[:300]}")
        warn("If the route already exists, this is fine. Otherwise create it manually:")
        warn(f"  cloudflared tunnel route dns {cfg.cloudflared_tunnel_id} {cfg.public_domain}")

    # Reload cloudflared
    info("Reloading cloudflared service...")
    if sys.platform == "darwin":
        # macOS launchctl
        result = subprocess.run(
            ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.cloudflare.cloudflared"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            ok("cloudflared restarted via launchctl")
        else:
            warn(f"launchctl restart failed (cloudflared may not be running as a service): {result.stderr.strip()[:200]}")
            warn("Restart manually: launchctl kickstart -k gui/$(id -u)/com.cloudflare.cloudflared")
    else:
        # Linux systemd
        result = subprocess.run(
            ["systemctl", "restart", "cloudflared"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            ok("cloudflared restarted via systemctl")
        else:
            warn("Could not restart cloudflared automatically. Restart manually:")
            warn("  sudo systemctl restart cloudflared")


def cmd_install(args) -> None:
    print(f"{BOLD}🌿 Niwa installer{RESET}")
    print(f"{DIM}Interactive setup for the Niwa MCP gateway + Isu lite web UI{RESET}\n")
    cfg = WizardConfig()
    step_detection(cfg)
    step_naming(cfg)
    step_database(cfg)
    step_filesystem(cfg)
    step_restart_whitelist(cfg)
    step_tokens(cfg)
    step_credentials(cfg)
    step_ports(cfg)
    step_remote(cfg)
    step_clients(cfg)
    if not step_summary(cfg):
        info("Aborted — nothing was installed")
        return
    execute_install(cfg)


def _find_install_dir(provided: Optional[str] = None) -> Optional[Path]:
    """Locate an existing niwa install. Tries common locations."""
    if provided:
        p = Path(provided).expanduser()
        if (p / "docker-compose.yml").exists():
            return p
        return None
    candidates = [Path.home() / ".niwa"]
    # Look for any ~/.* dir that has a niwa-style install
    for p in Path.home().glob(".*"):
        if p.is_dir() and (p / "docker-compose.yml").exists() and (p / "secrets" / "mcp.env").exists():
            candidates.append(p)
    for c in candidates:
        if (c / "docker-compose.yml").exists():
            return c
    return None


def _read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Strip quotes
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1].replace('\\"', '"')
        out[key.strip()] = value
    return out


def cmd_status(args) -> None:
    install_dir = _find_install_dir(args.dir)
    if not install_dir:
        err("No niwa install found. Use --dir to specify the location, or run 'niwa install'.")
        sys.exit(1)
    env = _read_env_file(install_dir / "secrets" / "mcp.env")
    instance = env.get("INSTANCE_NAME", "?")
    streaming_port = env.get("NIWA_GATEWAY_STREAMING_PORT", "?")
    sse_port = env.get("NIWA_GATEWAY_SSE_PORT", "?")
    caddy_port = env.get("NIWA_CADDY_PORT", "?")
    isu_port = env.get("NIWA_ISU_PORT", "?")

    header(f"Niwa install: {instance}")
    print(f"  Location:  {install_dir}")
    print(f"  Endpoints:")
    print(f"    Gateway streaming HTTP:  http://localhost:{streaming_port}/mcp")
    print(f"    Gateway SSE legacy:      http://localhost:{sse_port}/sse")
    print(f"    Caddy reverse proxy:     http://localhost:{caddy_port}/mcp")
    print(f"    Isu web UI:              http://localhost:{isu_port}")
    print()
    print(f"  {BOLD}Containers:{RESET}")
    try:
        out = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={instance}-",
             "--format", "  {{.Names}}\\t{{.Status}}"],
            capture_output=True, text=True, timeout=8,
        )
        if out.stdout.strip():
            for line in out.stdout.strip().split("\n"):
                print("  " + line.replace("\\t", "  "))
        else:
            print(f"  {DIM}(no containers found — install may be torn down){RESET}")
    except Exception as e:
        warn(f"Could not list containers: {e}")
    print()

    # Gateway healthcheck
    info("Gateway healthcheck...")
    try:
        with urllib.request.urlopen(f"http://localhost:{streaming_port}/mcp", timeout=3) as r:
            ok(f"Gateway responding ({r.status})")
    except urllib.error.HTTPError as e:
        if e.code in (400, 405, 406):
            ok(f"Gateway responding (HTTP {e.code} expected for GET /mcp)")
        else:
            warn(f"Gateway HTTP {e.code}")
    except Exception as e:
        warn(f"Gateway not reachable: {e}")

    # Isu healthcheck
    try:
        with urllib.request.urlopen(f"http://localhost:{isu_port}/health", timeout=3) as r:
            ok(f"Isu responding ({r.status})")
    except Exception as e:
        warn(f"Isu not reachable: {e}")


def cmd_uninstall(args) -> None:
    install_dir = _find_install_dir(args.dir)
    if not install_dir:
        err("No niwa install found. Use --dir to specify the location.")
        sys.exit(1)

    env = _read_env_file(install_dir / "secrets" / "mcp.env")
    instance = env.get("INSTANCE_NAME", "niwa")

    header(f"Uninstall niwa: {instance}")
    print(f"  Location:        {install_dir}")
    print(f"  Will stop:       all {instance}-* containers")
    print(f"  Will remove:     docker images for {instance}-niwa-mcp, {instance}-isu-mcp, "
          f"{instance}-platform-mcp, {instance}-isu")
    print(f"  Will delete:     {install_dir} (including DB and logs)")
    print()
    if not args.yes:
        if not prompt_bool("Proceed with uninstall? (this is irreversible)", default=False):
            info("Aborted")
            return

    # docker compose down
    info("Stopping containers...")
    result = subprocess.run(
        ["docker", "compose", "-f", str(install_dir / "docker-compose.yml"), "down"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        ok("Containers stopped and removed")
    else:
        warn(f"docker compose down had issues: {result.stderr[:300]}")

    # Remove images
    images = [
        f"{instance}-niwa-mcp:latest",
        f"{instance}-isu-mcp:latest",
        f"{instance}-platform-mcp:latest",
        f"{instance}-isu:latest",
    ]
    for img in images:
        result = subprocess.run(["docker", "rmi", img], capture_output=True, text=True)
        if result.returncode == 0:
            ok(f"Removed image {img}")

    # Unregister from clients ONLY if this install registered them
    # (avoids wiping registrations belonging to a different install with the same server name).
    tasks_name = env.get("NIWA_TASKS_SERVER_NAME", "niwa")
    if env.get("NIWA_REGISTERED_CLAUDE") == "1" and which("claude"):
        result = subprocess.run(
            ["claude", "mcp", "remove", tasks_name],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            ok(f"Unregistered '{tasks_name}' from Claude Code")
        else:
            warn(f"Could not unregister from Claude Code: {result.stderr.strip()}")
    if env.get("NIWA_REGISTERED_OPENCLAW") == "1" and which("openclaw"):
        result = subprocess.run(
            ["openclaw", "mcp", "unset", tasks_name],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            ok(f"Unregistered '{tasks_name}' from OpenClaw")
        else:
            warn(f"Could not unregister from OpenClaw: {result.stderr.strip()}")

    # Delete install dir
    if args.keep_data:
        info(f"Keeping data dir at {install_dir} (--keep-data flag)")
    else:
        shutil.rmtree(install_dir)
        ok(f"Removed {install_dir}")

    print()
    ok("Niwa uninstalled")


def cmd_restart(args) -> None:
    install_dir = _find_install_dir(args.dir)
    if not install_dir:
        err("No niwa install found.")
        sys.exit(1)
    info("Restarting all containers...")
    result = subprocess.run(
        ["docker", "compose", "-f", str(install_dir / "docker-compose.yml"), "restart"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        ok("Restarted")
    else:
        err(f"Restart failed: {result.stderr}")
        sys.exit(1)


def cmd_logs(args) -> None:
    install_dir = _find_install_dir(args.dir)
    if not install_dir:
        err("No niwa install found.")
        sys.exit(1)
    env = _read_env_file(install_dir / "secrets" / "mcp.env")
    instance = env.get("INSTANCE_NAME", "niwa")
    role = args.service or "mcp-gateway"
    container = f"{instance}-{role}"
    info(f"Showing last {args.tail} lines of {container} (Ctrl+C to exit)...")
    try:
        subprocess.run(["docker", "logs", "--tail", str(args.tail), "-f", container])
    except KeyboardInterrupt:
        pass


def main():
    parser = argparse.ArgumentParser(description="Niwa installer and CLI")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("install", help="Interactive install (default)")

    p_status = sub.add_parser("status", help="Show status of an existing install")
    p_status.add_argument("--dir", help="Install location (auto-detect by default)")

    p_uninstall = sub.add_parser("uninstall", help="Tear down an existing install")
    p_uninstall.add_argument("--dir", help="Install location (auto-detect by default)")
    p_uninstall.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    p_uninstall.add_argument("--keep-data", action="store_true",
                             help="Keep the install dir (DB, logs, configs) — only stop containers")

    p_restart = sub.add_parser("restart", help="Restart all containers")
    p_restart.add_argument("--dir", help="Install location (auto-detect by default)")

    p_logs = sub.add_parser("logs", help="Tail logs from a container")
    p_logs.add_argument("service", nargs="?", help="Service name (default: mcp-gateway)")
    p_logs.add_argument("--dir", help="Install location (auto-detect by default)")
    p_logs.add_argument("--tail", type=int, default=50, help="Lines to tail (default 50)")

    args = parser.parse_args()
    cmd = args.cmd or "install"
    if cmd == "install":
        cmd_install(args)
    elif cmd == "status":
        cmd_status(args)
    elif cmd == "uninstall":
        cmd_uninstall(args)
    elif cmd == "restart":
        cmd_restart(args)
    elif cmd == "logs":
        cmd_logs(args)


if __name__ == "__main__":
    main()
