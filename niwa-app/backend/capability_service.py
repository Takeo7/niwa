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

DEFAULT_SHELL_WHITELIST = ["ls", "cat", "grep", "find", "pwd", "echo"]

DEFAULT_CAPABILITY_PROFILE = {
    "name": "standard",
    "repo_mode": "read-write",
    "shell_mode": "whitelist",
    "shell_whitelist_json": json.dumps(DEFAULT_SHELL_WHITELIST),
    "web_mode": "off",
    "network_mode": "off",
    "filesystem_scope_json": json.dumps({"allow": ["<workspace>"], "deny": []}),
    "secrets_scope_json": json.dumps({"allow": []}),
    "resource_budget_json": json.dumps({"max_cost_usd": 5.0, "max_duration_ms": 600000}),
}

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


def _parse_json_list(raw: str | None) -> list | None:
    """Safely parse a JSON string expected to be a list.

    Returns ``None`` on failure so callers can fall back to defaults.
    """
    if not raw:
        return None
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


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

    PR-B3: merges ``projects.autonomy_mode`` into the returned dict so
    downstream ``evaluate*`` functions can short-circuit when the
    operator has opted into dangerous mode for this project. This is
    the single place where the flag is read — callers that build
    profile dicts by hand won't see the bypass.
    """
    profile: dict
    if project_id and conn:
        row = conn.execute(
            "SELECT * FROM project_capability_profiles "
            "WHERE project_id = ? ORDER BY created_at LIMIT 1",
            (project_id,),
        ).fetchone()
        profile = dict(row) if row else dict(DEFAULT_CAPABILITY_PROFILE)
    else:
        profile = dict(DEFAULT_CAPABILITY_PROFILE)

    autonomy_mode = "normal"
    if project_id and conn:
        proj_row = conn.execute(
            "SELECT autonomy_mode FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if proj_row is not None:
            value = proj_row["autonomy_mode"]
            if value in ("normal", "dangerous"):
                autonomy_mode = value
    profile["autonomy_mode"] = autonomy_mode
    return profile


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
            "(id, project_id, name, repo_mode, shell_mode, "
            " shell_whitelist_json, web_mode, "
            " network_mode, filesystem_scope_json, secrets_scope_json, "
            " resource_budget_json, created_at, updated_at) "
            "SELECT ?, ?, 'standard', ?, ?, ?, ?, ?, ?, ?, ?, ?, ? "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM project_capability_profiles "
            "  WHERE project_id = ? AND name = 'standard'"
            ")",
            (
                row_id, pid,
                DEFAULT_CAPABILITY_PROFILE["repo_mode"],
                DEFAULT_CAPABILITY_PROFILE["shell_mode"],
                DEFAULT_CAPABILITY_PROFILE["shell_whitelist_json"],
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


# ── Canonical enum values (PR-10d) ───────────────────────────────
# Exposed so the HTTP layer can validate input against the same
# set the SPEC PR-05 defines.  Keep in sync with SPEC.

REPO_MODES = ("none", "read-only", "read-write")
SHELL_MODES = ("disabled", "whitelist", "free")
WEB_MODES = ("off", "on")
NETWORK_MODES = ("off", "on", "restricted")

# Columns that ``upsert_profile_for_project`` will accept.  Any other
# key in the input dict is rejected as unknown_field by the HTTP layer.
UPDATABLE_CAPABILITY_FIELDS = (
    "repo_mode",
    "shell_mode",
    "web_mode",
    "network_mode",
    "shell_whitelist_json",
    "filesystem_scope_json",
    "secrets_scope_json",
    "resource_budget_json",
)


def validate_capability_input(payload: dict) -> dict | None:
    """Validate a partial ``project_capability_profile`` payload.

    Returns ``None`` when valid, or ``{"error": code, "field": name,
    "message": human}`` describing the first problem found.

    Rules:
      - Unknown fields are rejected (``unknown_field``).
      - ``repo_mode`` ∈ REPO_MODES.
      - ``shell_mode`` ∈ SHELL_MODES.
      - ``web_mode`` ∈ WEB_MODES.
      - ``network_mode`` ∈ NETWORK_MODES.
      - ``shell_whitelist_json`` must parse as a JSON list of strings.
      - ``filesystem_scope_json`` / ``secrets_scope_json`` /
        ``resource_budget_json`` must parse as JSON (any shape).

    ``name`` updates are intentionally out of scope for the editable
    surface — the seeded row is always named ``standard``.
    """
    if not isinstance(payload, dict):
        return {"error": "invalid_payload", "field": None,
                "message": "payload must be a JSON object"}

    for key in payload:
        if key not in UPDATABLE_CAPABILITY_FIELDS:
            return {"error": "unknown_field", "field": key,
                    "message": f"field {key!r} is not editable"}

    enums = {
        "repo_mode": REPO_MODES,
        "shell_mode": SHELL_MODES,
        "web_mode": WEB_MODES,
        "network_mode": NETWORK_MODES,
    }
    for field, allowed in enums.items():
        if field in payload:
            value = payload[field]
            if not isinstance(value, str) or value not in allowed:
                return {"error": "invalid_enum", "field": field,
                        "message": (
                            f"{field!r} must be one of "
                            f"{list(allowed)}, got {value!r}"
                        )}

    if "shell_whitelist_json" in payload:
        value = payload["shell_whitelist_json"]
        parsed = _parse_json_list(value) if isinstance(value, str) else None
        if parsed is None or not all(isinstance(c, str) for c in parsed):
            return {"error": "invalid_json", "field": "shell_whitelist_json",
                    "message": ("shell_whitelist_json must be a JSON "
                                "array of strings")}

    for json_field in ("filesystem_scope_json",
                       "secrets_scope_json",
                       "resource_budget_json"):
        if json_field in payload:
            value = payload[json_field]
            if not isinstance(value, str):
                return {"error": "invalid_json", "field": json_field,
                        "message": f"{json_field} must be a JSON string"}
            try:
                json.loads(value)
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                return {"error": "invalid_json", "field": json_field,
                        "message": f"{json_field} is not valid JSON: {e}"}

    return None


def upsert_profile_for_project(project_id: str, payload: dict, conn) -> dict:
    """Upsert the capability profile row for *project_id*.

    If no row exists, one is created from ``DEFAULT_CAPABILITY_PROFILE``
    with the fields in *payload* layered on top.  If a row exists,
    only the fields in *payload* are updated.

    Callers MUST validate *payload* first via
    ``validate_capability_input()`` — this function assumes it's valid.

    Returns the resulting row as a dict.
    Raises ``LookupError`` if *project_id* does not exist in projects.
    """
    proj = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,),
    ).fetchone()
    if not proj:
        raise LookupError(f"project {project_id!r} not found")

    now = _now_iso()
    existing = conn.execute(
        "SELECT * FROM project_capability_profiles "
        "WHERE project_id = ? ORDER BY created_at LIMIT 1",
        (project_id,),
    ).fetchone()

    if existing is None:
        merged = {
            "repo_mode": DEFAULT_CAPABILITY_PROFILE["repo_mode"],
            "shell_mode": DEFAULT_CAPABILITY_PROFILE["shell_mode"],
            "shell_whitelist_json": DEFAULT_CAPABILITY_PROFILE[
                "shell_whitelist_json"
            ],
            "web_mode": DEFAULT_CAPABILITY_PROFILE["web_mode"],
            "network_mode": DEFAULT_CAPABILITY_PROFILE["network_mode"],
            "filesystem_scope_json": DEFAULT_CAPABILITY_PROFILE[
                "filesystem_scope_json"
            ],
            "secrets_scope_json": DEFAULT_CAPABILITY_PROFILE[
                "secrets_scope_json"
            ],
            "resource_budget_json": DEFAULT_CAPABILITY_PROFILE[
                "resource_budget_json"
            ],
        }
        merged.update(payload)
        row_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO project_capability_profiles "
            "(id, project_id, name, repo_mode, shell_mode, "
            " shell_whitelist_json, web_mode, network_mode, "
            " filesystem_scope_json, secrets_scope_json, "
            " resource_budget_json, created_at, updated_at) "
            "VALUES (?, ?, 'standard', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row_id, project_id,
                merged["repo_mode"], merged["shell_mode"],
                merged["shell_whitelist_json"],
                merged["web_mode"], merged["network_mode"],
                merged["filesystem_scope_json"],
                merged["secrets_scope_json"],
                merged["resource_budget_json"],
                now, now,
            ),
        )
        logger.info(
            "Created capability_profile for project %s from defaults "
            "(fields overridden: %s)",
            project_id, sorted(payload),
        )
    else:
        if payload:
            sets = [f"{k} = ?" for k in payload]
            values = list(payload.values())
            sets.append("updated_at = ?")
            values.append(now)
            values.append(existing["id"])
            conn.execute(
                f"UPDATE project_capability_profiles "
                f"SET {', '.join(sets)} WHERE id = ?",
                values,
            )
            logger.info(
                "Updated capability_profile %s for project %s "
                "(fields: %s)",
                existing["id"], project_id, sorted(payload),
            )

    row = conn.execute(
        "SELECT * FROM project_capability_profiles "
        "WHERE project_id = ? ORDER BY created_at LIMIT 1",
        (project_id,),
    ).fetchone()
    return dict(row) if row else {}


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

    PR-B3: when ``capability_profile['autonomy_mode'] == 'dangerous'``
    the gate is bypassed — the operator has explicitly opted into
    unattended execution for this project.
    """
    if capability_profile.get("autonomy_mode") == "dangerous":
        return {
            "allowed": True,
            "reason": "autonomy_mode=dangerous — approval gate bypassed",
            "approval_required": False,
            "triggers": [],
        }

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

    # PR-B3: project-level dangerous mode bypasses all runtime checks.
    if capability_profile.get("autonomy_mode") == "dangerous":
        return {
            "allowed": True,
            "reason": "autonomy_mode=dangerous — approval gate bypassed",
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

    # whitelist mode — read from profile, fall back to default
    whitelist_raw = capability_profile.get("shell_whitelist_json")
    whitelist = _parse_json_list(whitelist_raw) if whitelist_raw else None
    if whitelist is None:
        whitelist = list(DEFAULT_SHELL_WHITELIST)
    whitelist_set = frozenset(whitelist)

    for cmd in commands:
        if cmd not in whitelist_set:
            return {
                "type": "shell_not_whitelisted",
                "detail": (
                    f"Command '{cmd}' not in shell whitelist "
                    f"{sorted(whitelist_set)}"
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

    if not resolved_allow and allow_paths:
        # allow list was defined but couldn't be resolved (e.g.
        # <workspace> without workspace_path) — fail closed.
        return {
            "type": "filesystem_scope_unresolvable",
            "detail": (
                "allow list contains <workspace> but no "
                "workspace_path provided — denying by default"
            ),
        }

    if not resolved_allow:
        # No allow paths defined at all — no scope restriction
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
