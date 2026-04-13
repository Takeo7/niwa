"""Capability service — PR-03 skeleton, logic in PR-05.

Manages ``project_capability_profiles`` and enforces security /
resource constraints before and during execution.
"""


def get_effective_profile(project_id: str, backend_slug: str,
                          conn) -> dict:
    """Return the merged capability profile for a project + backend.

    Combines the project-level profile with the backend's declared
    capabilities to produce the effective constraints.

    Implementation in PR-05.
    """
    raise NotImplementedError(
        "get_effective_profile() implementation is in PR-05."
    )


def validate_constraints(run: dict, capability_profile: dict) -> list[str]:
    """Check a run against its capability profile.

    Returns a list of violation descriptions (empty = all OK).

    Implementation in PR-05.
    """
    raise NotImplementedError(
        "validate_constraints() implementation is in PR-05."
    )
