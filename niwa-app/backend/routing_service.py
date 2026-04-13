"""Routing service — PR-03 skeleton, logic in PR-06.

Deterministic router: matches tasks against ``routing_rules`` and
selects the appropriate ``backend_profile``.  Creates
``routing_decisions`` audit records.

No LLM calls.  The router is purely rule-based.
"""


def route_task(task: dict, conn) -> dict:
    """Evaluate routing rules for *task* and return a routing decision.

    Implementation in PR-06.
    """
    raise NotImplementedError("route_task() implementation is in PR-06.")


def get_fallback_chain(routing_decision: dict, conn) -> list[dict]:
    """Return the ordered fallback chain for a routing decision.

    Implementation in PR-06.
    """
    raise NotImplementedError(
        "get_fallback_chain() implementation is in PR-06."
    )
