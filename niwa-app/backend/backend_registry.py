"""Backend registry — PR-03 Niwa v0.2.

Maintains a mapping from backend slug to ``BackendAdapter`` instance.
Provides ``seed_backend_profiles()`` to bootstrap the two initial
profiles (``claude_code``, ``codex``) in the ``backend_profiles`` table.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from backend_adapters.base import BackendAdapter
from backend_adapters.claude_code import ClaudeCodeAdapter
from backend_adapters.codex import CodexAdapter

logger = logging.getLogger(__name__)


class BackendRegistry:
    """Registry of available backend adapters, keyed by slug."""

    def __init__(self) -> None:
        self._adapters: dict[str, BackendAdapter] = {}

    def register(self, slug: str, adapter: BackendAdapter) -> None:
        """Register *adapter* under *slug*.

        Raises ``ValueError`` if *slug* is already registered.
        """
        if slug in self._adapters:
            raise ValueError(f"Backend slug already registered: {slug!r}")
        self._adapters[slug] = adapter

    def resolve(self, slug: str) -> BackendAdapter:
        """Return the adapter registered under *slug*.

        Raises ``KeyError`` if no adapter is registered for *slug*.
        """
        try:
            return self._adapters[slug]
        except KeyError:
            raise KeyError(
                f"No backend adapter registered for slug {slug!r}. "
                f"Available: {sorted(self._adapters)}"
            )

    def list_slugs(self) -> list[str]:
        """Return sorted list of registered backend slugs."""
        return sorted(self._adapters)

    def all(self) -> dict[str, BackendAdapter]:
        """Return a copy of the internal registry dict."""
        return dict(self._adapters)


# ── Module-level default registry ────────────────────────────────────

_default_registry: BackendRegistry | None = None


def get_default_registry() -> BackendRegistry:
    """Return (and lazily create) the process-wide default registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = BackendRegistry()
        _default_registry.register("claude_code", ClaudeCodeAdapter())
        _default_registry.register("codex", CodexAdapter())
    return _default_registry


# ── Seed backend_profiles rows ───────────────────────────────────────

_SEED_PROFILES: list[dict[str, Any]] = [
    {
        "slug": "claude_code",
        "display_name": "Claude Code",
        "backend_kind": "claude_code",
        "runtime_kind": "cli",
        "default_model": "claude-sonnet-4-6",
        "enabled": 1,
        "priority": 10,
    },
    {
        "slug": "codex",
        "display_name": "Codex",
        "backend_kind": "codex",
        "runtime_kind": "cli",
        "default_model": None,
        "enabled": 1,
        "priority": 5,
    },
]


def get_execution_registry(db_conn_factory) -> BackendRegistry:
    """Return a registry with adapters wired to *db_conn_factory*.

    Unlike ``get_default_registry()`` (which creates adapters without
    a DB factory — suitable only for ``capabilities()``), this registry
    creates adapters that can execute real runs with DB persistence.

    Each call creates a fresh registry.  The caller decides the lifecycle
    (e.g. one per executor loop, or singleton in the task-executor process).
    """
    registry = BackendRegistry()
    registry.register("claude_code", ClaudeCodeAdapter(db_conn_factory=db_conn_factory))
    registry.register("codex", CodexAdapter(db_conn_factory=db_conn_factory))
    return registry


def seed_backend_profiles(conn) -> int:
    """Insert seed backend profiles if they don't already exist.

    Uses ``INSERT OR IGNORE`` keyed on ``slug`` (UNIQUE) so this is
    safe to call on every startup — existing rows are never overwritten.

    After inserting, calls ``upgrade_codex_profile()`` to enable codex
    on existing installs that still have the old defaults (PR-07).

    *conn* must be a ``sqlite3.Connection`` with WAL/FK pragmas already
    set.  The caller is responsible for committing.

    Returns the number of rows actually inserted.
    """
    registry = get_default_registry()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    inserted = 0

    for profile in _SEED_PROFILES:
        slug = profile["slug"]
        adapter = registry.resolve(slug)
        caps_json = json.dumps(adapter.capabilities())
        row_id = str(uuid.uuid4())

        cursor = conn.execute(
            "INSERT OR IGNORE INTO backend_profiles "
            "(id, slug, display_name, backend_kind, runtime_kind, "
            " default_model, command_template, capabilities_json, "
            " enabled, priority, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)",
            (
                row_id,
                slug,
                profile["display_name"],
                profile["backend_kind"],
                profile["runtime_kind"],
                profile["default_model"],
                caps_json,
                profile["enabled"],
                profile["priority"],
                now,
                now,
            ),
        )
        if cursor.rowcount > 0:
            inserted += 1
            logger.info("Seeded backend_profile: %s", slug)

    # PR-07: upgrade codex from old defaults to enabled
    upgrade_codex_profile(conn)

    return inserted


# ── PR-10d: read + patch helpers ─────────────────────────────────

# Fields the UI is allowed to change in PATCH /api/backend-profiles/:id.
# ``capabilities_json`` and ``command_template`` are read-only in v0.2
# (editing them requires shape validation beyond the scope of PR-10d).
UPDATABLE_BACKEND_PROFILE_FIELDS = (
    "enabled", "priority", "default_model",
)


def list_backend_profiles(conn) -> list[dict]:
    """Return all backend_profiles rows ordered by priority DESC, slug ASC.

    The ordering matches what the routing service considers when
    resolving defaults (highest priority wins).
    """
    rows = conn.execute(
        "SELECT * FROM backend_profiles "
        "ORDER BY priority DESC, slug ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_backend_profile(profile_id: str, conn) -> dict | None:
    row = conn.execute(
        "SELECT * FROM backend_profiles WHERE id = ?", (profile_id,),
    ).fetchone()
    return dict(row) if row else None


def validate_backend_profile_patch(payload: dict) -> dict | None:
    """Validate a partial backend_profile PATCH payload.

    Returns ``None`` when valid, or ``{"error": code, "field": name,
    "message": human}``.
    """
    if not isinstance(payload, dict):
        return {"error": "invalid_payload", "field": None,
                "message": "payload must be a JSON object"}

    for key in payload:
        if key not in UPDATABLE_BACKEND_PROFILE_FIELDS:
            return {"error": "unknown_field", "field": key,
                    "message": f"field {key!r} is not editable"}

    if "enabled" in payload:
        v = payload["enabled"]
        # Reject non-boolean values — integer coercion would mask typos.
        if not isinstance(v, bool):
            return {"error": "invalid_type", "field": "enabled",
                    "message": "enabled must be boolean"}

    if "priority" in payload:
        v = payload["priority"]
        # bool is a subclass of int in Python — reject explicitly.
        if isinstance(v, bool) or not isinstance(v, int):
            return {"error": "invalid_type", "field": "priority",
                    "message": "priority must be integer"}

    if "default_model" in payload:
        v = payload["default_model"]
        if v is not None and not isinstance(v, str):
            return {"error": "invalid_type", "field": "default_model",
                    "message": "default_model must be string or null"}
        if isinstance(v, str) and len(v) > 200:
            return {"error": "invalid_length", "field": "default_model",
                    "message": "default_model too long (>200 chars)"}

    return None


def update_backend_profile(profile_id: str, payload: dict, conn) -> dict:
    """Apply a validated PATCH payload to a backend_profile row.

    The caller MUST validate *payload* first via
    ``validate_backend_profile_patch()``.

    Raises ``LookupError`` if the row does not exist.
    Returns the updated row as a dict.
    """
    existing = get_backend_profile(profile_id, conn)
    if existing is None:
        raise LookupError(f"backend_profile {profile_id!r} not found")

    if not payload:
        return existing

    # Normalize values: bool → 0/1 for enabled.
    normalized: dict[str, Any] = {}
    for k, v in payload.items():
        if k == "enabled":
            normalized[k] = 1 if v else 0
        else:
            normalized[k] = v

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sets = [f"{k} = ?" for k in normalized]
    values = list(normalized.values())
    sets.append("updated_at = ?")
    values.append(now)
    values.append(profile_id)

    conn.execute(
        f"UPDATE backend_profiles SET {', '.join(sets)} WHERE id = ?",
        values,
    )

    # PR-10d audit: stdout placeholder until a dedicated audit table
    # exists.  Captures old→new per edited field for traceability.
    for field, new_value in payload.items():
        old_value = existing.get(field)
        logger.info(
            "AUDIT backend_profile.%s %s: %r → %r",
            field, profile_id, old_value, new_value,
        )

    updated = get_backend_profile(profile_id, conn)
    return updated or existing


def upgrade_codex_profile(conn) -> bool:
    """Enable the codex profile for existing installs.

    Only upgrades if the current values are the PR-03 defaults
    (``enabled=0 AND priority=0``).  If the user has manually
    changed either field, their choice is respected.

    Also refreshes ``capabilities_json`` to match the current
    adapter capabilities (``resume_modes`` changed from
    ``["new_session"]`` to ``[]`` in PR-07).

    Returns True if the row was updated.
    """
    registry = get_default_registry()
    adapter = registry.resolve("codex")
    caps_json = json.dumps(adapter.capabilities())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    cursor = conn.execute(
        "UPDATE backend_profiles "
        "SET enabled = 1, priority = 5, "
        "    capabilities_json = ?, updated_at = ? "
        "WHERE slug = 'codex' AND enabled = 0 AND priority = 0",
        (caps_json, now),
    )
    updated = cursor.rowcount > 0
    if updated:
        logger.info("Upgraded codex profile: enabled=1 priority=5")
    return updated
