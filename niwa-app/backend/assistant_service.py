"""Assistant service — PR-03 skeleton, logic in PR-08.

Handles the ``assistant_turn`` flow: receives a message from an
external channel (Telegram via OpenClaw, web chat, etc.), routes it
through the appropriate backend, and returns a structured response.
"""

from typing import Any


def assistant_turn(
    *,
    session_id: str,
    project_id: str | None,
    message: str,
    channel: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Process one assistant turn.

    Parameters
    ----------
    session_id : str
        Conversation session identifier.
    project_id : str | None
        Optional project scope for the turn.
    message : str
        User message text.
    channel : str
        Origin channel (e.g. ``"telegram"``, ``"web"``, ``"mcp"``).
    metadata : dict | None
        Optional channel-specific metadata.

    Returns
    -------
    dict with keys:
        - ``assistant_message``: str — the response text.
        - ``actions_taken``: list[str] — summary of actions performed.
        - ``task_ids``: list[str] — tasks created or updated.
        - ``approval_ids``: list[str] — approvals triggered.
        - ``run_ids``: list[str] — backend runs started.

    Implementation in PR-08.
    """
    raise NotImplementedError(
        "assistant_turn() implementation is in PR-08."
    )
