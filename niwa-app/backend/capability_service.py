"""Capability service — PR-05 Niwa v0.2.

Manages ``project_capability_profiles`` and enforces security /
resource constraints before and during execution.

Two evaluation levels:
  - **Pre-execution** (``evaluate``): checks static constraints like
    ``quota_risk`` and ``estimated_resource_cost`` against the profile's
    ``resource_budget_json``.  These fields are populated by PR-06
    (deterministic router); until then, triggers are no-op.
  - **Runtime** (``evaluate_runtime_event``): inspects each ``tool_use``
    event from the Claude stream-json and checks against shell whitelist,
    filesystem scope, network/web mode, deletion commands, and repo mode.
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Default "standard" capability profile ────────────────────────
# Used as fallback when no project-specific profile exists in the DB.

DEFAULT_CAPABILITY_PROFILE = {
    "name": "standard",
    "repo_mode": "read-write",
    "shell_mode": "whitelist",
    "web_mode": "off",
    "network_mode": "off",
    "filesystem_scope_json": json.dumps({"allow": ["<workspace>"], "deny": []}),
    "secrets_scope_json": json.dumps({"allow": []}),
    "resource_budget_json": json.dumps({"max_cost_usd": 5.0, "max_duration_ms": 600000}),
}

# Shell commands allowed in "whitelist" mode.  The list is intentionally
# minimal (read-only, non-destructive).  Future PRs may store per-project
# whitelists in a dedicated column; for now this constant is authoritative.
DEFAULT_SHELL_WHITELIST = frozenset(["ls", "cat", "grep", "find"])

# Commands that imply file/directory deletion — always trigger approval
# regardless of shell_mode setting.
DELETION_COMMANDS = frozenset(["rm", "rmdir", "unlink", "shred"])

# Commands that imply outbound network access.
NETWORK_COMMANDS = frozenset([
    "curl", "wget", "ssh", "scp", "rsync", "nc", "ncat",
    "telnet", "ftp", "sftp", "ping", "nslookup", "dig",
])


# ── Helpers ──────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_json(raw: str | None) -> dict:
    """Safely parse a JSON string, returning {} on failure."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _extract_commands(command_str: str) -> list[str]:
    """Extract base command names from a shell command string.

    Splits on ``&&``, ``||``, ``;``, ``|`` to find all command bases.
    Returns the basename (no path prefix) of each command.
    """
    if not command_str:
        return []
    parts = re.split(r'\s*(?:[;&|]{1,2})\s*', command_str)
    commands: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if not tokens:
            continue
        # Skip env-var assignments like FOO=bar cmd
        base = tokens[0]
        for t in tokens:
            if "=" not in t or t.startswith("-"):
                base = t
                break
        # Strip path prefix
        base = base.rsplit("/", 1)[-1]
        if base:
            commands.append(base)
    return commands


# ── Profile retrieval ────────────────────────────────────────────

def get_effective_profile(project_id: str | None, conn) -> dict:
    """Return the capability profile for *project_id*.

    If the project has a row in ``project_capability_profiles``, returns
    it as a dict.  Otherwise falls back to ``DEFAULT_CAPABILITY_PROFILE``.
    """
    if project_id and conn:
        row = conn.execute(
            "SELECT * FROM project_capability_profiles "
            "WHERE project_id = ? ORDER BY created_at LIMIT 1",
            (project_id,),
        ).fetchone()
        if row:
            return dict(row)
    return dict(DEFAULT_CAPABILITY_PROFILE)


# ── Seed ─────────────────────────────────────────────────────────

def seed_capability_profiles(conn) -> int:
    """Insert a ``standard`` capability profile for every project that
    doesn't already have one.

    Uses ``INSERT OR IGNORE`` (unique on ``project_id`` + ``name``) so
    this is safe to call on every startup.

    Returns the number of rows actually inserted.
    """
    now = _now_iso()
    projects = conn.execute("SELECT id FROM projects").fetchall()
    inserted = 0

    for proj in projects:
        pid = proj["id"] if isinstance(proj, dict) else proj[0]
        row_id = str(uuid.uuid4())
        cursor = conn.execute(
            "INSERT OR IGNORE INTO project_capability_profiles "
            "(id, project_id, name, repo_mode, shell_mode, web_mode, "
            " network_mode, filesystem_scope_json, secrets_scope_json, "
            " resource_budget_json, created_at, updated_at) "
            "SELECT ?, ?, 'standard', ?, ?, ?, ?, ?, ?, ?, ?, ? "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM project_capability_profiles "
            "  WHERE project_id = ? AND name = 'standard'"
            ")",
            (
                row_id, pid,
                DEFAULT_CAPABILITY_PROFILE["repo_mode"],
                DEFAULT_CAPABILITY_PROFILE["shell_mode"],
                DEFAULT_CAPABILITY_PROFILE["web_mode"],
                DEFAULT_CAPABILITY_PROFILE["network_mode"],
                DEFAULT_CAPABILITY_PROFILE["filesystem_scope_json"],
                DEFAULT_CAPABILITY_PROFILE["secrets_scope_json"],
                DEFAULT_CAPABILITY_PROFILE["resource_budget_json"],
                now, now,
                pid,
            ),
        )
        if cursor.rowcount > 0:
            inserted += 1
            logger.info("Seeded capability_profile 'standard' for project %s", pid)

    return inserted


# ── Pre-execution evaluation ─────────────────────────────────────

def evaluate(task: dict, run: dict, profile: dict,
             capability_profile: dict) -> dict:
    """Pre-execution evaluation of a task against a capability profile.

    Returns::

        {
            "allowed": bool,
            "reason": str,
            "approval_required": bool,
            "triggers": [{"type": str, "detail": str}, ...],
        }

    Currently checks:
      - ``quota_risk >= medium`` (from task; no-op until PR-06)
      - ``estimated_resource_cost > max_cost_usd`` (no-op until PR-06)

    Both fields are ``None``/``"unknown"`` until the deterministic router
    (PR-06) populates them.
    """
    triggers: list[dict] = []

    # ── quota_risk ───────────────────────────────────────────────
    quota_risk = task.get("quota_risk")
    if quota_risk and quota_risk in ("medium", "high", "critical"):
        triggers.append({
            "type": "quota_risk",
            "detail": f"quota_risk={quota_risk}",
        })

    # ── estimated_resource_cost vs budget ────────────────────────
    resource_budget = _parse_json(
        capability_profile.get("resource_budget_json"),
    )
    max_cost = resource_budget.get("max_cost_usd")
    estimated_cost_str = task.get("estimated_resource_cost")
    if estimated_cost_str is not None and max_cost is not None:
        try:
            estimated_cost = float(estimated_cost_str)
            if estimated_cost > float(max_cost):
                triggers.append({
                    "type": "estimated_resource_cost",
                    "detail": (
                        f"estimated={estimated_cost} > "
                        f"max={max_cost}"
                    ),
                })
        except (ValueError, TypeError):
            pass

    if triggers:
        return {
            "allowed": False,
            "reason": "; ".join(t["detail"] for t in triggers),
            "approval_required": True,
            "triggers": triggers,
        }

    return {
        "allowed": True,
        "reason": "Pre-execution checks passed",
        "approval_required": False,
        "triggers": [],
    }


# ── Runtime evaluation ───────────────────────────────────────────

def evaluate_runtime_event(event: dict, capability_profile: dict,
                           *, workspace_path: str | None = None) -> dict:
    """Evaluate a single stream-json event against the capability profile.

    Only ``tool_use`` events are checked; all others pass immediately.

    Returns::

        {
            "allowed": bool,
            "reason": str,
            "approval_required": bool,
            "triggers": [{"type": str, "detail": str}, ...],
        }
    """
    if not isinstance(event, dict) or event.get("type") != "tool_use":
        return {
            "allowed": True,
            "reason": "Not a tool_use event",
            "approval_required": False,
            "triggers": [],
        }

    tool_name = event.get("name", event.get("tool", ""))
    tool_input = event.get("input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    triggers: list[dict] = []

    # ── Bash tool_use ────────────────────────────────────────────
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        commands = _extract_commands(command)

        # Shell mode check
        shell_trigger = _check_shell_whitelist(commands, capability_profile)
        if shell_trigger:
            triggers.append(shell_trigger)

        # Deletion check (independent of shell whitelist)
        deletion_trigger = _check_deletion(commands)
        if deletion_trigger:
            triggers.append(deletion_trigger)

        # Network command check
        network_trigger = _check_network_commands(
            commands, capability_profile,
        )
        if network_trigger:
            triggers.append(network_trigger)

    # ── Write / Edit tool_use ────────────────────────────────────
    elif tool_name in ("Write", "Edit"):
        file_path = tool_input.get("file_path", tool_input.get("path", ""))

        # Repo mode check
        repo_trigger = _check_repo_mode(capability_profile)
        if repo_trigger:
            triggers.append(repo_trigger)

        # Filesystem scope check
        fs_trigger = _check_filesystem_scope(
            file_path, capability_profile, workspace_path,
        )
        if fs_trigger:
            triggers.append(fs_trigger)

    # ── WebFetch / WebSearch ─────────────────────────────────────
    elif tool_name in ("WebFetch", "WebSearch"):
        web_trigger = _check_web_mode(capability_profile)
        if web_trigger:
            triggers.append(web_trigger)

        net_trigger = _check_network_mode(capability_profile)
        if net_trigger:
            triggers.append(net_trigger)

    if triggers:
        return {
            "allowed": False,
            "reason": "; ".join(t["detail"] for t in triggers),
            "approval_required": True,
            "triggers": triggers,
        }

    return {
        "allowed": True,
        "reason": "Permitted",
        "approval_required": False,
        "triggers": [],
    }


# ── Internal checkers ────────────────────────────────────────────

def _check_shell_whitelist(commands: list[str],
                           capability_profile: dict) -> dict | None:
    """Check commands against shell_mode policy."""
    shell_mode = capability_profile.get("shell_mode", "whitelist")

    if shell_mode == "disabled":
        return {
            "type": "shell_disabled",
            "detail": "Shell access is disabled by capability profile",
        }

    if shell_mode == "free":
        return None

    # whitelist mode
    for cmd in commands:
        if cmd not in DEFAULT_SHELL_WHITELIST:
            return {
                "type": "shell_not_whitelisted",
                "detail": (
                    f"Command '{cmd}' not in shell whitelist "
                    f"{sorted(DEFAULT_SHELL_WHITELIST)}"
                ),
            }

    return None


def _check_deletion(commands: list[str]) -> dict | None:
    """Check if any command implies file deletion."""
    for cmd in commands:
        if cmd in DELETION_COMMANDS:
            return {
                "type": "deletion",
                "detail": f"Deletion command '{cmd}' requires approval",
            }
    return None


def _check_network_commands(commands: list[str],
                            capability_profile: dict) -> dict | None:
    """Check for network commands when network_mode is off."""
    network_mode = capability_profile.get("network_mode", "off")
    if network_mode == "on":
        return None

    for cmd in commands:
        if cmd in NETWORK_COMMANDS:
            return {
                "type": "network_mode_denied",
                "detail": (
                    f"Network command '{cmd}' denied: "
                    f"network_mode='{network_mode}'"
                ),
            }
    return None


def _check_repo_mode(capability_profile: dict) -> dict | None:
    """Check whether writes are allowed by repo_mode."""
    repo_mode = capability_profile.get("repo_mode", "read-write")
    if repo_mode in ("none", "read-only"):
        return {
            "type": "repo_mode_violation",
            "detail": f"Write denied: repo_mode is '{repo_mode}'",
        }
    return None


def _check_filesystem_scope(file_path: str,
                            capability_profile: dict,
                            workspace_path: str | None) -> dict | None:
    """Check whether a file path is within the allowed filesystem scope."""
    if not file_path:
        return None

    fs_scope = _parse_json(
        capability_profile.get("filesystem_scope_json"),
    )
    allow_paths = fs_scope.get("allow", [])
    deny_paths = fs_scope.get("deny", [])

    # If no scope defined, allow everything
    if not allow_paths and not deny_paths:
        return None

    abs_file = os.path.abspath(file_path)

    # Check deny list first
    for dp in deny_paths:
        abs_deny = os.path.abspath(dp)
        if abs_file == abs_deny or abs_file.startswith(abs_deny + os.sep):
            return {
                "type": "filesystem_write_denied",
                "detail": f"Write to '{file_path}' is in deny list",
            }

    # Resolve <workspace> token and check allow list
    resolved_allow: list[str] = []
    for ap in allow_paths:
        if ap == "<workspace>":
            if workspace_path:
                resolved_allow.append(os.path.abspath(workspace_path))
        else:
            resolved_allow.append(os.path.abspath(ap))

    if not resolved_allow:
        # No resolvable allow paths — can't verify, allow by default
        return None

    for ap in resolved_allow:
        if abs_file == ap or abs_file.startswith(ap + os.sep):
            return None  # Within allowed scope

    return {
        "type": "filesystem_write_outside_scope",
        "detail": (
            f"Write to '{file_path}' is outside allowed "
            f"filesystem scope"
        ),
    }


def _check_web_mode(capability_profile: dict) -> dict | None:
    """Check whether web access is permitted."""
    web_mode = capability_profile.get("web_mode", "off")
    if web_mode == "off":
        return {
            "type": "web_mode_denied",
            "detail": "Web access denied: web_mode='off'",
        }
    return None


def _check_network_mode(capability_profile: dict) -> dict | None:
    """Check whether network access is permitted."""
    network_mode = capability_profile.get("network_mode", "off")
    if network_mode == "off":
        return {
            "type": "network_mode_denied",
            "detail": f"Network access denied: network_mode='{network_mode}'",
        }
    return None
