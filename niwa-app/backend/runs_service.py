"""Runs service — PR-03 skeleton, lifecycle logic in PR-04.

Manages the lifecycle of ``backend_runs``: creation, status transitions,
heartbeat updates, and linking (fallback / resume / retry).
"""


def create_run(task_id: str, routing_decision_id: str,
               backend_profile_id: str, conn, *,
               previous_run_id: str | None = None,
               relation_type: str | None = None) -> dict:
    """Create a new ``backend_run`` record.

    Implementation in PR-04.
    """
    raise NotImplementedError("create_run() implementation is in PR-04.")


def transition_run(run_id: str, new_status: str, conn, **kwargs) -> dict:
    """Transition a run to *new_status*, enforcing the state machine.

    Implementation in PR-04.
    """
    raise NotImplementedError(
        "transition_run() implementation is in PR-04."
    )


def record_heartbeat(run_id: str, conn) -> None:
    """Update ``heartbeat_at`` for a running execution.

    Implementation in PR-04.
    """
    raise NotImplementedError(
        "record_heartbeat() implementation is in PR-04."
    )


def finish_run(run_id: str, outcome: str, conn, *,
               exit_code: int | None = None,
               error_code: str | None = None) -> dict:
    """Mark a run as finished with the given outcome.

    Implementation in PR-04.
    """
    raise NotImplementedError("finish_run() implementation is in PR-04.")
