"""Approval service — PR-03 skeleton, logic in PR-05.

Manages approval gates: creation, resolution, and policy evaluation.
Approvals block task execution until a human resolves them.
"""


def request_approval(task_id: str, backend_run_id: str,
                     approval_type: str, reason: str,
                     risk_level: str, conn) -> dict:
    """Create an approval request for a backend run.

    Implementation in PR-05.
    """
    raise NotImplementedError(
        "request_approval() implementation is in PR-05."
    )


def resolve_approval(approval_id: str, status: str, resolved_by: str,
                     conn, *, resolution_note: str | None = None) -> dict:
    """Resolve an approval (approve / reject).

    Implementation in PR-05.
    """
    raise NotImplementedError(
        "resolve_approval() implementation is in PR-05."
    )


def evaluate_risk(task: dict, profile: dict,
                  capability_profile: dict) -> dict:
    """Evaluate whether a task requires approval based on risk.

    Returns a dict with ``requires_approval`` (bool), ``risk_level``,
    and ``reason``.

    Implementation in PR-05.
    """
    raise NotImplementedError(
        "evaluate_risk() implementation is in PR-05."
    )
