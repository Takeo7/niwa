"""Port allocator — find a free port in the configured range (Phase 4, DEPLOY-06)."""

from __future__ import annotations

import socket

from sqlalchemy.orm import Session

from ..models import Deployment

# Default range for process deployments. Configurable via niwa config in a
# future PR; hardcoded to avoid scope creep in this phase.
PORT_RANGE_START = 41000
PORT_RANGE_END = 41999


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def allocate_port(session: Session, *, project_id: int) -> int:
    """Return a free port in [PORT_RANGE_START, PORT_RANGE_END].

    Skips ports already assigned to a non-stopped/failed deployment, and
    ports already bound at the OS level. Raises ``RuntimeError`` if the
    entire range is exhausted.
    """
    in_use = set(
        session.query(Deployment.port)
        .filter(
            Deployment.project_id != project_id,
            Deployment.status.in_(["starting", "healthy", "unhealthy"]),
            Deployment.port.isnot(None),
        )
        .all()
    )
    occupied: set[int] = {r[0] for r in in_use if r[0] is not None}

    for port in range(PORT_RANGE_START, PORT_RANGE_END + 1):
        if port in occupied:
            continue
        if _port_in_use(port):
            continue
        return port
    raise RuntimeError(f"No free port in range {PORT_RANGE_START}-{PORT_RANGE_END}")
