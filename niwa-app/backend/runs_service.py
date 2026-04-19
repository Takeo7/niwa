"""Runs service — PR-04 Niwa v0.2.

Manages the lifecycle of ``backend_runs``: creation, status transitions,
heartbeat updates, event logging, and linking (fallback / resume / retry).
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import state_machines

logger = logging.getLogger(__name__)

# ── Filesystem snapshot / diff (FIX-20260420) ──────────────────────
#
# Completion detection now cross-checks stream events against an
# objective filesystem delta. A run that emits zero tool_use events
# but has a non-empty diff over the project directory has clearly done
# work (Bug 35 root cause — see brief).
#
# Paths ignored by default. Keeps repeated runs from flooding the diff
# with git metadata, interpreter caches, deploy output, etc. Rooted
# components — matched by basename or any path segment.
_DEFAULT_SNAPSHOT_EXCLUDES: tuple[str, ...] = (
    ".niwa",          # run-scoped logs live here (artifact_root subtree)
    ".git",
    ".DS_Store",
    "__pycache__",
    "node_modules",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".next",
    ".turbo",
    "dist",
    "build",
)

# Hard limit on files a single snapshot will hash. Above this we stop,
# log a warning, and mark the snapshot truncated. The run is not
# aborted — completion detection still works, just with reduced
# confidence in the "no files changed" branch.
SNAPSHOT_MAX_FILES = 10_000


def _snapshot_path_excluded(rel_parts: tuple[str, ...],
                            excludes: tuple[str, ...]) -> bool:
    """True if any segment of *rel_parts* matches an exclude token."""
    ex = set(excludes)
    return any(part in ex for part in rel_parts)


def snapshot_directory(
    path: str | Path,
    *,
    excludes: tuple[str, ...] | list[str] | None = None,
    max_files: int = SNAPSHOT_MAX_FILES,
) -> dict:
    """Return a ``{relative_path: sha256}`` mapping for every file
    under *path*, plus metadata about the scan.

    Deterministic: sorted by relative path. Uses forward slashes so the
    output is stable across Windows/POSIX for the unlikely case a dev
    machine round-trips a snapshot.

    Returns a dict with shape::

        {
            "root": "<absolute resolved path>",
            "files": {"rel/path": "<sha256 hex>", ...},
            "truncated": bool,
            "file_count": int,
            "missing": bool,  # True when path does not exist / not a dir
        }

    Non-existent roots return ``missing=True`` with an empty ``files``
    mapping — callers can diff against them safely to detect the case
    "project directory was created during the run".
    """
    exc = tuple(excludes) if excludes is not None else _DEFAULT_SNAPSHOT_EXCLUDES
    root = Path(path)
    out: dict[str, str] = {}
    truncated = False

    try:
        resolved = root.resolve(strict=False)
    except OSError:
        resolved = root

    if not root.exists() or not root.is_dir():
        return {
            "root": str(resolved),
            "files": {},
            "truncated": False,
            "file_count": 0,
            "missing": True,
        }

    count = 0
    # ``rglob('*')`` gives a depth-first, alphabetical iteration on
    # POSIX — deterministic enough for the diff callers, which sort
    # again anyway.
    for entry in sorted(root.rglob("*")):
        if not entry.is_file():
            continue
        try:
            rel = entry.relative_to(root)
        except ValueError:
            # symlink escape or similar — skip silently; not our
            # responsibility to resolve.
            continue
        rel_parts = rel.parts
        if _snapshot_path_excluded(rel_parts, exc):
            continue
        if count >= max_files:
            truncated = True
            logger.warning(
                "snapshot_directory: truncated at %d files for root=%s",
                max_files, resolved,
            )
            break
        try:
            h = hashlib.sha256(entry.read_bytes()).hexdigest()
        except OSError as e:
            # Unreadable file (permissions, symlink to nowhere, special
            # file) — log and skip. A caller that needs to know should
            # call with the file explicitly listed.
            logger.debug(
                "snapshot_directory: skipping %s: %s", entry, e,
            )
            continue
        # Forward-slash the key so diffs compare cleanly across
        # platforms. pathlib gives '/' on POSIX already; this is
        # defensive for tests that may run on Windows CI in the future.
        key = "/".join(rel_parts)
        out[key] = h
        count += 1

    return {
        "root": str(resolved),
        "files": out,
        "truncated": truncated,
        "file_count": count,
        "missing": False,
    }


def diff_snapshots(before: dict, after: dict) -> dict:
    """Compute added/modified/removed between two snapshots.

    Accepts either the full snapshot dict returned by
    :func:`snapshot_directory` or just the ``files`` mapping. Returns::

        {
            "added":    [relpath, ...],
            "modified": [relpath, ...],
            "removed":  [relpath, ...],
        }

    All lists are sorted alphabetically so the diff is deterministic
    across runs.
    """
    before_files = before.get("files", before) if isinstance(before, dict) else {}
    after_files = after.get("files", after) if isinstance(after, dict) else {}

    before_keys = set(before_files.keys())
    after_keys = set(after_files.keys())

    added = sorted(after_keys - before_keys)
    removed = sorted(before_keys - after_keys)
    modified = sorted(
        k for k in (before_keys & after_keys)
        if before_files[k] != after_files[k]
    )
    return {"added": added, "modified": modified, "removed": removed}


def diff_is_nonempty(diff: dict) -> bool:
    """True when the diff contains at least one added/modified/removed entry."""
    return bool(diff.get("added") or diff.get("modified") or diff.get("removed"))


def register_artifacts_from_diff(
    task_id: str,
    run_id: str,
    diff: dict,
    project_directory: str | Path,
    conn,
    *,
    after_snapshot: dict | None = None,
) -> int:
    """Persist ``artifacts`` rows for every file in *diff*.

    ``artifact_type`` is set to ``added`` / ``modified`` / ``removed``.
    When ``after_snapshot`` is provided, ``sha256`` and ``size_bytes``
    are filled in for added/modified entries by looking at the on-disk
    file. Removed entries carry ``size_bytes=NULL, sha256=NULL``.

    Returns the number of artifacts inserted.
    """
    project_root = Path(project_directory)
    after_files = (after_snapshot or {}).get("files") if after_snapshot else None
    inserted = 0

    def _stat_pair(rel: str) -> tuple[int | None, str | None]:
        if after_files and rel in after_files:
            sha = after_files[rel]
        else:
            sha = None
        try:
            size = (project_root / rel).stat().st_size
        except OSError:
            size = None
        return size, sha

    for rel in diff.get("added", []):
        size, sha = _stat_pair(rel)
        register_artifact(
            task_id=task_id, run_id=run_id, artifact_type="added",
            path=rel, conn=conn, size_bytes=size, sha256=sha,
        )
        inserted += 1
    for rel in diff.get("modified", []):
        size, sha = _stat_pair(rel)
        register_artifact(
            task_id=task_id, run_id=run_id, artifact_type="modified",
            path=rel, conn=conn, size_bytes=size, sha256=sha,
        )
        inserted += 1
    for rel in diff.get("removed", []):
        register_artifact(
            task_id=task_id, run_id=run_id, artifact_type="removed",
            path=rel, conn=conn, size_bytes=None, sha256=None,
        )
        inserted += 1
    return inserted


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def create_run(task_id: str, routing_decision_id: str,
               backend_profile_id: str, conn, *,
               previous_run_id: str | None = None,
               relation_type: str | None = None,
               backend_kind: str | None = None,
               runtime_kind: str | None = None,
               model_resolved: str | None = None,
               artifact_root: str | None = None) -> dict:
    """Create a new ``backend_run`` record with status 'queued'.

    Returns the created row as a dict.
    """
    run_id = str(uuid.uuid4())
    now = _now_iso()

    conn.execute(
        "INSERT INTO backend_runs "
        "(id, task_id, routing_decision_id, previous_run_id, relation_type, "
        " backend_profile_id, backend_kind, runtime_kind, model_resolved, "
        " session_handle, status, capability_snapshot_json, budget_snapshot_json, "
        " observed_usage_signals_json, heartbeat_at, started_at, finished_at, "
        " outcome, exit_code, error_code, artifact_root, created_at, updated_at) "
        "VALUES (?,?,?,?,?, ?,?,?,?, NULL,'queued',NULL,NULL, NULL,NULL,NULL,NULL, "
        "        NULL,NULL,NULL,?, ?,?)",
        (
            run_id, task_id, routing_decision_id, previous_run_id,
            relation_type, backend_profile_id, backend_kind, runtime_kind,
            model_resolved, artifact_root, now, now,
        ),
    )
    conn.commit()
    logger.info("Created backend_run %s for task %s (status=queued)", run_id, task_id)

    return _get_run(run_id, conn)


def transition_run(run_id: str, new_status: str, conn, **kwargs) -> dict:
    """Transition a run to *new_status*, enforcing the state machine.

    Optional keyword arguments are written as column updates:
      - session_handle, outcome, exit_code, error_code, started_at, finished_at,
        observed_usage_signals_json
    """
    row = _get_run(run_id, conn)
    old_status = row["status"]
    state_machines.assert_run_transition(old_status, new_status)

    now = _now_iso()
    sets = ["status = ?", "updated_at = ?"]
    params: list = [new_status, now]

    allowed_columns = {
        "session_handle", "outcome", "exit_code", "error_code",
        "started_at", "finished_at", "observed_usage_signals_json",
    }
    for col, val in kwargs.items():
        if col in allowed_columns:
            sets.append(f"{col} = ?")
            params.append(val)

    params.append(run_id)
    conn.execute(
        f"UPDATE backend_runs SET {', '.join(sets)} WHERE id = ?",
        params,
    )
    conn.commit()
    logger.info("Run %s: %s → %s", run_id, old_status, new_status)

    return _get_run(run_id, conn)


def record_heartbeat(run_id: str, conn) -> None:
    """Update ``heartbeat_at`` for a running execution."""
    now = _now_iso()
    conn.execute(
        "UPDATE backend_runs SET heartbeat_at = ?, updated_at = ? WHERE id = ?",
        (now, now, run_id),
    )
    conn.commit()


def record_event(run_id: str, event_type: str, conn, *,
                 message: str | None = None,
                 payload_json: str | None = None) -> str:
    """Insert a row into ``backend_run_events``.

    Returns the event id.
    """
    event_id = str(uuid.uuid4())
    now = _now_iso()
    conn.execute(
        "INSERT INTO backend_run_events "
        "(id, backend_run_id, event_type, message, payload_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (event_id, run_id, event_type, message, payload_json, now),
    )
    conn.commit()
    return event_id


def finish_run(run_id: str, outcome: str, conn, *,
               exit_code: int | None = None,
               error_code: str | None = None,
               observed_usage_signals_json: str | None = None) -> dict:
    """Mark a run as finished with the given outcome.

    Determines the terminal status from outcome:
      - 'success' → 'succeeded'
      - 'failure' → 'failed'
      - 'cancelled' → 'cancelled'
      - 'timed_out' → 'timed_out'
    """
    outcome_to_status = {
        "success": "succeeded",
        "failure": "failed",
        "cancelled": "cancelled",
        "timed_out": "timed_out",
        # Bug 32 fix: Claude sale exit 0 y responde solo con texto
        # (sin tool_use) en tareas ejecutivas → la task queda a la
        # espera de que el user aclare la especificación.
        "needs_clarification": "waiting_input",
    }
    new_status = outcome_to_status.get(outcome)
    if new_status is None:
        raise ValueError(
            f"Unknown outcome {outcome!r}. "
            f"Valid: {sorted(outcome_to_status)}"
        )

    return transition_run(
        run_id, new_status, conn,
        outcome=outcome,
        exit_code=exit_code,
        error_code=error_code,
        finished_at=_now_iso(),
        observed_usage_signals_json=observed_usage_signals_json,
    )


def register_artifact(task_id: str, run_id: str, artifact_type: str,
                      path: str, conn, *,
                      size_bytes: int | None = None,
                      sha256: str | None = None) -> str:
    """Insert a row into the ``artifacts`` table. Returns the artifact id."""
    artifact_id = str(uuid.uuid4())
    now = _now_iso()
    conn.execute(
        "INSERT INTO artifacts "
        "(id, task_id, backend_run_id, artifact_type, path, size_bytes, sha256, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (artifact_id, task_id, run_id, artifact_type, path, size_bytes, sha256, now),
    )
    conn.commit()
    return artifact_id


def update_session_handle(run_id: str, session_handle: str, conn) -> None:
    """Set the ``session_handle`` column on a run.

    Used by the adapter to persist the CLI session id after the run
    has already transitioned to 'running' (running→running is not
    a valid state transition, so we update the column directly).
    """
    now = _now_iso()
    conn.execute(
        "UPDATE backend_runs SET session_handle = ?, updated_at = ? WHERE id = ?",
        (session_handle, now, run_id),
    )
    conn.commit()


def _get_run(run_id: str, conn) -> dict:
    """Fetch a single backend_run as a dict. Raises if not found."""
    row = conn.execute(
        "SELECT * FROM backend_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"backend_run not found: {run_id}")
    return dict(row)


# ── Read-only query helpers for the Web UI (PR-10a) ─────────────────
#
# These helpers return rich dicts joined with backend_profiles so the
# UI can render slugs and display names without a second round-trip.
# They are pure reads — no writes, no side-effects.


def _run_row_to_api(row: dict) -> dict:
    """Normalise a backend_runs row for the HTTP API.

    Exposes profile slug/display_name inline (via join) and leaves
    JSON blob columns as their raw string form for the caller to
    parse client-side.
    """
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "routing_decision_id": row.get("routing_decision_id"),
        "previous_run_id": row.get("previous_run_id"),
        "relation_type": row.get("relation_type"),
        "backend_profile_id": row.get("backend_profile_id"),
        "backend_profile_slug": row.get("backend_profile_slug"),
        "backend_profile_display_name": row.get("backend_profile_display_name"),
        "backend_kind": row.get("backend_kind"),
        "runtime_kind": row.get("runtime_kind"),
        "model_resolved": row.get("model_resolved"),
        "session_handle": row.get("session_handle"),
        "status": row["status"],
        "outcome": row.get("outcome"),
        "exit_code": row.get("exit_code"),
        "error_code": row.get("error_code"),
        "artifact_root": row.get("artifact_root"),
        "heartbeat_at": row.get("heartbeat_at"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "observed_usage_signals_json": row.get("observed_usage_signals_json"),
        "capability_snapshot_json": row.get("capability_snapshot_json"),
        "budget_snapshot_json": row.get("budget_snapshot_json"),
    }


def list_runs_for_task(task_id: str, conn) -> list[dict]:
    """Return all backend_runs for a task, oldest first.

    Each row includes the backend_profile slug and display_name
    joined in.  Safe to return as-is over HTTP.
    """
    rows = conn.execute(
        "SELECT br.*, "
        "       bp.slug AS backend_profile_slug, "
        "       bp.display_name AS backend_profile_display_name "
        "FROM backend_runs br "
        "LEFT JOIN backend_profiles bp "
        "       ON bp.id = br.backend_profile_id "
        "WHERE br.task_id = ? "
        "ORDER BY br.created_at ASC",
        (task_id,),
    ).fetchall()
    return [_run_row_to_api(dict(r)) for r in rows]


def get_run_detail(run_id: str, conn) -> dict | None:
    """Return a single backend_run joined with its backend_profile.

    Returns None if the run doesn't exist.
    """
    row = conn.execute(
        "SELECT br.*, "
        "       bp.slug AS backend_profile_slug, "
        "       bp.display_name AS backend_profile_display_name "
        "FROM backend_runs br "
        "LEFT JOIN backend_profiles bp "
        "       ON bp.id = br.backend_profile_id "
        "WHERE br.id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return _run_row_to_api(dict(row))


def list_events_for_run(run_id: str, conn, *,
                        limit: int | None = None) -> list[dict]:
    """Return backend_run_events for a run, oldest first.

    Optional ``limit`` caps the number of events returned.  When
    omitted, returns all events (UI paginates client-side).
    """
    # ``created_at`` truncates to whole seconds, so events emitted in
    # rapid succession would tie.  ``rowid`` is SQLite's intrinsic
    # insertion order — stable secondary sort.
    sql = (
        "SELECT id, backend_run_id, event_type, message, "
        "       payload_json, created_at "
        "FROM backend_run_events "
        "WHERE backend_run_id = ? "
        "ORDER BY created_at ASC, rowid ASC"
    )
    params: list = [run_id]
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def list_artifacts_for_run(run_id: str, conn) -> list[dict]:
    """Return all ``artifacts`` registered for a run, oldest first.

    Rows are returned as plain dicts.  ``path`` is the value stored in
    the DB (relative to ``artifact_root`` as set by the adapter per
    PR-04 Decisión 10) — the caller MUST NOT expose the absolute host
    path; only the relative path travels to the UI.

    Ordering mirrors ``list_events_for_run``: ``created_at ASC, rowid
    ASC``.  ``created_at`` truncates to whole seconds, so ``rowid`` is
    the stable tie-breaker for files registered inside the same scan.
    """
    rows = conn.execute(
        "SELECT id, task_id, backend_run_id, artifact_type, path, "
        "       size_bytes, sha256, created_at "
        "FROM artifacts "
        "WHERE backend_run_id = ? "
        "ORDER BY created_at ASC, rowid ASC",
        (run_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_routing_decision_for_task(task_id: str, conn) -> dict | None:
    """Return the most recent routing_decision for a task.

    Includes the selected backend profile's slug/display_name and any
    pending approval_id linked to the task (for PR-10b's approvals
    view to pick up).  Returns None if no decision exists.

    Does NOT go through ``assistant_service._tool_run_explain`` — that
    function is affected by Bug 11 (reads ``reason_summary_json``
    instead of ``reason_summary``).  We read the column directly so
    the UI gets real data.
    """
    row = conn.execute(
        "SELECT rd.*, "
        "       bp.slug AS selected_backend_slug, "
        "       bp.display_name AS selected_backend_display_name "
        "FROM routing_decisions rd "
        "LEFT JOIN backend_profiles bp "
        "       ON bp.id = rd.selected_profile_id "
        "WHERE rd.task_id = ? "
        "ORDER BY rd.created_at DESC "
        "LIMIT 1",
        (task_id,),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)

    matched_rules: list = []
    if d.get("matched_rules_json"):
        try:
            matched_rules = json.loads(d["matched_rules_json"])
        except (json.JSONDecodeError, TypeError):
            matched_rules = []

    fallback_chain_ids: list[str] = []
    if d.get("fallback_chain_json"):
        try:
            fallback_chain_ids = json.loads(d["fallback_chain_json"])
        except (json.JSONDecodeError, TypeError):
            fallback_chain_ids = []

    # Resolve fallback chain ids → [{id, slug, display_name}]
    fallback_chain: list[dict] = []
    if fallback_chain_ids:
        placeholders = ",".join("?" * len(fallback_chain_ids))
        profile_rows = conn.execute(
            f"SELECT id, slug, display_name FROM backend_profiles "
            f"WHERE id IN ({placeholders})",
            fallback_chain_ids,
        ).fetchall()
        by_id = {r["id"]: dict(r) for r in profile_rows}
        for pid in fallback_chain_ids:
            entry = by_id.get(pid)
            if entry is None:
                # Profile was deleted — still report the id so the UI
                # can show "unknown profile <id>".
                fallback_chain.append({
                    "id": pid,
                    "slug": None,
                    "display_name": None,
                })
            else:
                fallback_chain.append({
                    "id": entry["id"],
                    "slug": entry["slug"],
                    "display_name": entry["display_name"],
                })

    # Find the most recent pending approval linked to this task (PR-10b
    # will render the detail — for PR-10a we just surface the id).
    approval_row = conn.execute(
        "SELECT id, status, approval_type, risk_level, reason, "
        "       requested_at, resolved_at "
        "FROM approvals "
        "WHERE task_id = ? "
        "ORDER BY requested_at DESC "
        "LIMIT 1",
        (task_id,),
    ).fetchone()
    approval = dict(approval_row) if approval_row else None

    return {
        "id": d["id"],
        "task_id": d["task_id"],
        "decision_index": d.get("decision_index"),
        "requested_profile_id": d.get("requested_profile_id"),
        "selected_profile_id": d.get("selected_profile_id"),
        "selected_backend_slug": d.get("selected_backend_slug"),
        "selected_backend_display_name": d.get("selected_backend_display_name"),
        "reason_summary": d.get("reason_summary") or "",
        "matched_rules": matched_rules,
        "fallback_chain": fallback_chain,
        "estimated_resource_cost": d.get("estimated_resource_cost"),
        "quota_risk": d.get("quota_risk"),
        "contract_version": d.get("contract_version"),
        "created_at": d["created_at"],
        "approval_required": bool(
            approval and approval.get("status") == "pending"
        ),
        "approval": approval,
    }
