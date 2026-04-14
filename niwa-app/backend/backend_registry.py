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
