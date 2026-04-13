"""Routing service — PR-06 Niwa v0.2.

Deterministic router: matches tasks against ``routing_rules`` and
selects the appropriate ``backend_profile``.  Creates
``routing_decisions`` audit records.

No LLM calls.  The router is purely rule-based.

Evaluation order (deterministic):
  1. Pin explícito  — ``tasks.requested_backend_profile_id``
  2. Capability check — ``capability_service.evaluate()``
  3. Resume-aware   — prior run's backend if it supports resume
  4. Persisted rules — ``routing_rules`` ordered by ``position``
  5. Default         — highest-priority enabled backend
"""

import json
import logging
import uuid
from datetime import datetime, timezone

import approval_service
import capability_service

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ── Matching engine ─────────────────────────────────────────────────


def _match_rule(rule: dict, task: dict) -> bool:
    """Evaluate a single routing rule's ``match_json`` against a task.

    All conditions present in the match dict must be satisfied (AND).
    An empty match dict always matches.
    """
    match_raw = rule.get("match_json")
    if not match_raw:
        return True
    try:
        match = json.loads(match_raw) if isinstance(match_raw, str) else match_raw
    except (json.JSONDecodeError, TypeError):
        return False

    if not match:
        return True

    # Build searchable text from task title + description, lowercased
    text = " ".join(
        filter(None, [task.get("title", ""), task.get("description", "")])
    ).lower()

    word_count = len(text.split()) if text.strip() else 0

    # keywords_any: at least one keyword must be present
    keywords_any = match.get("keywords_any")
    if keywords_any:
        if not any(kw.lower() in text for kw in keywords_any):
            return False

    # keywords_all: all keywords must be present
    keywords_all = match.get("keywords_all")
    if keywords_all:
        if not all(kw.lower() in text for kw in keywords_all):
            return False

    # description_min_words
    min_words = match.get("description_min_words")
    if min_words is not None:
        if word_count < min_words:
            return False

    # description_max_words
    max_words = match.get("description_max_words")
    if max_words is not None:
        if word_count > max_words:
            return False

    # source filter
    source_filter = match.get("source")
    if source_filter is not None:
        if task.get("source") != source_filter:
            return False

    return True


def _resolve_backend_slug(action_json: str | dict, conn) -> str | None:
    """Resolve ``action.backend_slug`` to a ``backend_profile.id``.

    Returns the profile id if the profile exists and is enabled.
    Returns ``None`` if the profile doesn't exist or is disabled.
    """
    try:
        action = json.loads(action_json) if isinstance(action_json, str) else action_json
    except (json.JSONDecodeError, TypeError):
        return None

    slug = action.get("backend_slug")
    if not slug:
        return None

    row = conn.execute(
        "SELECT id, enabled FROM backend_profiles WHERE slug = ?",
        (slug,),
    ).fetchone()
    if not row:
        return None
    if not row["enabled"]:
        return None
    return row["id"]


# ── Fallback chain ──────────────────────────────────────────────────


def _build_fallback_chain(selected_profile_id: str, conn) -> list[str]:
    """Build the fallback chain: selected first, then other enabled
    profiles ordered by priority DESC.

    Returns a list of backend_profile ids.
    """
    chain = [selected_profile_id]
    rows = conn.execute(
        "SELECT id FROM backend_profiles "
        "WHERE enabled = 1 AND id != ? "
        "ORDER BY priority DESC",
        (selected_profile_id,),
    ).fetchall()
    for r in rows:
        chain.append(r["id"])
    return chain


# ── Core decision logic ─────────────────────────────────────────────


def decide(task: dict, conn) -> dict:
    """Evaluate routing rules for *task* and return a routing decision.

    Idempotent: if the task already has an active routing decision
    (with ``selected_profile_id`` set), returns it.

    Returns::

        {
            "routing_decision_id": str,
            "selected_backend_profile_id": str | None,
            "fallback_chain": [profile_id, ...],
            "reason_summary": str,
            "matched_rules": [...],
            "approval_required": bool,
            "approval_id": str | None,
        }
    """
    task_id = task["id"]

    # ── Idempotency: reuse existing active decision ─────────────
    existing = conn.execute(
        "SELECT * FROM routing_decisions "
        "WHERE task_id = ? AND selected_profile_id IS NOT NULL "
        "ORDER BY created_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    if existing:
        existing = dict(existing)
        fallback_chain = []
        if existing.get("fallback_chain_json"):
            try:
                fallback_chain = json.loads(existing["fallback_chain_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        matched_rules = []
        if existing.get("matched_rules_json"):
            try:
                matched_rules = json.loads(existing["matched_rules_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        return {
            "routing_decision_id": existing["id"],
            "selected_backend_profile_id": existing["selected_profile_id"],
            "fallback_chain": fallback_chain,
            "reason_summary": existing.get("reason_summary", ""),
            "matched_rules": matched_rules,
            "approval_required": False,
            "approval_id": None,
        }

    # Also check for pending approval decision (no selected_profile_id)
    pending_approval = conn.execute(
        "SELECT rd.*, a.id as approval_id FROM routing_decisions rd "
        "LEFT JOIN approvals a ON a.task_id = rd.task_id "
        "  AND a.status = 'pending' "
        "WHERE rd.task_id = ? AND rd.selected_profile_id IS NULL "
        "ORDER BY rd.created_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    if pending_approval:
        pending_approval = dict(pending_approval)
        # Check if there's still a pending approval
        if pending_approval.get("approval_id"):
            return {
                "routing_decision_id": pending_approval["id"],
                "selected_backend_profile_id": None,
                "fallback_chain": [],
                "reason_summary": pending_approval.get("reason_summary", ""),
                "matched_rules": [],
                "approval_required": True,
                "approval_id": pending_approval["approval_id"],
            }

    # ── Count existing decisions for decision_index ─────────────
    count_row = conn.execute(
        "SELECT COUNT(*) as cnt FROM routing_decisions WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    decision_index = count_row["cnt"] if count_row else 0

    matched_rules: list[dict] = []
    selected_profile_id: str | None = None
    reason_summary = ""

    # ── Step 1: Pin explícito ───────────────────────────────────
    requested_profile_id = task.get("requested_backend_profile_id")
    if requested_profile_id:
        profile = conn.execute(
            "SELECT id, enabled, slug FROM backend_profiles WHERE id = ?",
            (requested_profile_id,),
        ).fetchone()
        if profile and profile["enabled"]:
            selected_profile_id = profile["id"]
            matched_rules.append({
                "rule": "user_pin",
                "profile_id": profile["id"],
                "slug": profile["slug"],
            })
            reason_summary = f"User pin to {profile['slug']}"

    # ── Step 2: Capability check ────────────────────────────────
    if selected_profile_id is None and not requested_profile_id:
        cap_profile = capability_service.get_effective_profile(
            task.get("project_id"), conn,
        )
        # Build a minimal run/profile for evaluate()
        eval_result = capability_service.evaluate(
            task, {}, {}, cap_profile,
        )
        if not eval_result["allowed"] and eval_result.get("approval_required"):
            # Create routing decision without selected profile
            decision_id = str(uuid.uuid4())
            now = _now_iso()
            reason_summary = f"Capability denied: {eval_result['reason']}"

            conn.execute(
                "INSERT INTO routing_decisions "
                "(id, task_id, decision_index, requested_profile_id, "
                " selected_profile_id, reason_summary, matched_rules_json, "
                " fallback_chain_json, estimated_resource_cost, "
                " quota_risk, created_at) "
                "VALUES (?, ?, ?, ?, NULL, ?, ?, NULL, ?, ?, ?)",
                (
                    decision_id, task_id, decision_index,
                    requested_profile_id,
                    reason_summary,
                    json.dumps([{"rule": "capability_denied",
                                 "triggers": eval_result["triggers"]}]),
                    task.get("estimated_resource_cost"),
                    task.get("quota_risk"),
                    now,
                ),
            )

            # Create approval
            approval = approval_service.request_approval(
                task_id=task_id,
                backend_run_id=None,
                approval_type="capability_denied",
                reason=reason_summary,
                risk_level="medium",
                conn=conn,
            )

            # Mark task as approval_required
            conn.execute(
                "UPDATE tasks SET approval_required = 1, updated_at = ? "
                "WHERE id = ?",
                (now, task_id),
            )
            conn.commit()

            return {
                "routing_decision_id": decision_id,
                "selected_backend_profile_id": None,
                "fallback_chain": [],
                "reason_summary": reason_summary,
                "matched_rules": [{"rule": "capability_denied",
                                   "triggers": eval_result["triggers"]}],
                "approval_required": True,
                "approval_id": approval["id"],
            }

    # ── Step 3: Resume-aware ────────────────────────────────────
    if selected_profile_id is None:
        current_run_id = task.get("current_run_id")
        if current_run_id:
            prior_run = conn.execute(
                "SELECT br.*, bp.slug, bp.enabled, bp.capabilities_json "
                "FROM backend_runs br "
                "JOIN backend_profiles bp ON bp.id = br.backend_profile_id "
                "WHERE br.id = ?",
                (current_run_id,),
            ).fetchone()
            if prior_run:
                prior_run = dict(prior_run)
                status = prior_run.get("status", "")
                if status in ("succeeded", "failed"):
                    if prior_run.get("enabled"):
                        # Check resume capability
                        caps = {}
                        if prior_run.get("capabilities_json"):
                            try:
                                caps = json.loads(
                                    prior_run["capabilities_json"]
                                )
                            except (json.JSONDecodeError, TypeError):
                                pass
                        resume_modes = caps.get("resume_modes", [])
                        if resume_modes:
                            selected_profile_id = prior_run[
                                "backend_profile_id"
                            ]
                            matched_rules.append({
                                "rule": "resume_aware",
                                "prior_run_id": current_run_id,
                                "profile_id": selected_profile_id,
                                "slug": prior_run["slug"],
                            })
                            reason_summary = (
                                f"Resume-aware: reusing {prior_run['slug']} "
                                f"from prior run {current_run_id}"
                            )

    # ── Step 4: Persisted routing rules ─────────────────────────
    if selected_profile_id is None:
        rules = conn.execute(
            "SELECT * FROM routing_rules "
            "WHERE enabled = 1 "
            "ORDER BY position ASC",
        ).fetchall()
        for rule in rules:
            rule = dict(rule)
            if _match_rule(rule, task):
                profile_id = _resolve_backend_slug(
                    rule.get("action_json", "{}"), conn,
                )
                if profile_id is not None:
                    selected_profile_id = profile_id
                    # Get slug for logging
                    slug_row = conn.execute(
                        "SELECT slug FROM backend_profiles WHERE id = ?",
                        (profile_id,),
                    ).fetchone()
                    matched_rules.append({
                        "rule": "routing_rule",
                        "rule_id": rule["id"],
                        "rule_name": rule.get("name", ""),
                        "position": rule["position"],
                        "profile_id": profile_id,
                        "slug": slug_row["slug"] if slug_row else "",
                    })
                    reason_summary = (
                        f"Rule '{rule.get('name', '')}' "
                        f"(pos={rule['position']}) matched"
                    )
                    break
                # Rule matched but backend is disabled/missing — skip

    # ── Step 5: Default fallback ────────────────────────────────
    if selected_profile_id is None:
        default = conn.execute(
            "SELECT id, slug FROM backend_profiles "
            "WHERE enabled = 1 "
            "ORDER BY priority DESC LIMIT 1",
        ).fetchone()
        if default:
            selected_profile_id = default["id"]
            matched_rules.append({
                "rule": "default",
                "profile_id": default["id"],
                "slug": default["slug"],
            })
            reason_summary = f"Default: {default['slug']} (highest priority)"

    # ── Build fallback chain ────────────────────────────────────
    fallback_chain: list[str] = []
    if selected_profile_id:
        fallback_chain = _build_fallback_chain(selected_profile_id, conn)

    # ── Persist decision ────────────────────────────────────────
    decision_id = str(uuid.uuid4())
    now = _now_iso()

    conn.execute(
        "INSERT INTO routing_decisions "
        "(id, task_id, decision_index, requested_profile_id, "
        " selected_profile_id, reason_summary, matched_rules_json, "
        " fallback_chain_json, estimated_resource_cost, "
        " quota_risk, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            decision_id, task_id, decision_index,
            task.get("requested_backend_profile_id"),
            selected_profile_id,
            reason_summary,
            json.dumps(matched_rules),
            json.dumps(fallback_chain),
            task.get("estimated_resource_cost"),
            task.get("quota_risk"),
            now,
        ),
    )

    # Update task with selected profile
    if selected_profile_id:
        conn.execute(
            "UPDATE tasks SET selected_backend_profile_id = ?, "
            "updated_at = ? WHERE id = ?",
            (selected_profile_id, now, task_id),
        )

    conn.commit()

    return {
        "routing_decision_id": decision_id,
        "selected_backend_profile_id": selected_profile_id,
        "fallback_chain": fallback_chain,
        "reason_summary": reason_summary,
        "matched_rules": matched_rules,
        "approval_required": False,
        "approval_id": None,
    }


# ── Public helpers ──────────────────────────────────────────────────


def get_fallback_chain(routing_decision: dict, conn) -> list[str]:
    """Return the ordered fallback chain for a routing decision.

    Reads from the persisted ``fallback_chain_json`` in the DB.
    """
    decision_id = routing_decision.get("id") or routing_decision.get(
        "routing_decision_id"
    )
    if not decision_id:
        return []

    row = conn.execute(
        "SELECT fallback_chain_json FROM routing_decisions WHERE id = ?",
        (decision_id,),
    ).fetchone()
    if not row or not row["fallback_chain_json"]:
        return []
    try:
        return json.loads(row["fallback_chain_json"])
    except (json.JSONDecodeError, TypeError):
        return []


# ── Seed routing rules ──────────────────────────────────────────────

_SEED_ROUTING_RULES = [
    {
        "name": "complex_to_claude",
        "position": 10,
        "match_json": json.dumps({
            "keywords_any": [
                "refactor", "arquitectura", "diseño",
                "migra", "reestructura", "multi-archivo",
                "varios archivos", "todo el",
            ],
            "description_min_words": 30,
        }),
        "action_json": json.dumps({"backend_slug": "claude_code"}),
    },
    {
        "name": "small_patch_to_codex",
        "position": 20,
        "match_json": json.dumps({
            "keywords_any": [
                "fix", "bug", "typo", "rename", "quita",
                "añade test", "parche", "corrige",
            ],
            "description_max_words": 40,
        }),
        "action_json": json.dumps({"backend_slug": "codex"}),
    },
    {
        "name": "default_claude",
        "position": 999,
        "match_json": json.dumps({}),
        "action_json": json.dumps({"backend_slug": "claude_code"}),
    },
]


def seed_routing_rules(conn) -> int:
    """Insert seed routing rules if the table is empty.

    Only executes if ``routing_rules`` has zero rows.
    Uses ``INSERT OR IGNORE`` for safety.

    Returns the number of rows inserted.
    """
    count = conn.execute(
        "SELECT COUNT(*) as cnt FROM routing_rules"
    ).fetchone()
    if count and count["cnt"] > 0:
        return 0

    now = _now_iso()
    inserted = 0

    for rule in _SEED_ROUTING_RULES:
        rule_id = str(uuid.uuid4())
        conn.execute(
            "INSERT OR IGNORE INTO routing_rules "
            "(id, name, position, enabled, match_json, action_json, "
            " created_at, updated_at) "
            "VALUES (?, ?, ?, 1, ?, ?, ?, ?)",
            (
                rule_id,
                rule["name"],
                rule["position"],
                rule["match_json"],
                rule["action_json"],
                now, now,
            ),
        )
        inserted += 1
        logger.info("Seeded routing_rule: %s (position=%d)",
                     rule["name"], rule["position"])

    return inserted
