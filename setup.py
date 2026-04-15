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

NIWA_VERSION = "0.1.0"

# Docker image pin for the MCP gateway (PR-11, 2026-04).
# See docs/DECISIONS-LOG.md for rationale. Override at install time with
#   NIWA_MCP_GATEWAY_IMAGE=docker/mcp-gateway:<tag> ./niwa install ...
NIWA_MCP_GATEWAY_IMAGE_DEFAULT = "docker/mcp-gateway:v0.40.4"

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


# ────────────────────────── install hints ──────────────────────────
# When a dependency is missing we don't auto-install it (sudo, multi-distro,
# version pinning are all hard). We do print the exact command to install it
# on the user's platform so they can copy-paste.

def _platform_key() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "other"


INSTALL_HINTS: dict[str, dict[str, list[str]]] = {
    "docker": {
        "macos": [
            "brew install orbstack            # recommended for macOS",
            "# or: brew install --cask docker (Docker Desktop)",
            "# or: brew install colima docker-cli",
        ],
        "linux": [
            "curl -fsSL https://get.docker.com | sh    # universal",
            "# or (Debian/Ubuntu): sudo apt install docker.io",
            "# or (Fedora):        sudo dnf install docker-ce",
            "# or (Arch):          sudo pacman -S docker",
            "# Then: sudo systemctl enable --now docker && sudo usermod -aG docker $USER",
        ],
        "other": ["See https://docs.docker.com/engine/install/"],
    },
    "python3": {
        "macos": ["brew install python@3.12"],
        "linux": [
            "sudo apt install python3.12       # Debian/Ubuntu",
            "# or: sudo dnf install python3.12  # Fedora",
            "# or: sudo pacman -S python        # Arch",
        ],
        "other": ["See https://www.python.org/downloads/"],
    },
    "claude": {
        "macos": [
            "npm install -g @anthropic-ai/claude-code   # requires Node 18+",
            "# Then: claude   (interactive auth on first run)",
        ],
        "linux": [
            "npm install -g @anthropic-ai/claude-code",
            "# Then: claude   (interactive auth on first run)",
        ],
        "other": ["See https://docs.claude.com/en/docs/claude-code"],
    },
    "llm": {
        "macos": [
            "brew install llm                  # Simon Willison's CLI",
            "# Then: llm keys set openai      (or other provider)",
        ],
        "linux": [
            "pipx install llm",
            "# or: pip install --user llm",
            "# Then: llm keys set openai",
        ],
        "other": ["See https://llm.datasette.io/en/stable/setup.html"],
    },
    "gemini": {
        "macos": ["See https://ai.google.dev/gemini-api/docs/quickstart for the Gemini CLI"],
        "linux": ["See https://ai.google.dev/gemini-api/docs/quickstart for the Gemini CLI"],
        "other": ["See https://ai.google.dev/gemini-api/docs/quickstart"],
    },
    "openclaw": {
        "macos": ["See https://docs.openclaw.ai/install (optional)"],
        "linux": ["See https://docs.openclaw.ai/install (optional)"],
        "other": ["See https://docs.openclaw.ai/install (optional)"],
    },
    "cloudflared": {
        "macos": [
            "brew install cloudflared",
            "cloudflared login",
            "cloudflared tunnel create niwa",
        ],
        "linux": [
            "# Debian/Ubuntu:",
            "wget -qO- https://pkg.cloudflare.com/cloudflare-main.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloudflare-main.gpg",
            "echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main' | sudo tee /etc/apt/sources.list.d/cloudflared.list",
            "sudo apt update && sudo apt install cloudflared",
            "cloudflared login",
            "cloudflared tunnel create niwa",
        ],
        "other": ["See https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"],
    },
}


def print_install_hint(tool: str) -> None:
    """Print install instructions for the user's platform."""
    plat = _platform_key()
    hint = INSTALL_HINTS.get(tool, {}).get(plat) or INSTALL_HINTS.get(tool, {}).get("other")
    if not hint:
        warn(f"  No install hint registered for '{tool}'. Search docs.")
        return
    print(f"  {DIM}Install hint:{RESET}")
    for line in hint:
        print(f"    {line}")


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
        Path.home() / ".orbstack" / "run" / "docker.sock",          # OrbStack (macOS)
        Path("/var/run/docker.sock"),                               # Docker Desktop / system
        Path.home() / ".colima" / "default" / "docker.sock",        # Colima
        Path.home() / ".docker" / "run" / "docker.sock",            # Docker Desktop newer / rootless
        Path(f"/run/user/{os.getuid()}/docker.sock"),               # Linux rootless Docker
        Path(f"/run/user/{os.getuid()}/podman/podman.sock"),        # Podman rootless
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


def _apply_sql_idempotent(conn, sql: str) -> None:
    """Apply a SQL script idempotently, emulating ADD COLUMN IF NOT EXISTS.

    SQLite does not support ``ALTER TABLE ADD COLUMN IF NOT EXISTS``, so on a
    fresh install (where schema.sql already defines the v0.2 columns in the
    ``tasks`` table) running migration 007 via ``conn.executescript`` fails
    with ``duplicate column name``. This helper parses the script into
    individual statements; for each ``ALTER TABLE ADD COLUMN`` it consults
    ``PRAGMA table_info`` and skips the statement when the column already
    exists. All other statements are executed directly.

    This must stay behaviourally equivalent to
    ``niwa-app/backend/app.py::_apply_sql_idempotent`` and the copy in
    ``tests/test_pr01_schema.py`` so that the installer bootstrap, the
    app-level migration runner, and the tests agree on migration semantics.
    The helper is duplicated here (instead of imported) because
    ``niwa-app/backend/app.py`` pulls in FastAPI and other heavy runtime
    deps that are not available inside the installer's Python environment.
    """
    lines: list[str] = []
    for line in sql.split('\n'):
        stripped = line.strip()
        if stripped.startswith('--') or not stripped:
            continue
        if ' --' in line:
            line = line[:line.index(' --')]
        lines.append(line)
    cleaned = '\n'.join(lines)

    for stmt in cleaned.split(';'):
        stmt = stmt.strip()
        if not stmt:
            continue
        # Skip explicit transaction-control statements. The Python sqlite3
        # driver opens an implicit transaction on DML, so a migration that
        # starts with ``BEGIN TRANSACTION`` (e.g. 008_state_machine_checks.sql)
        # errors out with "cannot start a transaction within a transaction"
        # when applied statement-by-statement. Atomicity is still guaranteed
        # by the caller's outer connection-level transaction (setup.py's
        # ``with sqlite3.connect(...) as conn`` block, or app.py's per-migration
        # ``c.commit()``), so dropping the inner BEGIN/COMMIT is safe.
        if re.match(
            r'(BEGIN|COMMIT|END|ROLLBACK)(\s+(TRANSACTION|WORK))?\s*$',
            stmt, re.IGNORECASE,
        ):
            continue
        m = re.match(
            r'ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)',
            stmt, re.IGNORECASE,
        )
        if m:
            table, column = m.group(1), m.group(2)
            existing = {r[1] for r in conn.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()}
            if column in existing:
                continue
        conn.execute(stmt)


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
    contract_file: Optional[str] = None,
    tasks_env: Optional[dict[str, str]] = None,
) -> str:
    """Generate the niwa-catalog.yaml content with the user's chosen server names.

    Tools for the tasks-mcp server are read from config/mcp-catalog/*.json
    (source of truth) instead of being hardcoded.

    If contract_file is given and exists, only expose tools listed in the contract.
    This is used when OpenClaw is enabled to limit the tool surface.
    For standalone Niwa (no OpenClaw), all 21 tools are exposed.
    """
    tasks_name = server_names["tasks"]
    notes_name = server_names["notes"]
    platform_name = server_names["platform"]
    fs_name = server_names["filesystem"]

    # Read tools list from config/mcp-catalog/*.json (source of truth)
    catalog_dir = REPO_ROOT / "config" / "mcp-catalog"
    tasks_tools: list[str] = []
    for catalog_file in sorted(catalog_dir.glob("*.json")):
        if catalog_file.name == "combined.json":
            continue
        with open(catalog_file) as _f:
            data = json.load(_f)
            tasks_tools.extend(data.get("tools", []))

    # If a contract is specified, the contract's tools list becomes the
    # authoritative advertised surface. PR-09's v02-assistant tools
    # (assistant_turn, task_cancel, …) live only in
    # servers/tasks-mcp/server.py::_V02_TOOL_DEFS, not in the v0.1
    # catalog JSONs. Intersecting with tasks_tools would drop them.
    # The server-side filter (NIWA_MCP_CONTRACT env) guarantees the
    # tasks-mcp container actually implements only these tools.
    if contract_file and Path(contract_file).exists():
        contract = json.loads(Path(contract_file).read_text())
        contract_tools = contract.get("tools", [])
        if contract_tools:
            tasks_tools = list(contract_tools)

    tools_yaml = "\n".join(f'      - name: "{t}"' for t in tasks_tools)

    # PR-11: optional env block for the tasks-mcp container. In assistant
    # mode this carries NIWA_MCP_CONTRACT, NIWA_MCP_SERVER_TOKEN and
    # NIWA_APP_URL so the server-side contract filter and the HTTP proxy
    # auth work inside the ephemeral container.
    if tasks_env:
        tasks_env_block = "    env:\n" + "\n".join(
            f'      - name: "{k}"\n        value: "{v}"'
            for k, v in tasks_env.items()
        ) + "\n"
    else:
        tasks_env_block = ""

    return f"""version: 2
name: {instance_name}
displayName: {instance_name.capitalize()} local catalog
registry:
  {tasks_name}:
    description: "Read+write access to tasks/projects DB"
    title: "{tasks_name.capitalize()}"
    type: "server"
    image: "{instance_name}-tasks-mcp:{NIWA_VERSION}"
    tools:
{tools_yaml}
    volumes:
      - "{db_path}:/data/niwa.sqlite3"
{tasks_env_block}    metadata:
      category: "{instance_name}"
      tags: [{tasks_name}, tasks]

  {notes_name}:
    description: "Personal notes (typed) and inbox"
    title: "{notes_name.capitalize()}"
    type: "server"
    image: "{instance_name}-notes-mcp:{NIWA_VERSION}"
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
      - "{db_path}:/data/niwa.sqlite3"
    metadata:
      category: "{instance_name}"
      tags: [{notes_name}, notes]

  {platform_name}:
    description: "Container ops (list, logs, health, restart)"
    title: "{platform_name.capitalize()}"
    type: "server"
    image: "{instance_name}-platform-mcp:{NIWA_VERSION}"
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
    image: "mcp/filesystem:2025.1"
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
            "tasks": "tasks",
            "notes": "notes",
            "platform": "platform",
            "filesystem": "filesystem",
        }
        self.gateway_streaming_port: int = 18810
        self.gateway_sse_port: int = 18812
        self.caddy_port: int = 18811
        self.app_port: int = 8080
        self.terminal_port: int = 7681
        self.bind_host: str = "127.0.0.1"
        self.tokens: dict[str, str] = {}
        self.username: str = "arturo"
        self.password: str = ""
        self.register_claude: bool = False
        self.register_openclaw: bool = False
        self.mode: str = "local-only"  # or "remote"
        self.public_domain: str = ""
        self.cloudflared_tunnel_id: str = ""
        self.cloudflared_config_path: Path = Path.home() / ".cloudflared" / "config.yml"
        self.executor_enabled: bool = True
        self.llm_provider: str = ""
        self.llm_command: str = ""
        self.projects: list[dict] = []  # [{name, slug, directory}, ...]
        self.telegram_bot_token: str = ""
        self.telegram_chat_id: str = ""
        self.webhook_url: str = ""
        # PR-11: quick install bookkeeping. Not part of the interactive
        # wizard; populated only by the --quick path.
        self.quick_mode: str = ""  # "" | "core" | "assistant"
        self.mcp_contract: str = ""  # e.g. "v02-assistant"
        self.mcp_server_token: str = ""  # service-to-service bearer for tasks-mcp


# ────────────────────────── LLM provider catalog ──────────────────────────
LLM_PROVIDERS = {
    "claude": {
        "label": "Claude (Anthropic claude CLI)",
        "binary": "claude",
        "command": "claude -p --max-turns 50 --output-format text",
        "auth_hint": "Run 'claude' once to authenticate before installing Niwa",
    },
    "llm": {
        "label": "llm CLI (Simon Willison) — supports OpenAI, Anthropic, Gemini via plugins",
        "binary": "llm",
        "command": "llm -m gpt-4 --no-stream",
        "auth_hint": "Set OPENAI_API_KEY (or run 'llm keys set openai') before running tasks",
    },
    "gemini": {
        "label": "Gemini CLI (Google)",
        "binary": "gemini",
        "command": "gemini chat --model gemini-1.5-pro",
        "auth_hint": "Run 'gemini auth' to authenticate before installing Niwa",
    },
    "custom": {
        "label": "Custom command (you provide)",
        "binary": None,
        "command": "",
        "auth_hint": "You're on your own — make sure the command works in your shell",
    },
}


def step_detection(cfg: WizardConfig) -> None:
    header("Step 0 — Pre-flight detection")
    docker = detect_docker()
    if not docker.get("available"):
        err("Docker is not installed or not in PATH.")
        print_install_hint("docker")
        print()
        print("  After installing, re-run ./niwa install")
        sys.exit(1)
    ok(f"Docker: {docker['version']} ({docker.get('runtime', 'unknown')})")

    sock = detect_socket_path()
    if not sock:
        err("Could not find a Docker socket. Looked at ~/.orbstack, /var/run, ~/.colima, ~/.docker, /run/user/<uid>.")
        print("  If your Docker is rootless, make sure the daemon is running and DOCKER_HOST is set.")
        sys.exit(1)
    ok(f"Docker socket: {sock}")
    cfg.detected["docker_socket"] = sock

    if sys.version_info < (3, 9):
        err(f"Python 3.9+ required, you have {sys.version_info.major}.{sys.version_info.minor}")
        print_install_hint("python3")
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
        info("No optional integrations detected (OpenClaw, Claude Code, cloudflared)")
        info("That's fine — Niwa works without them. Later wizard steps will print")
        info("install instructions if you want to enable any of them.")


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
            "Tasks server name", default="tasks", validator=valid_server_name
        )
        cfg.server_names["notes"] = prompt(
            "Notes server name", default="notes", validator=valid_server_name
        )
        cfg.server_names["platform"] = prompt(
            "Platform server name", default="platform", validator=valid_server_name
        )
        cfg.server_names["filesystem"] = prompt(
            "Filesystem server name", default="filesystem", validator=valid_server_name
        )


def step_database(cfg: WizardConfig) -> None:
    header("Step 2 — Database")
    print("Niwa needs a SQLite database with the Niwa schema (tasks, projects, notes, etc.).")
    choice = prompt_choice(
        "Database source:",
        ["Create a fresh empty database (recommended for new installs)",
         "Use an existing database"],
        default=0,
    )
    if choice == 0:
        cfg.db_mode = "fresh"
        cfg.db_path = cfg.niwa_home / "data" / "niwa.sqlite3"
        info(f"Will create a fresh DB at {cfg.db_path}")
    else:
        cfg.db_mode = "existing"
        existing = prompt("Path to existing niwa.sqlite3", validator=valid_path)
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
    header("Step 6 — Niwa app login")
    print("Set credentials for the Niwa app web UI (you'll log in with these in the browser).")
    cfg.username = prompt("Username", default="admin")
    cfg.password = prompt("Password (visible — write it down or pick something temporary)")


def step_ports(cfg: WizardConfig) -> None:
    header("Step 7 — Ports")
    cfg.bind_host = "127.0.0.1"
    if prompt_bool("Is this a remote server/VPS (bind ports to all interfaces for external access)?", default=False):
        cfg.bind_host = "0.0.0.0"
        info("Ports will be accessible from outside. Make sure the app has a strong password.")
    else:
        print("All ports are bound to 127.0.0.1 (loopback only).")
    defaults = [
        ("Gateway streaming HTTP", "gateway_streaming_port", 18810),
        ("Gateway SSE legacy", "gateway_sse_port", 18812),
        ("Caddy reverse proxy", "caddy_port", 18811),
        ("Niwa app web UI", "app_port", 8080),
        ("Web terminal", "terminal_port", 7681),
    ]
    for label, attr, default in defaults:
        # Auto-find a free port if default is in use
        actual_default = default
        if not detect_port_free(default):
            # Try incrementing until we find a free one
            for offset in range(1, 100):
                candidate = default + offset
                if detect_port_free(candidate):
                    actual_default = candidate
                    info(f"Puerto {default} en uso — usando {candidate} automáticamente")
                    break
        in_use = not detect_port_free(actual_default)
        suffix = f" {YELLOW}(in use!){RESET}" if in_use else ""
        while True:
            answer = prompt(f"{label} port{suffix}", default=str(actual_default), validator=valid_port)
            n = int(answer)
            if not detect_port_free(n):
                if n == actual_default and not prompt_bool(
                    f"  Port {n} appears to be in use. Continue anyway?", default=False
                ):
                    continue
                if n != default:
                    warn(f"  Port {n} appears to be in use. Pick another.")
                    continue
            setattr(cfg, attr, n)
            break


def _auto_install_nodejs_linux() -> bool:
    """Try to install Node.js on Linux. Returns True if successful."""
    if which("node"):
        return True
    info("Node.js not found — installing automatically...")
    try:
        r = subprocess.run(["apt-get", "update", "-qq"], capture_output=True, timeout=60)
        r = subprocess.run(["apt-get", "install", "-y", "-qq", "nodejs", "npm"],
                           capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and which("node"):
            ok(f"Installed Node.js {subprocess.run(['node', '--version'], capture_output=True, text=True).stdout.strip()}")
            return True
    except Exception as e:
        warn(f"Auto-install failed: {e}")
    return False


def _auto_install_claude() -> bool:
    """Try to install Claude CLI via npm. Returns True if successful."""
    if which("claude"):
        return True
    if not which("npm"):
        warn("npm not found — cannot install Claude CLI automatically")
        return False
    info("Installing Claude CLI...")
    try:
        r = subprocess.run(["npm", "install", "-g", "@anthropic-ai/claude-code"],
                           capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and which("claude"):
            version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
            ok(f"Installed Claude CLI {version}")
            return True
        warn(f"npm install failed: {r.stderr[:200]}")
    except Exception as e:
        warn(f"Auto-install failed: {e}")
    return False


def _auto_install_openclaw() -> bool:
    """Try to install OpenClaw via npm. Returns True if successful."""
    if which("openclaw"):
        return True
    if not which("npm"):
        warn("npm not found — cannot install OpenClaw automatically")
        return False
    info("Installing OpenClaw...")
    try:
        env = os.environ.copy()
        env["SHARP_IGNORE_GLOBAL_LIBVIPS"] = "1"  # Avoid libvips build issues
        r = subprocess.run(["npm", "install", "-g", "openclaw@latest"],
                           capture_output=True, text=True, timeout=180, env=env)
        if r.returncode == 0 and which("openclaw"):
            version = subprocess.run(["openclaw", "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
            ok(f"Installed OpenClaw {version}")
            return True
        warn(f"npm install failed: {r.stderr[:200]}")
    except Exception as e:
        warn(f"Auto-install failed: {e}")
    return False


def _get_local_ip() -> str:
    """Get the local LAN IP address for non-loopback binds."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _configure_openclaw_mcp(cfg) -> None:
    """Full OpenClaw auto-configuration: MCP server + skill + agent config."""
    if not which("openclaw"):
        return

    gateway_port = getattr(cfg, 'gateway_streaming_port', 28810)
    gateway_token = cfg.tokens.get('MCP_GATEWAY_AUTH_TOKEN', '')
    bind_host = getattr(cfg, 'bind_host', '127.0.0.1')

    # Use the LAN IP if bound to all interfaces
    if bind_host == '0.0.0.0':
        host = _get_local_ip()
    else:
        host = bind_host

    gateway_url = f"http://{host}:{gateway_port}/mcp"

    # Step 1: Register MCP server
    mcp_config = json.dumps({
        "url": gateway_url,
        "transport": "streamable-http",
        "headers": {"Authorization": f"Bearer {gateway_token}"} if gateway_token else {},
    })

    info("Registering Niwa MCP server in OpenClaw...")
    try:
        r = subprocess.run(
            ["openclaw", "mcp", "set", "niwa", mcp_config],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            ok("MCP server registered: niwa")
        else:
            warn(f"MCP registration failed: {r.stderr[:200]}")
            _print_openclaw_manual_instructions(gateway_url, gateway_token)
            return
    except Exception as e:
        warn(f"MCP config failed: {e}")
        _print_openclaw_manual_instructions(gateway_url, gateway_token)
        return

    # Step 2: Install Niwa skill
    skill_src = Path(__file__).parent / "config" / "openclaw" / "niwa-skill.md"
    if skill_src.is_file():
        openclaw_config = Path.home() / ".config" / "openclaw"
        if not openclaw_config.exists():
            openclaw_config = Path.home() / ".openclaw"

        skills_dir = openclaw_config / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)

        shutil.copy2(str(skill_src), str(skills_dir / "niwa.md"))
        ok("Niwa skill installed for OpenClaw")

    # Step 3: Add Niwa MCP to openclaw.json
    openclaw_json = Path.home() / ".config" / "openclaw" / "openclaw.json"
    if not openclaw_json.exists():
        openclaw_json = Path.home() / ".openclaw" / "openclaw.json"

    if openclaw_json.exists():
        try:
            config = json.loads(openclaw_json.read_text())
        except Exception:
            config = {}
    else:
        config = {}
        openclaw_json.parent.mkdir(parents=True, exist_ok=True)

    if "mcpServers" not in config:
        config["mcpServers"] = {}

    config["mcpServers"]["niwa"] = {
        "url": gateway_url,
        "transport": "streamable-http",
        "headers": {"Authorization": f"Bearer {gateway_token}"} if gateway_token else {},
    }

    openclaw_json.write_text(json.dumps(config, indent=2) + "\n")
    ok("Updated openclaw.json with Niwa MCP server")

    # Step 4: Verify connection
    info("Verifying OpenClaw \u2192 Niwa connection...")
    try:
        r = subprocess.run(
            ["openclaw", "mcp", "list"],
            capture_output=True, text=True, timeout=30,
        )
        if "niwa" in r.stdout.lower():
            niwa_lines = [l for l in r.stdout.split('\n') if 'niwa' in l.lower()]
            ok(f"Connection verified: {len(niwa_lines)} Niwa tools visible to OpenClaw")
        else:
            warn("Niwa tools not yet visible. Run 'openclaw mcp list' after restarting OpenClaw gateway.")
    except Exception:
        info("Run 'openclaw mcp list' to verify after the gateway starts.")

    # Step 5: Print summary
    print()
    ok("OpenClaw \u2194 Niwa integration complete:")
    print(f"    Gateway:   {gateway_url}")
    print(f"    Server:    niwa (13 tools via contract)")
    print(f"    Skill:     niwa.md installed")
    print(f"    Transport: streamable-http")
    print()
    info("Try: openclaw 'list my tasks'")
    info("Or from Telegram/Discord: 'create a task to review the homepage'")


def _print_openclaw_manual_instructions(gateway_url: str, gateway_token: str) -> None:
    """Fallback: print manual OpenClaw setup instructions."""
    mcp_config = json.dumps({
        "url": gateway_url,
        "transport": "streamable-http",
        "headers": {"Authorization": f"Bearer {gateway_token}"} if gateway_token else {},
    })
    print()
    info("To connect manually:")
    print(f"  openclaw mcp set niwa '{mcp_config}'")
    print(f"  openclaw gateway restart")
    print()


def step_executor(cfg: WizardConfig) -> None:
    header("Step 8 — Autonomous task execution")
    print("The executor is a background worker that picks up tasks marked 'pendiente',")
    print("runs them via an LLM CLI (Claude, GPT, Gemini), and updates the status.")
    print()
    if not prompt_bool("Enable autonomous task execution?", default=True):
        cfg.executor_enabled = False
        return
    cfg.executor_enabled = True
    options = list(LLM_PROVIDERS.keys())
    labels = [LLM_PROVIDERS[k]["label"] for k in options]
    choice = prompt_choice("LLM provider:", labels, default=0)
    cfg.llm_provider = options[choice]
    provider = LLM_PROVIDERS[cfg.llm_provider]
    if cfg.llm_provider == "custom":
        cfg.llm_command = prompt("Custom command (the prompt is appended as last arg)")
    else:
        binary = provider["binary"]
        if binary and not which(binary):
            installed = False
            # Auto-install on Linux
            if _platform_key() == "linux" and cfg.llm_provider == "claude":
                _auto_install_nodejs_linux()
                installed = _auto_install_claude()
            if not installed:
                warn(f"'{binary}' not found in PATH.")
                print_install_hint(binary)
                warn(f"You can install it later from the web terminal in Niwa.")
                if not prompt_bool("Continue anyway?", default=True):
                    cfg.executor_enabled = False
                    return
        cfg.llm_command = provider["command"]
        # Add --dangerously-skip-permissions for non-root executor on Linux
        if cfg.llm_provider == "claude" and _platform_key() == "linux" and os.getuid() == 0:
            cfg.llm_command += " --dangerously-skip-permissions"
            info("Added --dangerously-skip-permissions (executor will run as non-root 'niwa' user)")
        info(f"LLM command: {cfg.llm_command}")
        info(f"Auth hint:   {provider['auth_hint']}")


def step_projects(cfg: WizardConfig) -> None:
    header("Step 9 — Register projects (optional)")
    print("Niwa tracks tasks per project. The executor uses each project's")
    print("'directory' field to know where to run the LLM commands.")
    print("You can register projects now or add them later via the Niwa app web UI.")
    print()
    if not prompt_bool("Register a project now?", default=False):
        return
    while True:
        name = prompt("Project name", default="my-project")
        slug_default = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "project"
        slug = prompt(
            "Project slug (lowercase, used in IDs)",
            default=slug_default,
            validator=lambda v: None if re.fullmatch(r"[a-z][a-z0-9-]{0,30}", v) else "lowercase letters, digits, hyphens; start with a letter",
        )
        directory = prompt(
            "Project directory (absolute path, must exist)",
            validator=lambda v: None if Path(v).expanduser().is_dir() else "directory not found",
        )
        cfg.projects.append({
            "name": name,
            "slug": slug,
            "directory": str(Path(directory).expanduser().resolve()),
        })
        ok(f"Will register '{name}' at {cfg.projects[-1]['directory']}")
        if not prompt_bool("Add another project?", default=False):
            break


def step_remote(cfg: WizardConfig) -> None:
    header("Step 10 — Public exposure (optional)")
    print("By default, Niwa is local-only (loopback). To access from outside (mobile,")
    print("ChatGPT, n8n in another machine), you can opt in to remote exposure via")
    print("Cloudflare Tunnel + Caddy bearer auth.")
    print()
    if not prompt_bool("Enable remote access via Cloudflare Tunnel?", default=False):
        cfg.mode = "local-only"
        return

    if not cfg.detected.get("cloudflared"):
        warn("cloudflared is NOT installed.")
        print_install_hint("cloudflared")
        print()
        print("  Or skip remote for now and run './niwa install' again later")
        if not prompt_bool("Continue with remote setup anyway?", default=False):
            cfg.mode = "local-only"
            return
    else:
        # Cloudflared is installed — verify it's logged in
        cf_problem = _check_cloudflared_authenticated()
        if cf_problem:
            warn(cf_problem)
            if not prompt_bool("Continue anyway? (the wizard will skip the tunnel reload)", default=False):
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


def step_notifications(cfg: WizardConfig) -> None:
    header("Step 11 — Notifications (optional)")
    print("Niwa routines can send notifications when they run. Currently supported:")
    print("  - Telegram Bot API")
    print("  - Generic webhook (POST JSON)")
    print()
    if prompt_bool("Configure Telegram notifications?", default=False):
        cfg.telegram_bot_token = prompt("Telegram bot token (from @BotFather)")
        cfg.telegram_chat_id = prompt("Telegram chat ID (your user or group ID)")
        ok(f"Telegram: bot token set, chat ID = {cfg.telegram_chat_id}")
        print()
    if prompt_bool("Configure a generic webhook URL?", default=False):
        cfg.webhook_url = prompt("Webhook URL (receives POST with {text, source})")
        ok(f"Webhook: {cfg.webhook_url}")
    print()


def _check_claude_authenticated() -> Optional[str]:
    """Returns None if claude is auth'd, else a message describing what's missing."""
    # ~/.claude.json exists when claude is configured at all
    config = Path.home() / ".claude.json"
    if not config.exists():
        return "Claude Code is installed but not configured. Run 'claude' once interactively before installing Niwa so it can register the MCP server."
    return None


def _check_cloudflared_authenticated() -> Optional[str]:
    """Returns None if cloudflared has cert/credentials, else a message."""
    cert = Path.home() / ".cloudflared" / "cert.pem"
    if not cert.exists():
        return "cloudflared is installed but not logged in. Run 'cloudflared login' interactively (it opens a browser) before continuing."
    return None


def step_clients(cfg: WizardConfig) -> None:
    header("Step 12 — Auto-register MCP clients")
    
    # --- Claude CLI ---
    if not cfg.detected["claude"]:
        if _platform_key() == "linux" and which("npm"):
            if prompt_bool("Claude CLI no detectado. ¿Instalar automáticamente?", default=True):
                _auto_install_nodejs_linux()
                if _auto_install_claude():
                    cfg.detected["claude"] = True
    if cfg.detected["claude"]:
        claude_problem = _check_claude_authenticated()
        if claude_problem:
            warn(claude_problem)
            cfg.register_claude = prompt_bool(
                "Try to register anyway?", default=False
            )
        else:
            cfg.register_claude = prompt_bool(
                "Register Niwa with Claude Code (user scope, claude mcp add)?", default=True
            )
    
    # --- OpenClaw ---
    if not cfg.detected["openclaw"]:
        print()
        info("OpenClaw es un orquestador multi-canal y multi-modelo.")
        info("Con OpenClaw, puedes usar Niwa desde Telegram, WhatsApp, Slack, Discord y terminal.")
        info("OpenClaw actúa como cerebro y usa las tools de Niwa via MCP.")
        if prompt_bool("¿Instalar OpenClaw? (opcional, recomendado)", default=True):
            _auto_install_nodejs_linux() if _platform_key() == "linux" else None
            if _auto_install_openclaw():
                cfg.detected["openclaw"] = True
                info("OpenClaw instalado. Se configurará automáticamente para usar Niwa.")
            else:
                warn("No se pudo instalar OpenClaw. Puedes instalarlo manualmente después:")
                info("  curl -fsSL https://openclaw.ai/install.sh | bash")
    if cfg.detected["openclaw"]:
        cfg.register_openclaw = prompt_bool(
            "Register Niwa with OpenClaw (openclaw mcp set)?", default=True
        )
    
    if not cfg.detected["claude"] and not cfg.detected["openclaw"]:
        info("No MCP clients detected to register. You can wire any client manually using:")
        info(f"  Streaming HTTP: http://localhost:{cfg.gateway_streaming_port}/mcp")
        info(f"  SSE legacy:     http://localhost:{cfg.gateway_sse_port}/sse")


def step_summary(cfg: WizardConfig) -> bool:
    header("Step 13 — Summary")
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
          f"sse={cfg.gateway_sse_port}, caddy={cfg.caddy_port}, app={cfg.app_port}")
    print(f"  Tokens:             auto-generated, stored in niwa.env (chmod 600)")
    print(f"  App login:          {cfg.username}")
    print(f"  Mode:               {cfg.mode}")
    if cfg.mode == "remote":
        print(f"  Public domain:      {cfg.public_domain}")
        print(f"  Tunnel ID:          {cfg.cloudflared_tunnel_id or '(skip — manual config)'}")
    print(f"  Executor:           {'enabled' if cfg.executor_enabled else 'disabled'}")
    if cfg.executor_enabled:
        print(f"    Provider:         {cfg.llm_provider}")
        print(f"    Command:          {cfg.llm_command}")
    if cfg.projects:
        print(f"  Projects to register:")
        for p in cfg.projects:
            print(f"    - {p['name']} ({p['slug']}) → {p['directory']}")
    if cfg.telegram_bot_token:
        print(f"  Telegram:           chat_id={cfg.telegram_chat_id}")
    if cfg.webhook_url:
        print(f"  Webhook:            {cfg.webhook_url}")
    print(f"  Register Claude:    {cfg.register_claude}")
    print(f"  Register OpenClaw:  {cfg.register_openclaw}")
    print()
    return prompt_bool("Proceed with install?", default=True)


# ────────────────────────── execution ──────────────────────────
def execute_install(cfg: WizardConfig) -> None:
    import sqlite3
    header("Step 14 — Building install")
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
        "NIWA_VERSION": NIWA_VERSION,
        "NIWA_MODE": cfg.mode,
        "NIWA_PUBLIC_DOMAIN": cfg.public_domain,
        "NIWA_CLOUDFLARE_TUNNEL_ID": cfg.cloudflared_tunnel_id,
        "INSTANCE_NAME": cfg.instance_name,
        "NIWA_HOME": str(cfg.niwa_home),
        "NIWA_LOGS_DIR": str(cfg.niwa_home / "logs"),
        "NIWA_SECRETS_DIR": str(cfg.niwa_home / "secrets"),
        "NIWA_DB_PATH": str(cfg.db_path),
        "NIWA_DATA_DIR": str(cfg.db_path.parent),
        "NIWA_FILESYSTEM_WORKSPACE": str(cfg.fs_workspace),
        "NIWA_FILESYSTEM_MEMORY": str(cfg.fs_memory),
        "NIWA_GATEWAY_STREAMING_PORT": str(cfg.gateway_streaming_port),
        "NIWA_GATEWAY_SSE_PORT": str(cfg.gateway_sse_port),
        "NIWA_CADDY_PORT": str(cfg.caddy_port),
        "NIWA_APP_PORT": str(cfg.app_port),
        "NIWA_TERMINAL_PORT": str(cfg.terminal_port),
        "NIWA_BIND_HOST": cfg.bind_host,
        "NIWA_ENABLED_SERVERS": ",".join(cfg.server_names[k] for k in ("tasks", "notes", "platform", "filesystem")),
        "NIWA_MCP_GATEWAY_IMAGE": os.environ.get("NIWA_MCP_GATEWAY_IMAGE", NIWA_MCP_GATEWAY_IMAGE_DEFAULT),
        "NIWA_TASKS_SERVER_NAME": cfg.server_names["tasks"],
        "NIWA_NOTES_SERVER_NAME": cfg.server_names["notes"],
        "NIWA_PLATFORM_SERVER_NAME": cfg.server_names["platform"],
        "NIWA_FILESYSTEM_SERVER_NAME": cfg.server_names["filesystem"],
        "MCP_GATEWAY_AUTH_TOKEN": cfg.tokens["MCP_GATEWAY_AUTH_TOKEN"],
        "NIWA_LOCAL_TOKEN": cfg.tokens["NIWA_LOCAL_TOKEN"],
        "NIWA_REMOTE_TOKEN": cfg.tokens["NIWA_REMOTE_TOKEN"],
        "PLATFORM_RESTART_WHITELIST": ",".join(cfg.restart_whitelist),
        "NIWA_APP_USERNAME": cfg.username,
        "NIWA_APP_PASSWORD": cfg.password,
        "NIWA_APP_SESSION_SECRET": generate_token(),
        "NIWA_APP_PUBLIC_BASE_URL": f"http://{'0.0.0.0' if cfg.bind_host == '0.0.0.0' else 'localhost'}:{cfg.app_port}",
        "NIWA_APP_AUTH_REQUIRED": "1",
        "NIWA_REGISTERED_CLAUDE": "1" if cfg.register_claude else "0",
        "NIWA_REGISTERED_OPENCLAW": "1" if cfg.register_openclaw else "0",
        "NIWA_EXECUTOR_ENABLED": "1" if cfg.executor_enabled else "0",
        "NIWA_LLM_PROVIDER": cfg.llm_provider,
        "NIWA_LLM_COMMAND": cfg.llm_command,
        "DOCKER_SOCKET_PATH": cfg.detected.get("docker_socket", "/var/run/docker.sock"),
        "NIWA_TELEGRAM_BOT_TOKEN": cfg.telegram_bot_token,
        "NIWA_TELEGRAM_CHAT_ID": cfg.telegram_chat_id,
        "NIWA_WEBHOOK_URL": cfg.webhook_url,
        # PR-11: assistant-mode MCP contract wiring. Empty in core mode
        # (the app's is_authenticated() falls back to cookie auth and
        # servers/tasks-mcp/server.py exposes the 21 legacy tools).
        "NIWA_MCP_CONTRACT": cfg.mcp_contract or "",
        "NIWA_MCP_SERVER_TOKEN": cfg.mcp_server_token or "",
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

    # Generate catalog yaml. PR-11: in assistant mode, filter the
    # tasks-mcp surface via the v02-assistant contract and inject the
    # server-side env the tasks-mcp container needs.
    contract_file = None
    tasks_env = None
    if cfg.mcp_contract:
        contract_path = REPO_ROOT / "config" / "mcp-contract" / f"{cfg.mcp_contract}.json"
        if contract_path.is_file():
            contract_file = str(contract_path)
            tasks_env = {
                "NIWA_MCP_CONTRACT": cfg.mcp_contract,
                "NIWA_MCP_SERVER_TOKEN": cfg.mcp_server_token,
                "NIWA_APP_URL": f"http://{cfg.instance_name}-app:8080",
            }
        else:
            warn(f"Contract file not found: {contract_path} — "
                 f"falling back to unfiltered catalog")
    catalog = generate_catalog_yaml(
        cfg.server_names,
        str(cfg.db_path),
        str(cfg.fs_workspace),
        str(cfg.fs_memory),
        cfg.instance_name,
        contract_file=contract_file,
        tasks_env=tasks_env,
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
        info("Bootstrapping fresh database with Niwa schema...")
        schema_sql = (REPO_ROOT / "niwa-app" / "db" / "schema.sql").read_text()
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
            # Run all migrations on top of the base schema.
            #
            # Tables/indexes use CREATE ... IF NOT EXISTS, but SQLite does NOT
            # support ALTER TABLE ADD COLUMN IF NOT EXISTS — and migration 007
            # adds columns to `tasks` that schema.sql already creates, which
            # would blow up a fresh install with "duplicate column name".
            # _apply_sql_idempotent parses each statement and skips ALTER TABLE
            # ADD COLUMN when the column is already present, mirroring the
            # behaviour of niwa-app/backend/app.py::_run_migrations and the
            # test harness in tests/test_pr01_schema.py.
            migrations_dir = REPO_ROOT / "niwa-app" / "db" / "migrations"
            if migrations_dir.is_dir():
                import glob as _glob
                for mfile in sorted(_glob.glob(str(migrations_dir / "*.sql"))):
                    mig_sql = Path(mfile).read_text()
                    _apply_sql_idempotent(conn, mig_sql)

            # Track which migrations have been applied so `bin/niwa migrate`
            # won't re-run them.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                    filename TEXT
                )
            """)
            if migrations_dir.is_dir():
                for mfile in sorted(_glob.glob(str(migrations_dir / "*.sql"))):
                    fname = os.path.basename(mfile)
                    try:
                        ver = int(fname.split("_")[0])
                    except (ValueError, IndexError):
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO schema_version (version, filename) VALUES (?, ?)",
                        (ver, fname),
                    )
            conn.commit()
        ok(f"Fresh DB created at {cfg.db_path}")

    # Build images
    header("Step 14b — Building Docker images")
    images = [
        ("tasks-mcp", REPO_ROOT / "servers" / "tasks-mcp", f"{cfg.instance_name}-tasks-mcp:{NIWA_VERSION}"),
        ("notes-mcp", REPO_ROOT / "servers" / "notes-mcp", f"{cfg.instance_name}-notes-mcp:{NIWA_VERSION}"),
        ("platform-mcp", REPO_ROOT / "servers" / "platform-mcp", f"{cfg.instance_name}-platform-mcp:{NIWA_VERSION}"),
        ("niwa-app", REPO_ROOT / "niwa-app", f"{cfg.instance_name}-app:{NIWA_VERSION}"),
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
    subprocess.run(["docker", "pull", "mcp/filesystem:2025.1"], check=False, capture_output=True)
    ok("Pulled mcp/filesystem:2025.1")

    # docker compose up
    header("Step 14c — Starting the stack")
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
        if e.code in (400, 405, 406):
            ok(f"Gateway responding on port {cfg.gateway_streaming_port} (HTTP {e.code} expected for GET)")
        else:
            warn(f"Gateway returned HTTP {e.code} — check 'docker logs {cfg.instance_name}-mcp-gateway'")
    except Exception as e:
        warn(f"Gateway health check failed: {e}")
        warn(f"  Run: docker logs {cfg.instance_name}-mcp-gateway")

    # Niwa app healthcheck
    try:
        with urllib.request.urlopen(f"http://localhost:{cfg.app_port}/health", timeout=5) as r:
            if r.status == 200:
                ok(f"Niwa app responding on port {cfg.app_port}")
            else:
                warn(f"Niwa app returned HTTP {r.status}")
    except Exception as e:
        warn(f"Niwa app health check failed: {e}")
        warn(f"  Run: docker logs {cfg.instance_name}-app")

    # Caddy healthcheck (no auth needed for /health)
    try:
        with urllib.request.urlopen(f"http://localhost:{cfg.caddy_port}/health", timeout=5) as r:
            if r.status == 200:
                ok(f"Caddy responding on port {cfg.caddy_port}")
    except Exception as e:
        warn(f"Caddy health check failed: {e}")
        warn(f"  Run: docker logs {cfg.instance_name}-caddy")

    # Bootstrap projects table with the user's chosen projects
    if cfg.projects:
        info("Registering projects...")
        with sqlite3.connect(str(cfg.db_path)) as conn:
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            for p in cfg.projects:
                conn.execute(
                    "INSERT OR IGNORE INTO projects (id, slug, name, area, description, active, created_at, updated_at, directory) VALUES (?, ?, ?, 'proyecto', ?, 1, ?, ?, ?)",
                    (f"proj-{p['slug']}", p["slug"], p["name"], f"Project {p['name']}", ts, ts, p["directory"]),
                )
            conn.commit()
        ok(f"Registered {len(cfg.projects)} project(s)")

    # Install task executor (host-side launchd/systemd) if enabled
    if cfg.executor_enabled:
        install_task_executor(cfg)

    # Install hosting server (host-side, always — needed for deploy_web)
    install_hosting_server(cfg)

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
        _configure_openclaw_mcp(cfg)

    _post_install_smoke(cfg)
    print_summary(cfg)


def _post_install_smoke(cfg) -> None:
    """Quick smoke test after install."""
    import urllib.request

    info("Running post-install verification...")

    # Test 1: App responds
    try:
        url = f"http://localhost:{cfg.app_port}/api/version"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            ok(f"Niwa app: v{data.get('version', '?')} responding on port {cfg.app_port}")
    except Exception as e:
        warn(f"App not responding on port {cfg.app_port}: {e}")

    # Test 2: MCP gateway responds
    try:
        url = f"http://localhost:{cfg.gateway_streaming_port}/mcp"
        headers = {"Authorization": f"Bearer {cfg.tokens.get('MCP_GATEWAY_AUTH_TOKEN', '')}"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok(f"MCP gateway: responding on port {cfg.gateway_streaming_port}")
    except Exception as e:
        # Gateway might not respond to plain GET — that's OK if it returns 405 or similar
        if '405' in str(e) or '400' in str(e):
            ok(f"MCP gateway: responding on port {cfg.gateway_streaming_port}")
        else:
            warn(f"MCP gateway not responding: {e}")

    # Test 3: Database has tables
    try:
        import sqlite3 as _sqlite3
        db_path = cfg.niwa_home / "data" / "niwa.sqlite3"
        if db_path.exists():
            conn = _sqlite3.connect(str(db_path))
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            conn.close()
            ok(f"Database: {len(tables)} tables created")
        else:
            warn(f"Database not found at {db_path}")
    except Exception as e:
        warn(f"Database check failed: {e}")


def _get_local_ip() -> str:
    """Get the machine's LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def print_summary(cfg: WizardConfig) -> None:
    header("✅ Niwa is up")
    print()
    # Determine the right host to show in URLs
    if cfg.bind_host == "0.0.0.0":
        local_ip = _get_local_ip()
        host_display = local_ip
    else:
        host_display = "localhost"
    print(f"  {BOLD}Endpoints:{RESET}")
    print(f"    MCP (streaming HTTP):    http://{host_display}:{cfg.gateway_streaming_port}/mcp")
    print(f"    MCP (SSE legacy):        http://{host_display}:{cfg.gateway_sse_port}/sse")
    print(f"    Caddy reverse proxy:     http://{host_display}:{cfg.caddy_port}/mcp (bearer auth)")
    print(f"    Niwa app web UI:         http://{host_display}:{cfg.app_port}")
    if cfg.bind_host == "0.0.0.0":
        print(f"    También accesible en:    http://localhost:{cfg.app_port} (desde esta máquina)")
    if cfg.mode == "remote" and cfg.public_domain:
        print(f"    Público (remoto):        https://{cfg.public_domain}/mcp (bearer NIWA_REMOTE_TOKEN)")
    print()
    print(f"  {BOLD}Tokens:{RESET}")
    print(f"    Remote (for public/external clients): {cfg.tokens['NIWA_REMOTE_TOKEN'][:16]}...")
    print(f"    Full tokens are in: {cfg.niwa_home / 'secrets' / 'mcp.env'}")
    print()
    print(f"  {BOLD}MCP servers:{RESET} {', '.join(cfg.server_names.values())}")
    print()
    print(f"  {BOLD}Next steps:{RESET}")
    print(f"    - Open Niwa app:    open http://{host_display}:{cfg.app_port}")
    if cfg.register_claude:
        print(f"    - Test from Claude Code:  ask it to use the '{cfg.server_names['tasks']}' MCP")
    print(f"    - View logs:          docker logs {cfg.instance_name}-mcp-gateway")
    print(f"    - Stop:               docker compose -f {cfg.niwa_home / 'docker-compose.yml'} down")
    print(f"    - Restart:            docker compose -f {cfg.niwa_home / 'docker-compose.yml'} restart")
    print()


# ────────────────────────── subcommands ──────────────────────────
def install_task_executor(cfg: WizardConfig) -> None:
    """Copy task-executor.py to the install dir and register it as a launchd
    agent (macOS) or user systemd unit (Linux)."""
    info("Installing task executor...")
    bin_dir = cfg.niwa_home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    src = REPO_ROOT / "bin" / "task-executor.py"
    dest = bin_dir / "task-executor.py"
    shutil.copy(src, dest)
    dest.chmod(0o755)
    ok(f"Copied executor to {dest}")
    if sys.platform == "darwin":
        _install_launchd_agent(cfg, dest)
    elif sys.platform.startswith("linux"):
        _install_systemd_unit(cfg, dest)
    else:
        warn(f"Unknown platform {sys.platform} — executor copied but not registered as a service.")
        warn(f"Run it manually with: NIWA_HOME={cfg.niwa_home} python3 {dest}")


def _install_launchd_agent(cfg: WizardConfig, executor_path: Path) -> None:
    label = f"com.niwa.{cfg.instance_name}.executor"
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = cfg.niwa_home / "logs" / "executor.log"
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/env</string>
        <string>python3</string>
        <string>{executor_path}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>NIWA_HOME</key>
        <string>{cfg.niwa_home}</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
</dict>
</plist>
"""
    plist_path.write_text(plist)
    ok(f"Wrote launchd plist: {plist_path}")
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True, text=True)
    result = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        ok(f"Loaded launchd agent {label}")
    else:
        warn(f"launchctl bootstrap failed: {result.stderr.strip()[:300]}")
        warn(f"Load manually: launchctl bootstrap gui/{uid} {plist_path}")


def _wait_for_service_stable(
    unit_name: str,
    *,
    user_scope: bool = False,
    wait_seconds: int = 15,
    sleep=time.sleep,
    runner=subprocess.run,
):
    """Block for ``wait_seconds`` after ``systemctl enable --now`` and
    report whether the service settled into a healthy state.

    Returns ``(healthy, is_active, nrestarts, journal_tail)``.

    - ``healthy`` is True iff ``is-active == 'active'`` AND
      ``NRestarts == 0`` after the wait window.
    - ``journal_tail`` is populated only when ``healthy`` is False (last
      20 lines of ``journalctl -u <unit>``); on the happy path it is the
      empty string to keep output clean.

    ``sleep`` and ``runner`` are injection points for tests — both
    default to the real stdlib primitives in production.

    Regression guard for Bug 18b (docs/BUGS-FOUND.md): ``setup.py``
    reported "Enabled and started" immediately after ``systemctl enable
    --now`` without checking whether the service actually stayed up,
    which masked PR-23's crash-loop (executor.log root-owned) for hours.
    """
    scope_args = ["--user"] if user_scope else []
    sleep(wait_seconds)

    # is-active returns non-zero for non-active states. We want the
    # string value regardless, so don't `check=True` and read stdout.
    try:
        is_active_res = runner(
            ["systemctl", *scope_args, "is-active", unit_name],
            capture_output=True, text=True, timeout=10,
        )
        is_active = (is_active_res.stdout or "").strip() or "unknown"
    except Exception as exc:  # noqa: BLE001 — diagnostic path, don't mask
        is_active = f"error: {exc}"

    try:
        show_res = runner(
            ["systemctl", *scope_args, "show", unit_name,
             "--property=NRestarts", "--value"],
            capture_output=True, text=True, timeout=10,
        )
        raw = (show_res.stdout or "").strip()
        nrestarts = int(raw) if raw.isdigit() else 0
    except Exception:  # noqa: BLE001 — diagnostic path
        nrestarts = 0

    healthy = (is_active == "active") and (nrestarts == 0)

    journal_tail = ""
    if not healthy:
        try:
            j = runner(
                ["journalctl", *scope_args, "-u", unit_name,
                 "-n", "20", "--no-pager"],
                capture_output=True, text=True, timeout=5,
            )
            journal_tail = (j.stdout or "").strip() or "(journal empty)"
        except Exception:  # noqa: BLE001
            journal_tail = "(journal unavailable)"

    return healthy, is_active, nrestarts, journal_tail


def _verify_service_or_abort(
    unit_name: str,
    *,
    user_scope: bool = False,
    wait_seconds: int = 15,
    sleep=time.sleep,
    runner=subprocess.run,
) -> None:
    """Fail-loud wrapper around ``_wait_for_service_stable``.

    On healthy → prints a success line and returns. On unhealthy →
    dumps is-active, NRestarts, the journal tail, pointers to the
    relevant bugs and a manual unblock command, then ``sys.exit(1)``.

    This is the ``fail loud`` half of PR-25: any future regression of
    the Bug 18 / 19 family (executor crash-looping immediately after
    install) will now abort the install with a visible, actionable
    error instead of a silent "Enabled and started" lie.
    """
    healthy, is_active, nrestarts, journal_tail = _wait_for_service_stable(
        unit_name,
        user_scope=user_scope,
        wait_seconds=wait_seconds,
        sleep=sleep,
        runner=runner,
    )
    if healthy:
        ok(f"Service {unit_name} is stable "
           f"(is-active={is_active}, NRestarts={nrestarts})")
        return

    err(f"Service {unit_name} did not stabilise after {wait_seconds}s")
    err(f"  is-active:  {is_active}")
    err(f"  NRestarts:  {nrestarts}")
    err(f"  journal tail (last 20 lines):")
    for line in (journal_tail or "").splitlines():
        err(f"    {line}")
    err("")
    err("  Known causes (see docs/BUGS-FOUND.md):")
    err("    • Bug 18 — executor.log owned by root (fixed in PR-23).")
    err("      Manual unblock on an already-broken install:")
    err("        chown niwa:niwa /opt/<instance>/logs/executor.log")
    err("        chown niwa:niwa /opt/<instance>/logs/hosting.log")
    err("    • Bug 19 — executor passed prompt as path (fixed in PR-24).")
    err("")
    err("  Install aborted (fail-loud). Investigate, fix, then retry")
    err("  ./niwa install.")
    sys.exit(1)


def _reset_failed_unit(
    unit_name: str,
    *,
    user_scope: bool = False,
    runner=subprocess.run,
) -> None:
    """Best-effort ``systemctl reset-failed`` before enabling.

    On reinstall over a previously crash-looping unit, ``NRestarts`` is
    cumulative across the unit's lifetime and would cause the health
    check to false-positive even on a now-healthy service. Reset the
    counter first; ignore errors (unit may not exist yet)."""
    scope_args = ["--user"] if user_scope else []
    try:
        runner(
            ["systemctl", *scope_args, "reset-failed", unit_name],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:  # noqa: BLE001 — best-effort, pre-enable cleanup
        pass


def _install_systemd_unit(cfg: WizardConfig, executor_path: Path) -> None:
    """Install systemd unit for the executor. If running as root, creates a
    dedicated 'niwa' user (--dangerously-skip-permissions fails as root)."""
    import grp
    run_as_root = os.getuid() == 0
    niwa_user = "niwa" if run_as_root else None
    log_path = cfg.niwa_home / "logs" / "executor.log"

    if run_as_root:
        # Create niwa user if needed
        try:
            subprocess.run(["id", "niwa"], capture_output=True, check=True)
        except subprocess.CalledProcessError:
            subprocess.run(["useradd", "-m", "-s", "/bin/bash", "niwa"], check=True)
            ok("Created system user 'niwa' for the executor")
        # Setup niwa home with copies/links
        niwa_home = Path("/home/niwa") / f".{cfg.instance_name}"
        niwa_home.mkdir(parents=True, exist_ok=True)
        (niwa_home / "secrets").mkdir(parents=True, exist_ok=True)
        (niwa_home / "bin").mkdir(parents=True, exist_ok=True)
        shutil.copy(str(cfg.niwa_home / "secrets" / "mcp.env"), str(niwa_home / "secrets" / "mcp.env"))
        shutil.copy(str(executor_path), str(niwa_home / "bin" / "task-executor.py"))
        # Copy Claude credentials to niwa user so executor can authenticate
        claude_creds = Path.home() / ".claude"
        claude_json = Path.home() / ".claude.json"
        niwa_claude = Path("/home/niwa") / ".claude"
        niwa_claude_json = Path("/home/niwa") / ".claude.json"
        if claude_creds.is_dir() and not niwa_claude.exists():
            shutil.copytree(str(claude_creds), str(niwa_claude))
            subprocess.run(["chown", "-R", "niwa:niwa", str(niwa_claude)], capture_output=True)
            ok("Copied Claude credentials to niwa user")
        if claude_json.is_file() and not niwa_claude_json.exists():
            shutil.copy2(str(claude_json), str(niwa_claude_json))
            subprocess.run(["chown", "niwa:niwa", str(niwa_claude_json)], capture_output=True)
        # Also try to generate a setup token for portability
        if which("claude") and cfg.llm_provider == "claude":
            try:
                result = subprocess.run(
                    ["claude", "setup-token"],
                    capture_output=True, text=True, timeout=30,
                    input="\n",  # Accept defaults
                )
                if result.returncode == 0 and "sk-ant-" in result.stdout:
                    # Extract token from output
                    for line in result.stdout.split("\n"):
                        if "sk-ant-" in line:
                            token = line.strip()
                            # Save to niwa env
                            env = _read_env_file(niwa_home / "secrets" / "mcp.env")
                            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
                            write_env_file(niwa_home / "secrets" / "mcp.env", env)
                            ok("Generated and saved Claude setup token for executor")
                            break
            except Exception as e:
                info(f"Could not generate setup token: {e} (executor will use copied credentials)")
        # Data/logs in a shared location
        shared_dir = Path("/opt") / cfg.instance_name
        shared_dir.mkdir(parents=True, exist_ok=True)
        if not (shared_dir / "data").exists():
            shutil.copytree(str(cfg.niwa_home / "data"), str(shared_dir / "data"))
        if not (shared_dir / "logs").exists():
            shutil.copytree(str(cfg.niwa_home / "logs"), str(shared_dir / "logs"))
        # Update DB path in niwa user's env
        env = _read_env_file(niwa_home / "secrets" / "mcp.env")
        env["NIWA_DB_PATH"] = str(shared_dir / "data" / "niwa.sqlite3")
        write_env_file(niwa_home / "secrets" / "mcp.env", env)
        # Update compose to mount from shared dir
        compose_path = cfg.niwa_home / "docker-compose.yml"
        if compose_path.exists():
            content = compose_path.read_text()
            old_data_dir = str(cfg.niwa_home / "data")
            if old_data_dir in content:
                content = content.replace(old_data_dir, str(shared_dir / "data"))
                compose_path.write_text(content)
                info(f"Updated compose to mount {shared_dir / 'data'}")
        # Symlinks from niwa home
        for d in ("data", "logs"):
            target = niwa_home / d
            if target.exists() or target.is_symlink():
                target.unlink() if target.is_symlink() else shutil.rmtree(str(target))
            target.symlink_to(shared_dir / d)
        # Pre-create the executor log file so systemd doesn't create it
        # with root ownership on first start.  Systemd's
        # ``StandardOutput=append:<path>`` below opens the file with the
        # service manager's euid (root), creating a root-owned file in
        # a niwa-owned directory — and the Python executor (running as
        # ``User=niwa``) then crash-loops in
        # ``RotatingFileHandler(LOG_PATH)`` with ``PermissionError``.
        # Touching it here means the subsequent ``chown -R`` pins the
        # file to ``niwa:niwa`` before systemd ever sees it, so the
        # service's ``append:`` just reuses the existing fd.
        (shared_dir / "logs" / "executor.log").touch(exist_ok=True)
        subprocess.run(["chown", "-R", "niwa:niwa", str(niwa_home), str(shared_dir)], check=True)
        subprocess.run(["loginctl", "enable-linger", "niwa"], capture_output=True)
        executor_path = niwa_home / "bin" / "task-executor.py"
        niwa_home_env = str(niwa_home)
        log_path = shared_dir / "logs" / "executor.log"
    else:
        niwa_home_env = str(cfg.niwa_home)

    unit_name = f"niwa-{cfg.instance_name}-executor.service"

    # Detect paths for LLM CLIs so the executor can find them
    extra_paths = set()
    for cli in ["claude", "codex", "openclaw", "node", "npm"]:
        cli_path = which(cli)
        if cli_path:
            extra_paths.add(str(Path(cli_path).parent))
    # Also check common npm global locations
    for p in ["/usr/local/bin", str(Path.home() / ".npm-global" / "bin"), "/usr/bin"]:
        if Path(p).is_dir():
            extra_paths.add(p)
    path_env = ":".join(sorted(extra_paths)) + ":/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

    if run_as_root:
        # System-level unit running as niwa user
        unit_dir = Path("/etc/systemd/system")
        unit = f"""[Unit]
Description=Niwa task executor ({cfg.instance_name})
After=network.target

[Service]
Type=simple
User=niwa
Group=niwa
Environment="NIWA_HOME={niwa_home_env}"
Environment="PATH={path_env}"
ExecStart=/usr/bin/env python3 {executor_path}
StandardOutput=append:{log_path}
StandardError=append:{log_path}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
        unit_path = unit_dir / unit_name
        unit_path.write_text(unit)
        ok(f"Wrote systemd unit: {unit_path} (runs as user niwa)")
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
        _reset_failed_unit(unit_name, user_scope=False)
        result = subprocess.run(["systemctl", "enable", "--now", unit_name], capture_output=True, text=True)
    else:
        # User-level unit
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit = f"""[Unit]
Description=Niwa task executor ({cfg.instance_name})
After=network.target

[Service]
Type=simple
Environment="NIWA_HOME={niwa_home_env}"
Environment="PATH={path_env}"
ExecStart=/usr/bin/env python3 {executor_path}
StandardOutput=append:{log_path}
StandardError=append:{log_path}
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
"""
        unit_path = unit_dir / unit_name
        unit_path.write_text(unit)
        ok(f"Wrote systemd unit: {unit_path}")
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        _reset_failed_unit(unit_name, user_scope=True)
        result = subprocess.run(["systemctl", "--user", "enable", "--now", unit_name], capture_output=True, text=True)

    if result.returncode == 0:
        ok(f"Enabled and started {unit_name}")
        # Fail loud: verify the service actually stayed up. PR-25 —
        # Bug 18b in docs/BUGS-FOUND.md. A crash-loop here (see PR-23,
        # PR-24) would otherwise masquerade as a successful install.
        _verify_service_or_abort(unit_name, user_scope=not run_as_root)
    else:
        warn(f"systemctl enable failed: {result.stderr.strip()[:300]}")
        if run_as_root:
            warn(f"Enable manually: systemctl enable --now {unit_name}")
        else:
            warn(f"Enable manually: systemctl --user enable --now {unit_name}")


def _uninstall_service(install_dir: Path, instance: str, service_type: str) -> None:
    """Stop and remove the launchd agent / systemd unit for a service type (executor or hosting)."""
    if sys.platform == "darwin":
        label = f"com.niwa.{instance}.{service_type}"
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
        if plist_path.exists():
            uid = os.getuid()
            subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True)
            plist_path.unlink()
            ok(f"Removed launchd agent {label}")
    elif sys.platform.startswith("linux"):
        unit_name = f"niwa-{instance}-{service_type}.service"
        # Check system-level first (root installs)
        system_path = Path("/etc/systemd/system") / unit_name
        if system_path.exists():
            subprocess.run(["systemctl", "disable", "--now", unit_name], capture_output=True)
            system_path.unlink()
            subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
            ok(f"Removed system systemd unit {unit_name}")
        # Check user-level
        user_path = Path.home() / ".config" / "systemd" / "user" / unit_name
        if user_path.exists():
            subprocess.run(["systemctl", "--user", "disable", "--now", unit_name], capture_output=True)
            user_path.unlink()
            ok(f"Removed user systemd unit {unit_name}")


def _uninstall_task_executor(install_dir: Path, instance: str) -> None:
    """Stop and remove the executor and hosting server services."""
    _uninstall_service(install_dir, instance, "executor")
    _uninstall_service(install_dir, instance, "hosting")


def install_hosting_server(cfg: WizardConfig) -> None:
    """Copy hosting-server.py to the install dir and register it as a service."""
    src = REPO_ROOT / "bin" / "hosting-server.py"
    if not src.exists():
        warn("hosting-server.py not found in repo — skipping hosting server install")
        return
    info("Installing hosting server...")
    bin_dir = cfg.niwa_home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    dest = bin_dir / "hosting-server.py"
    shutil.copy(src, dest)
    dest.chmod(0o755)

    # Create projects directory for hosted sites
    projects_dir = cfg.niwa_home / "data" / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    ok(f"Copied hosting server to {dest}")

    if sys.platform == "darwin":
        label = f"com.niwa.{cfg.instance_name}.hosting"
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        log_path = cfg.niwa_home / "logs" / "hosting.log"
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/env</string>
        <string>python3</string>
        <string>{dest}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>NIWA_DB_PATH</key>
        <string>{cfg.db_path}</string>
        <key>NIWA_PROJECTS_DIR</key>
        <string>{projects_dir}</string>
        <key>NIWA_HOSTING_PORT</key>
        <string>8880</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
</dict>
</plist>
"""
        plist_path.write_text(plist)
        uid = os.getuid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True)
        result = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            ok(f"Loaded hosting server launchd agent {label}")
        else:
            warn(f"launchctl bootstrap failed for hosting: {result.stderr.strip()[:300]}")
    elif sys.platform.startswith("linux"):
        run_as_root = os.getuid() == 0
        log_path = cfg.niwa_home / "logs" / "hosting.log"
        unit_name = f"niwa-{cfg.instance_name}-hosting.service"

        if run_as_root:
            shared_dir = Path("/opt") / cfg.instance_name
            hosting_projects_dir = shared_dir / "data" / "projects"
            hosting_projects_dir.mkdir(parents=True, exist_ok=True)
            unit_dir = Path("/etc/systemd/system")
            unit = f"""[Unit]
Description=Niwa hosting server ({cfg.instance_name})
After=network.target

[Service]
Type=simple
User=niwa
Group=niwa
Environment="NIWA_DB_PATH={shared_dir / 'data' / 'niwa.sqlite3'}"
Environment="NIWA_PROJECTS_DIR={hosting_projects_dir}"
Environment="NIWA_HOSTING_PORT=8880"
ExecStart=/usr/bin/env python3 {dest}
StandardOutput=append:{shared_dir / 'logs' / 'hosting.log'}
StandardError=append:{shared_dir / 'logs' / 'hosting.log'}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
            unit_path = unit_dir / unit_name
            unit_path.write_text(unit)
            subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
            _reset_failed_unit(unit_name, user_scope=False)
            result = subprocess.run(["systemctl", "enable", "--now", unit_name], capture_output=True, text=True)
        else:
            unit_dir = Path.home() / ".config" / "systemd" / "user"
            unit_dir.mkdir(parents=True, exist_ok=True)
            unit = f"""[Unit]
Description=Niwa hosting server ({cfg.instance_name})
After=network.target

[Service]
Type=simple
Environment="NIWA_DB_PATH={cfg.db_path}"
Environment="NIWA_PROJECTS_DIR={projects_dir}"
Environment="NIWA_HOSTING_PORT=8880"
ExecStart=/usr/bin/env python3 {dest}
StandardOutput=append:{log_path}
StandardError=append:{log_path}
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
"""
            unit_path = unit_dir / unit_name
            unit_path.write_text(unit)
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
            _reset_failed_unit(unit_name, user_scope=True)
            result = subprocess.run(["systemctl", "--user", "enable", "--now", unit_name], capture_output=True, text=True)

        if result.returncode == 0:
            ok(f"Enabled and started {unit_name}")
            # Fail loud: verify the hosting service stayed up. PR-25.
            # Mirrors the executor check; closes the latent variant of
            # Bug 18a (hosting has the same log-ownership pattern but
            # doesn't currently open the file at Python level).
            _verify_service_or_abort(unit_name, user_scope=not run_as_root)
        else:
            warn(f"Hosting server systemctl enable failed: {result.stderr.strip()[:300]}")
    else:
        warn(f"Unknown platform — hosting server copied but not started. Run: python3 {dest}")


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


class StepBack(Exception):
    """Raised when the user wants to go back to the previous step."""
    pass


def prompt_with_back(label, **kwargs):
    """Wrapper around prompt() that raises StepBack if user types '<' or 'back'."""
    result = prompt(label, **kwargs)
    if result.strip().lower() in ('<', 'back', 'atras', 'atrás', 'b'):
        raise StepBack()
    return result


def prompt_bool_with_back(label, **kwargs):
    """Wrapper around prompt_bool() that checks for back command."""
    # Show the prompt but intercept 'back' before processing
    raw = prompt(label + f" [{'Y/n' if kwargs.get('default', False) else 'y/N'}] (<: volver) ", default='')
    if raw.strip().lower() in ('<', 'back', 'atras', 'atrás', 'b'):
        raise StepBack()
    if raw.strip() == '':
        return kwargs.get('default', False)
    return raw.strip().lower() in ('y', 'yes', 'si', 'sí', 's')


def run_wizard_steps(cfg: WizardConfig) -> bool:
    """Run all wizard steps with back navigation support.
    
    Type '<' or 'back' at any prompt to go back to the previous step.
    Returns True if the wizard completed, False if aborted.
    """
    steps = [
        ("Detección", step_detection),
        ("Nombre", step_naming),
        ("Base de datos", step_database),
        ("Sistema de archivos", step_filesystem),
        ("Restart whitelist", step_restart_whitelist),
        ("Tokens", step_tokens),
        ("Credenciales", step_credentials),
        ("Puertos", step_ports),
        ("Executor", step_executor),
        ("Proyectos", step_projects),
        ("Acceso remoto", step_remote),
        ("Notificaciones", step_notifications),
        ("Clientes MCP", step_clients),
    ]
    
    i = 0
    while i < len(steps):
        name, fn = steps[i]
        try:
            fn(cfg)
            i += 1
        except StepBack:
            if i > 0:
                i -= 1
                info(f"Volviendo a: {steps[i][0]}")
            else:
                info("Ya estás en el primer paso.")
        except KeyboardInterrupt:
            print()
            info("Instalación cancelada.")
            return False
    
    # Summary step (can also go back)
    while True:
        try:
            if step_summary(cfg):
                return True
            info("Aborted — nothing was installed")
            return False
        except StepBack:
            i = len(steps) - 1
            name, fn = steps[i]
            info(f"Volviendo a: {name}")
            try:
                fn(cfg)
            except StepBack:
                if i > 0:
                    i -= 1
            continue


def cmd_install(args) -> None:
    print(f"{BOLD}🌿 Niwa installer{RESET}")
    print(f"{DIM}Interactive setup for the Niwa MCP gateway + web app{RESET}")
    print(f"{DIM}Escribe '<' o 'back' en cualquier momento para volver al paso anterior.{RESET}\n")
    cfg = WizardConfig()
    if not run_wizard_steps(cfg):
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
    app_port = env.get("NIWA_APP_PORT", "?")

    header(f"Niwa install: {instance}")
    print(f"  Location:  {install_dir}")
    print(f"  Endpoints:")
    print(f"    Gateway streaming HTTP:  http://localhost:{streaming_port}/mcp")
    print(f"    Gateway SSE legacy:      http://localhost:{sse_port}/sse")
    print(f"    Caddy reverse proxy:     http://localhost:{caddy_port}/mcp")
    print(f"    Niwa app web UI:         http://localhost:{app_port}")
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

    # Niwa app healthcheck
    try:
        with urllib.request.urlopen(f"http://localhost:{app_port}/health", timeout=3) as r:
            ok(f"Niwa app responding ({r.status})")
    except Exception as e:
        warn(f"Niwa app not reachable: {e}")


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
    print(f"  Will remove:     docker images for {instance}-tasks-mcp, {instance}-notes-mcp, "
          f"{instance}-platform-mcp, {instance}-app")
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

    # Remove images (both versioned and legacy :latest)
    images = [
        f"{instance}-tasks-mcp:{NIWA_VERSION}",
        f"{instance}-notes-mcp:{NIWA_VERSION}",
        f"{instance}-platform-mcp:{NIWA_VERSION}",
        f"{instance}-app:{NIWA_VERSION}",
        f"{instance}-tasks-mcp:latest",
        f"{instance}-notes-mcp:latest",
        f"{instance}-platform-mcp:latest",
        f"{instance}-app:latest",
    ]
    for img in images:
        result = subprocess.run(["docker", "rmi", img], capture_output=True, text=True)
        if result.returncode == 0:
            ok(f"Removed image {img}")

    # Unregister from clients ONLY if this install registered them
    # (avoids wiping registrations belonging to a different install with the same server name).
    tasks_name = env.get("NIWA_TASKS_SERVER_NAME", "tasks")
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

    # Stop task executor (launchd / systemd)
    if env.get("NIWA_EXECUTOR_ENABLED") == "1":
        _uninstall_task_executor(install_dir, instance)

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
    # Special: 'executor' is the host-side launchd/systemd worker, not a container
    if role == "executor":
        log_path = install_dir / "logs" / "executor.log"
        if not log_path.exists():
            err(f"Executor log not found at {log_path}")
            sys.exit(1)
        info(f"Tailing {log_path} (Ctrl+C to exit)...")
        try:
            subprocess.run(["tail", "-n", str(args.tail), "-f", str(log_path)])
        except KeyboardInterrupt:
            pass
        return
    # Otherwise: docker container logs
    container = f"{instance}-{role}"
    info(f"Showing last {args.tail} lines of {container} (Ctrl+C to exit)...")
    try:
        subprocess.run(["docker", "logs", "--tail", str(args.tail), "-f", container])
    except KeyboardInterrupt:
        pass


_CONFIG_KEYS = {
    "telegram_bot_token": "NIWA_TELEGRAM_BOT_TOKEN",
    "telegram_chat_id": "NIWA_TELEGRAM_CHAT_ID",
    "webhook_url": "NIWA_WEBHOOK_URL",
    "llm_provider": "NIWA_LLM_PROVIDER",
    "llm_command": "NIWA_LLM_COMMAND",
    "llm_api_key": "NIWA_LLM_API_KEY",
    "executor_enabled": "NIWA_EXECUTOR_ENABLED",
    "executor_poll_seconds": "NIWA_EXECUTOR_POLL_SECONDS",
    "executor_timeout_seconds": "NIWA_EXECUTOR_TIMEOUT_SECONDS",
}
_SENSITIVE_CONFIG = {"telegram_bot_token", "llm_api_key"}


def cmd_config(args) -> None:
    """View or update Niwa configuration."""
    install_dir = _find_install_dir(args.dir)
    if not install_dir:
        err("No niwa install found.")
        sys.exit(1)
    env_path = install_dir / "secrets" / "mcp.env"
    env = _read_env_file(env_path)

    # niwa config (no args) — show current values
    if not args.key:
        header("Niwa configuration")
        for key, env_var in _CONFIG_KEYS.items():
            val = env.get(env_var, "")
            if key in _SENSITIVE_CONFIG and val:
                display = val[:8] + "..." + val[-4:] if len(val) > 12 else "****"
            else:
                display = val or DIM + "(not set)" + RESET
            print(f"  {BOLD}{key:30}{RESET} {display}")
        print()
        info(f"Config file: {env_path}")
        info("Set a value: niwa config <key> <value>")
        return

    key = args.key
    if key not in _CONFIG_KEYS:
        err(f"Unknown key: {key}")
        info(f"Available keys: {', '.join(_CONFIG_KEYS)}")
        sys.exit(1)

    # niwa config <key> (no value) — show single value
    if args.value is None:
        env_var = _CONFIG_KEYS[key]
        val = env.get(env_var, "")
        if key in _SENSITIVE_CONFIG and val:
            print(val[:8] + "..." + val[-4:] if len(val) > 12 else "****")
        else:
            print(val or "(not set)")
        return

    # niwa config <key> <value> — update
    env_var = _CONFIG_KEYS[key]
    new_val = args.value
    env[env_var] = new_val
    write_env_file(env_path, env)
    ok(f"{key} updated")
    if key in _SENSITIVE_CONFIG:
        info(f"Value: {new_val[:8]}...{new_val[-4:]}" if len(new_val) > 12 else f"Value: ****")
    else:
        info(f"Value: {new_val}")
    warn("Restart containers for changes to take effect: niwa restart")


def cmd_backup(args) -> None:
    """Backup the Niwa database with 7-day rotation."""
    install_dir = _find_install_dir(args.dir)
    if not install_dir:
        err("No niwa install found.")
        sys.exit(1)
    env = _read_env_file(install_dir / "secrets" / "mcp.env")
    db_path = Path(env.get("NIWA_DB_PATH", str(install_dir / "data" / "niwa.sqlite3")))
    if not db_path.exists():
        err(f"Database not found at {db_path}")
        sys.exit(1)
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = backup_dir / f"niwa-{stamp}.sqlite3"
    import sqlite3 as _sq
    src_conn = _sq.connect(str(db_path))
    dst_conn = _sq.connect(str(dst))
    src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()
    ok(f"Backup: {dst} ({dst.stat().st_size:,} bytes)")
    # Rotate backups older than 7 days
    cutoff = time.time() - 7 * 86400
    rotated = 0
    for old in sorted(backup_dir.glob("niwa-*.sqlite3")):
        if old == dst:
            continue
        if old.stat().st_mtime < cutoff:
            old.unlink()
            rotated += 1
    if rotated:
        info(f"Rotated {rotated} backup(s) older than 7 days")


def cmd_update(args) -> None:
    """Update Niwa: pull latest code, rebuild containers, apply migrations.
    Preserves all config, secrets, and data."""
    install_dir = Path(args.dir) if getattr(args, 'dir', None) else _find_install_dir()
    if not install_dir or not install_dir.exists():
        print("\u274c Niwa install not found. Use --dir or set NIWA_HOME.")
        sys.exit(1)

    repo_dir = install_dir / "repo"
    if not (repo_dir / ".git").exists():
        # Find repo from the clone record
        repo_dir = Path(__file__).parent
        if not (repo_dir / ".git").exists():
            print("\u274c Git repo not found. Clone the repo first.")
            sys.exit(1)

    print("\U0001f504 Updating Niwa...")

    # 1. Git pull
    print("  \u2192 Pulling latest code...")
    result = subprocess.run(["git", "pull", "origin", "main"], cwd=str(repo_dir),
                          capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  \u26a0\ufe0f  Git pull failed: {result.stderr[:200]}")
        print("  Continuing with current code...")
    else:
        print(f"  \u2713 {result.stdout.strip()}")

    # 2. Copy updated files (preserve secrets/config)
    print("  \u2192 Updating executor...")
    src_executor = repo_dir / "bin" / "task-executor.py"
    dst_executor = install_dir / "bin" / "task-executor.py"
    if src_executor.exists() and dst_executor.exists():
        shutil.copy2(str(src_executor), str(dst_executor))
        print("  \u2713 Executor updated")

    print("  \u2192 Updating MCP servers...")
    for server_name in ("tasks-mcp", "notes-mcp", "platform-mcp"):
        src = repo_dir / "servers" / server_name / "server.py"
        dst = install_dir / "servers" / server_name / "server.py"
        if src.exists() and dst.parent.exists():
            shutil.copy2(str(src), str(dst))
            print(f"  \u2713 {server_name}")

    # 3. Rebuild app container
    print("  \u2192 Rebuilding app container...")
    instance = install_dir.name.replace(".", "")
    compose_file = install_dir / "docker-compose.yml"
    if compose_file.exists():
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "build", "--no-cache", "app"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("  \u2713 App container rebuilt")
            # Restart app
            subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "up", "-d", "--no-deps", "app"],
                capture_output=True, text=True
            )
            print("  \u2713 App restarted")
        else:
            print(f"  \u26a0\ufe0f  Build failed: {result.stderr[:200]}")

    # 4. Restart executor
    print("  \u2192 Restarting executor...")
    service_name = f"niwa-{instance}-executor.service" if instance != "niwa" else "niwa-executor.service"
    result = subprocess.run(["systemctl", "restart", service_name],
                          capture_output=True, text=True)
    if result.returncode == 0:
        print("  \u2713 Executor restarted")
    else:
        print(f"  \u26a0\ufe0f  Executor restart failed (may need: sudo systemctl restart {service_name})")

    print("\n\u2705 Niwa updated successfully!")
    print("   Config, secrets, and data are preserved.")
    print("   Migrations will run automatically on next app startup.")


def cmd_hosting(args) -> None:
    """Set up web hosting for static project sites."""
    install_dir = _find_install_dir(getattr(args, 'dir', None))
    if not install_dir:
        err("No niwa install found. Run './niwa install' first.")
        sys.exit(1)

    header("Niwa Web Hosting Setup")
    port = getattr(args, 'port', 8880)
    domain = getattr(args, 'domain', None) or ""

    if not domain:
        info("No domain provided — path-based routing will be used (http://VPS_IP:port/project-name/).")
        info("To use subdomain routing, pass --domain projects.yoursite.com")
    else:
        ok(f"Domain: {domain}")
        print()
        info("DNS setup required: create a wildcard A record pointing to your VPS:")
        print(f"  *.{domain}  A  <VPS_IP>")
        print(f"  {domain}    A  <VPS_IP>")
        print()

    # Write hosting config to mcp.env
    env_path = install_dir / "secrets" / "mcp.env"
    env = _read_env_file(env_path) if env_path.exists() else {}
    env["NIWA_HOSTING_PORT"] = str(port)
    env["NIWA_HOSTING_DOMAIN"] = domain
    env["NIWA_HOSTING_CADDYFILE"] = str(install_dir / "data" / "niwa-hosting-Caddyfile")
    write_env_file(env_path, env)
    ok(f"Saved hosting config to {env_path}")

    # Generate initial Caddyfile
    caddyfile_path = install_dir / "data" / "niwa-hosting-Caddyfile"
    caddyfile_path.parent.mkdir(parents=True, exist_ok=True)
    caddyfile_content = [
        "# Auto-generated by Niwa hosting",
        "{",
        "    admin off",
        "    auto_https off",
        "}",
        "",
        f":{port} {{",
        '    handle {',
        f'        respond "Niwa Hosting - 0 projects deployed" 200',
        "    }",
        "}",
    ]
    caddyfile_path.write_text("\n".join(caddyfile_content))
    ok(f"Generated initial Caddyfile at {caddyfile_path}")

    # Try to start Caddy
    caddy_bin = shutil.which("caddy")
    if caddy_bin:
        info(f"Starting Caddy on port {port}...")
        try:
            subprocess.Popen(
                [caddy_bin, "run", "--config", str(caddyfile_path), "--adapter", "caddyfile"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            ok(f"Caddy started on port {port}")
        except Exception as e:
            warn(f"Could not start Caddy automatically: {e}")
            info(f"Start manually: caddy run --config {caddyfile_path} --adapter caddyfile")
    else:
        warn("caddy not found in PATH. Install Caddy or use Docker.")
        info(f"To run with Docker: docker run -d -p {port}:{port} -v {caddyfile_path}:/etc/caddy/Caddyfile:ro caddy:2-alpine")

    print()
    ok("Hosting setup complete!")
    if domain:
        info(f"Example URL: http://my-project.{domain}:{port}/")
    else:
        public_url = env.get("NIWA_PUBLIC_URL", "http://localhost")
        info(f"Example URL: {public_url}:{port}/my-project/")
    info("Deploy a project: use the deploy_web MCP tool or call hosting.deploy_project() directly.")


# ────────────────────────── PR-11: quick installer ──────────────────────────
# Two-mode quick install: --mode core (Niwa standalone) and --mode assistant
# (Niwa + OpenClaw MCP registration). See docs/SPEC-v0.2.md PR-11.
QUICK_MODES = ("core", "assistant")


def detect_claude_credentials() -> dict:
    """Inspect the current environment for a usable Claude CLI auth.

    Returns a dict with:
      - ``cli``: bool — ``claude`` binary resolvable via PATH.
      - ``authenticated``: bool — at least one credential source detected.
      - ``source``: short label ("env:ANTHROPIC_API_KEY", "~/.claude.json", …).
      - ``detail``: human-readable message suitable for printing.

    Side effects: none. Never echoes a token.
    """
    if not which("claude"):
        return {
            "cli": False,
            "authenticated": False,
            "source": "",
            "detail": "claude CLI not in PATH — Claude backend will be unavailable",
        }
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return {
            "cli": True,
            "authenticated": True,
            "source": "env:CLAUDE_CODE_OAUTH_TOKEN",
            "detail": "claude auth: CLAUDE_CODE_OAUTH_TOKEN present",
        }
    if os.environ.get("ANTHROPIC_API_KEY"):
        return {
            "cli": True,
            "authenticated": True,
            "source": "env:ANTHROPIC_API_KEY",
            "detail": "claude auth: ANTHROPIC_API_KEY present",
        }
    cfg_file = Path.home() / ".claude.json"
    if cfg_file.is_file():
        return {
            "cli": True,
            "authenticated": True,
            "source": "~/.claude.json",
            "detail": "claude auth: ~/.claude.json present",
        }
    return {
        "cli": True,
        "authenticated": False,
        "source": "",
        "detail": "claude CLI present but not authenticated — run `claude` once or export CLAUDE_CODE_OAUTH_TOKEN",
    }


def detect_codex_credentials() -> dict:
    """Inspect the current environment for a usable Codex CLI auth.

    Mirrors ``detect_claude_credentials``.  Codex tokens in v0.2 live in
    the Niwa DB (oauth_tokens, provider='openai') — those are filled
    from the web UI after install, not at install time, so detection
    here is limited to CLI presence + env vars.
    """
    if not which("codex"):
        return {
            "cli": False,
            "authenticated": False,
            "source": "",
            "detail": "codex CLI not in PATH — Codex backend will be unavailable",
        }
    if os.environ.get("OPENAI_ACCESS_TOKEN"):
        return {
            "cli": True,
            "authenticated": True,
            "source": "env:OPENAI_ACCESS_TOKEN",
            "detail": "codex auth: OPENAI_ACCESS_TOKEN present",
        }
    if os.environ.get("OPENAI_API_KEY"):
        return {
            "cli": True,
            "authenticated": True,
            "source": "env:OPENAI_API_KEY",
            "detail": "codex auth: OPENAI_API_KEY present",
        }
    codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    if (codex_home / "auth.json").is_file():
        return {
            "cli": True,
            "authenticated": True,
            "source": f"{codex_home}/auth.json",
            "detail": f"codex auth: {codex_home}/auth.json present",
        }
    return {
        "cli": True,
        "authenticated": False,
        "source": "",
        "detail": "codex CLI present but no auth detected — configure OAuth via the Niwa web UI after install",
    }


def detect_openclaw_presence() -> dict:
    """Check that the OpenClaw CLI is available (needed for --mode assistant).

    Returns ``{'cli': bool, 'detail': str}``.
    """
    if not which("openclaw"):
        return {
            "cli": False,
            "detail": "openclaw CLI not in PATH",
        }
    return {
        "cli": True,
        "detail": "openclaw CLI present",
    }


def resolve_quick_workspace(arg_workspace: Optional[str], niwa_home: Path) -> Path:
    """Resolve the workspace path for --quick.

    Priority:
      1. Explicit ``--workspace`` CLI argument.
      2. ``NIWA_FILESYSTEM_WORKSPACE`` from an existing ``secrets/mcp.env``
         (re-install over the same install dir).
      3. ``<niwa_home>/data`` default.
    """
    if arg_workspace:
        return Path(arg_workspace).expanduser().resolve()
    env_file = niwa_home / "secrets" / "mcp.env"
    if env_file.is_file():
        existing = _read_env_file(env_file).get("NIWA_FILESYSTEM_WORKSPACE")
        if existing:
            return Path(existing).expanduser()
    return (niwa_home / "data").resolve()


def _quick_free_port(default: int) -> int:
    """Return ``default`` if free, else first free offset in [1, 100).

    Keeps quick install non-interactive even on machines that already
    have another niwa install running — the operator can still pin with
    explicit flags if they want deterministic ports.
    """
    if detect_port_free(default):
        return default
    for offset in range(1, 100):
        candidate = default + offset
        if detect_port_free(candidate):
            return candidate
    return default  # give up — user will see collision warning downstream


def parse_public_url(url: str) -> dict:
    """Parse --public-url into bind info. Returns {'domain', 'scheme'}.

    Accepts forms: ``example.com``, ``https://example.com``,
    ``http://example.com:8080``. Empty string → ``{'domain': '', 'scheme': ''}``.
    """
    if not url:
        return {"domain": "", "scheme": ""}
    from urllib.parse import urlparse
    # Add scheme if missing so urlparse works predictably
    candidate = url if "://" in url else f"https://{url}"
    parsed = urlparse(candidate)
    host = parsed.hostname or ""
    return {"domain": host, "scheme": parsed.scheme or "https"}


def build_quick_config(args) -> WizardConfig:
    """Construct a WizardConfig from CLI args + autodetection.

    Does NOT prompt interactively except when ``--yes`` is not set and
    a value is genuinely ambiguous. Does NOT mutate the filesystem nor
    the DB — only assembles config.
    """
    cfg = WizardConfig()

    # --- Pre-flight: docker is hard requirement ---
    docker = detect_docker()
    if not docker.get("available"):
        err("Docker is not installed or not in PATH.")
        print_install_hint("docker")
        sys.exit(1)
    sock = detect_socket_path()
    if not sock:
        err("Could not find a Docker socket.")
        sys.exit(1)
    cfg.detected["docker_socket"] = sock

    # --- Naming & location ---
    cfg.instance_name = (getattr(args, "instance", None) or "niwa")
    if getattr(args, "dir", None):
        cfg.niwa_home = Path(args.dir).expanduser().resolve()
    else:
        cfg.niwa_home = Path.home() / f".{cfg.instance_name}"

    # --- DB ---
    cfg.db_mode = "fresh"
    cfg.db_path = cfg.niwa_home / "data" / "niwa.sqlite3"

    # --- Filesystem workspace ---
    cfg.fs_workspace = resolve_quick_workspace(
        getattr(args, "workspace", None), cfg.niwa_home
    )
    cfg.fs_memory = cfg.niwa_home / "memory"

    # --- Binding: --public-url implies 0.0.0.0, else loopback ---
    public_url = getattr(args, "public_url", None) or ""
    if public_url:
        cfg.bind_host = "0.0.0.0"
        cfg.mode = "remote"
        parsed = parse_public_url(public_url)
        cfg.public_domain = parsed["domain"]
    else:
        cfg.bind_host = "127.0.0.1"
        cfg.mode = "local-only"

    # --- Ports with auto-increment on collision ---
    cfg.gateway_streaming_port = _quick_free_port(18810)
    cfg.gateway_sse_port = _quick_free_port(18812)
    cfg.caddy_port = _quick_free_port(18811)
    cfg.app_port = _quick_free_port(8080)
    cfg.terminal_port = 7681  # unused in quick install (advanced overlay only)

    # --- Restart whitelist: empty by default, operator edits post-install ---
    cfg.restart_whitelist = []

    # --- Tokens ---
    cfg.tokens["NIWA_LOCAL_TOKEN"] = generate_token()
    cfg.tokens["NIWA_REMOTE_TOKEN"] = generate_token()
    cfg.tokens["MCP_GATEWAY_AUTH_TOKEN"] = cfg.tokens["NIWA_LOCAL_TOKEN"]

    # --- App web UI credentials ---
    cfg.username = (getattr(args, "admin_user", None) or "niwa")
    provided_pw = getattr(args, "admin_password", None)
    if provided_pw:
        cfg.password = provided_pw
    else:
        # Auto-generate a readable password. Printed at the end of the
        # install. Never written to logs, only to secrets/mcp.env and
        # displayed once in the summary.
        cfg.password = generate_token()[:24]

    # --- Executor: enabled by default, claude provider ---
    cfg.executor_enabled = True
    cfg.llm_provider = "claude"
    cfg.llm_command = LLM_PROVIDERS["claude"]["command"]

    # --- Detection ---
    cfg.detected["claude"] = which("claude") is not None
    cfg.detected["openclaw"] = which("openclaw") is not None
    cfg.detected["cloudflared"] = which("cloudflared") is not None

    # --- Register Claude MCP client if authenticated ---
    claude = detect_claude_credentials()
    cfg.register_claude = bool(claude["authenticated"])

    # --- Mode-specific: OpenClaw registration ---
    cfg.quick_mode = args.mode
    if args.mode == "assistant":
        openclaw = detect_openclaw_presence()
        cfg.register_openclaw = openclaw["cli"]
        cfg.mcp_contract = "v02-assistant"
        cfg.mcp_server_token = generate_token()
    else:
        cfg.register_openclaw = False
        cfg.mcp_contract = ""
        cfg.mcp_server_token = ""

    return cfg


def print_quick_plan(cfg: WizardConfig) -> None:
    """Print the resolved quick-install plan so the operator can eyeball it."""
    header("Niwa install --quick plan")
    print(f"  Mode:              {cfg.quick_mode}")
    print(f"  Instance name:     {cfg.instance_name}")
    print(f"  Install location:  {cfg.niwa_home}")
    print(f"  Database:          fresh at {cfg.db_path}")
    print(f"  Workspace:         {cfg.fs_workspace}")
    print(f"  Bind:              {cfg.bind_host} ({cfg.mode})")
    if cfg.public_domain:
        print(f"  Public domain:     {cfg.public_domain}")
    print(f"  Ports:             gateway={cfg.gateway_streaming_port}, "
          f"sse={cfg.gateway_sse_port}, caddy={cfg.caddy_port}, app={cfg.app_port}")
    print(f"  App login user:    {cfg.username}  (password auto-generated; shown after install)")
    print(f"  Executor:          claude  ({cfg.llm_command})")
    claude = detect_claude_credentials()
    print(f"  {claude['detail']}")
    codex = detect_codex_credentials()
    print(f"  {codex['detail']}")
    print(f"  Register Claude:   {cfg.register_claude}")
    print(f"  Register OpenClaw: {cfg.register_openclaw}")
    if cfg.quick_mode == "assistant":
        print(f"  MCP contract:      {cfg.mcp_contract}")
    print(f"  Terminal service:  disabled (advanced overlay only)")
    print()


def _ensure_assistant_prereqs(cfg: WizardConfig) -> Optional[str]:
    """Return an error message if assistant-mode prereqs are missing, else None."""
    if cfg.quick_mode != "assistant":
        return None
    if not cfg.detected.get("openclaw"):
        return (
            "OpenClaw is required for --mode assistant but the CLI was not found.\n"
            "  Install it first (npm i -g openclaw@latest, or see https://openclaw.ai/install),\n"
            "  then re-run: ./niwa install --quick --mode assistant"
        )
    return None


def detect_existing_quick_mode(niwa_home: Path) -> str:
    """Detect the quick-install mode currently recorded for ``niwa_home``.

    Returns:
        - ``""`` if no install exists at the path (or no ``secrets/mcp.env``).
        - ``"assistant"`` if ``NIWA_MCP_CONTRACT=v02-assistant`` is set.
        - ``"core"`` otherwise (existing install without the assistant flag).

    The function is read-only; it never mutates the install.
    """
    env_file = niwa_home / "secrets" / "mcp.env"
    if not env_file.is_file():
        return ""
    env = _read_env_file(env_file)
    contract = env.get("NIWA_MCP_CONTRACT") or ""
    if contract == "v02-assistant":
        return "assistant"
    return "core"


def _ensure_mode_matches_existing(cfg: WizardConfig,
                                   force: bool) -> Optional[str]:
    """Defensive idempotence check (SPEC PR-11 rule C).

    If an install already exists at ``cfg.niwa_home`` under a different
    mode than the one requested, return an error message asking the
    operator to either change ``--mode`` or pass ``--force``. Same-mode
    reinstalls are allowed and behave as update-in-place (tokens and
    admin password rotate).

    Returns None when it is safe to proceed.
    """
    existing = detect_existing_quick_mode(cfg.niwa_home)
    if not existing:
        return None  # fresh install
    if existing == cfg.quick_mode:
        return None  # idempotent reinstall under the same mode
    if force:
        return None  # explicit override
    return (
        f"{cfg.niwa_home} is already installed in --mode {existing}; refusing to\n"
        f"  silently switch to --mode {cfg.quick_mode}. Options:\n"
        f"    1. Re-run with --mode {existing} (same as the current install).\n"
        f"    2. Re-run with --force to overwrite the existing install config\n"
        f"       (DB data is preserved; tokens and registered MCP clients rotate).\n"
        f"    3. Uninstall first: ./niwa uninstall --dir {cfg.niwa_home}"
    )


def _parse_url_for_main(url: str) -> Optional[str]:  # pragma: no cover
    """Wrapper around parse_public_url that validates non-empty domain."""
    info = parse_public_url(url)
    if not info["domain"]:
        return None
    return info["domain"]


def cmd_install_quick(args) -> int:
    """Entrypoint for ``install --quick``. Returns an exit code."""
    print(f"{BOLD}🌿 Niwa installer — quick ({args.mode}){RESET}")
    print(f"{DIM}Non-interactive install path (SPEC PR-11).{RESET}\n")

    if args.mode not in QUICK_MODES:
        err(f"--mode must be one of {QUICK_MODES}, got: {args.mode!r}")
        return 2

    cfg = build_quick_config(args)

    # Assistant mode requires OpenClaw present. Fail clean with exit 2.
    blocker = _ensure_assistant_prereqs(cfg)
    if blocker:
        err(blocker)
        return 2

    # Idempotence guard (SPEC PR-11 rule C): refuse silent mode changes.
    mode_mismatch = _ensure_mode_matches_existing(cfg, getattr(args, "force", False))
    if mode_mismatch:
        err(mode_mismatch)
        return 2

    # Inform the operator when a same-mode reinstall will rotate secrets.
    existing_mode = detect_existing_quick_mode(cfg.niwa_home)
    if existing_mode == cfg.quick_mode:
        warn(
            f"Existing {existing_mode}-mode install detected at {cfg.niwa_home}. "
            "This re-run will rotate tokens and the admin password "
            "(DB data is preserved)."
        )

    print_quick_plan(cfg)

    if not args.yes:
        if not prompt_bool("Proceed with install?", default=True):
            info("Aborted by user — nothing was installed.")
            return 130

    # Delegate to the full install flow. Ported paths like execute_install
    # already handle DB seed, compose up, healthchecks, client registration.
    try:
        execute_install(cfg)
    except SystemExit as exc:
        # execute_install calls sys.exit(1) on compose/build failures.
        return int(exc.code) if isinstance(exc.code, int) else 1
    except Exception as exc:  # pragma: no cover — defensive
        err(f"install failed: {exc}")
        return 1

    # Post-install smoke. Mode-specific checks live in installer_smoke().
    smoke = installer_smoke(cfg)
    if not smoke["ok"]:
        err("Post-install smoke test failed — the stack is up, fix and retry manually.")
        for step in smoke["steps"]:
            marker = "✓" if step["ok"] else "✗"
            print(f"  {marker} {step['name']}{(' — ' + step['detail']) if step['detail'] else ''}")
        return 1

    print()
    ok(f"Quick install ({cfg.quick_mode}) completed — smoke: PASS in {smoke['duration_ms']}ms")
    if cfg.quick_mode == "assistant":
        # The installer smoke tolerates LLM-not-configured (SPEC PR-11 rule G
        # + PR-09 Dec A): the MCP contract surface is fully advertised even
        # without an LLM, the assistant_turn roundtrip is simply skipped.
        # Surface an explicit tip so the operator knows where to complete
        # the wiring for the conversational chat.
        print()
        info("Para usar el chat conversacional real (assistant_turn con "
             "respuestas del LLM), configura el modelo y la API key en la UI: "
             "System → Agentes (pestaña 'assistant').")
        mcp_smoke_cmd = (f"bin/niwa-mcp-smoke --app-url http://localhost:{cfg.app_port} "
                         "--token <NIWA_MCP_SERVER_TOKEN> --project-id <id>")
        info(f"Re-run the MCP smoke with a roundtrip any time: {mcp_smoke_cmd}")
    return 0


def installer_smoke(cfg: WizardConfig) -> dict:
    """Post-install verification covering HTTP health, DB, and (assistant) MCP.

    Returns::

        {"ok": bool, "steps": [{"name", "ok", "detail"}, ...], "duration_ms": int}

    Must complete in <30s on a clean install. If it takes longer, there
    is a healthcheck or timeout issue.
    """
    import sqlite3 as _sqlite3
    t0 = time.monotonic()
    steps: list[dict] = []
    ok_overall = True

    def _add(name: str, ok_: bool, detail: str = "") -> None:
        nonlocal ok_overall
        steps.append({"name": name, "ok": ok_, "detail": detail})
        if not ok_:
            ok_overall = False

    # 1. App /health responds
    try:
        with urllib.request.urlopen(
            f"http://localhost:{cfg.app_port}/health", timeout=5
        ) as resp:
            _add("app_health", resp.status == 200, f"HTTP {resp.status}")
    except Exception as exc:
        _add("app_health", False, str(exc))

    # 2. DB migrated with v0.2 tables + routing_mode=v02.
    # init_db() runs when the app container boots, after the installer's
    # schema+migrations pass. Retry a few times to absorb the boot window.
    db_path = cfg.niwa_home / "data" / "niwa.sqlite3"
    if db_path.exists():
        required = {"tasks", "projects", "settings", "backend_profiles",
                    "routing_decisions", "backend_runs", "approvals"}
        tables_ok = False
        missing: set[str] = set()
        tables: set[str] = set()
        for _ in range(15):
            try:
                conn = _sqlite3.connect(str(db_path))
                tables = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()}
                conn.close()
                missing = required - tables
                if not missing:
                    tables_ok = True
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if tables_ok:
            _add("db_tables", True, f"{len(tables)} tables present")
        else:
            _add("db_tables", False, f"missing: {sorted(missing)}")

        mode_val = None
        for _ in range(15):
            try:
                conn = _sqlite3.connect(str(db_path))
                row = conn.execute(
                    "SELECT value FROM settings WHERE key='routing_mode'"
                ).fetchone()
                conn.close()
                mode_val = row[0] if row else None
                if mode_val == "v02":
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if mode_val == "v02":
            _add("routing_mode_v02", True, "settings.routing_mode=v02")
        else:
            _add("routing_mode_v02", False, f"settings.routing_mode={mode_val!r}")
    else:
        _add("db_tables", False, f"DB not found at {db_path}")

    # 3. Mode-specific checks
    if cfg.quick_mode == "core":
        # Basic API endpoints respond (no auth required: /health + /api/version)
        try:
            with urllib.request.urlopen(
                f"http://localhost:{cfg.app_port}/api/version", timeout=5
            ) as resp:
                _add("api_version", resp.status == 200, f"HTTP {resp.status}")
        except Exception as exc:
            _add("api_version", False, str(exc))
    elif cfg.quick_mode == "assistant":
        # Invoke the PR-09 MCP smoke via bin/niwa-mcp-smoke (as a subprocess
        # so we keep the exact contract covered by the existing CI).
        smoke_result = _run_mcp_smoke_subprocess(cfg)
        _add(
            "mcp_assistant_smoke",
            smoke_result["ok"],
            smoke_result.get("detail", ""),
        )

    duration_ms = int((time.monotonic() - t0) * 1000)
    return {"ok": ok_overall, "steps": steps, "duration_ms": duration_ms}


def _run_mcp_smoke_subprocess(cfg: WizardConfig) -> dict:
    """Invoke bin/niwa-mcp-smoke with the v02-assistant contract.

    The smoke is allowed to report ``roundtrip_assistant_turn_skip``
    (LLM not configured) without marking the overall install as failed
    — PR-09 Dec A + the SPEC's ``assistant mode install completes even
    without LLM`` rule.
    """
    script = REPO_ROOT / "bin" / "niwa-mcp-smoke"
    if not script.is_file():
        return {"ok": False, "detail": f"{script} not found"}
    cmd = [
        sys.executable, str(script),
        "--app-url", f"http://localhost:{cfg.app_port}",
        "--token", cfg.mcp_server_token or cfg.tokens.get("MCP_GATEWAY_AUTH_TOKEN", ""),
        "--json",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as exc:
        return {"ok": False, "detail": f"smoke subprocess error: {exc}"}
    try:
        payload = json.loads(r.stdout or "{}")
    except Exception:
        return {"ok": False, "detail": f"smoke returned non-JSON (exit {r.returncode})"}
    if payload.get("ok"):
        return {"ok": True, "detail": f"{payload.get('duration_ms', '?')}ms"}
    # Exception: LLM-not-configured skip is not a failure.
    for step in payload.get("steps", []):
        if step.get("name") == "roundtrip_assistant_turn_skip" and step.get("ok"):
            # Check whether the only non-ok condition was the roundtrip;
            # if everything else passed, treat as pass with warning.
            other_failures = [
                s for s in payload["steps"]
                if not s.get("ok") and s.get("name") != "roundtrip_assistant_turn"
            ]
            if not other_failures:
                return {
                    "ok": True,
                    "detail": "LLM not configured — roundtrip skipped (install still valid)",
                }
    return {"ok": False, "detail": payload.get("error_message") or "smoke failed"}


def main():
    parser = argparse.ArgumentParser(description="Niwa installer and CLI")
    sub = parser.add_subparsers(dest="cmd")

    p_install = sub.add_parser("install", help="Interactive install (default)")
    # PR-11: --quick --mode flags. When --quick is NOT passed, the
    # interactive wizard (steps 0-13) runs exactly as before.
    p_install.add_argument("--quick", action="store_true",
                           help="Run the non-interactive quick install (PR-11)")
    p_install.add_argument("--mode", choices=QUICK_MODES, default="core",
                           help="Install mode: core (standalone) or assistant (with OpenClaw). "
                                "Only read when --quick is set.")
    p_install.add_argument("-y", "--yes", action="store_true",
                           help="Skip the final confirmation prompt (--quick only)")
    p_install.add_argument("--workspace",
                           help="Workspace directory to expose as /workspace (quick only)")
    p_install.add_argument("--public-url",
                           help="If set, bind ports to 0.0.0.0 and use this domain (quick only)")
    p_install.add_argument("--admin-user",
                           help="Niwa web UI username (default: niwa). Quick install only.")
    p_install.add_argument("--admin-password",
                           help="Niwa web UI password. If omitted, one is auto-generated.")
    p_install.add_argument("--instance",
                           help="Instance name (default: niwa). Quick install only.")
    p_install.add_argument("--dir",
                           help="Install directory (default: ~/.<instance>). Quick install only.")
    p_install.add_argument("--force", action="store_true",
                           help="Overwrite an existing install even when the --mode differs "
                                "from the recorded one. DB data is preserved.")

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

    p_backup = sub.add_parser("backup", help="Backup the Niwa database")
    p_backup.add_argument("--dir", help="Install location (auto-detect by default)")

    p_config = sub.add_parser("config", help="View or update configuration")
    p_config.add_argument("key", nargs="?", help="Config key (e.g. telegram_bot_token, llm_command)")
    p_config.add_argument("value", nargs="?", help="New value (omit to show current)")
    p_config.add_argument("--dir", help="Install location (auto-detect by default)")

    p_update = sub.add_parser("update", help="Update Niwa to the latest version (preserves config/data)")
    p_update.add_argument("--dir", help="Install directory")

    p_hosting = sub.add_parser("hosting", help="Set up web hosting for projects")
    p_hosting.add_argument("--domain", help="Domain for hosting (e.g., projects.myweb.com)")
    p_hosting.add_argument("--port", type=int, default=8880, help="Hosting port (default 8880)")
    p_hosting.add_argument("--dir", help="Install directory")

    args = parser.parse_args()
    cmd = args.cmd or "install"
    if cmd == "install":
        if getattr(args, "quick", False):
            sys.exit(cmd_install_quick(args))
        cmd_install(args)
    elif cmd == "status":
        cmd_status(args)
    elif cmd == "uninstall":
        cmd_uninstall(args)
    elif cmd == "restart":
        cmd_restart(args)
    elif cmd == "logs":
        cmd_logs(args)
    elif cmd == "backup":
        cmd_backup(args)
    elif cmd == "config":
        cmd_config(args)
    elif cmd == "update":
        cmd_update(args)
    elif cmd == "hosting":
        cmd_hosting(args)


if __name__ == "__main__":
    main()
