"""Polling loop for the Niwa v1 executor.

The loop is intentionally minimal:

* Open a fresh session per iteration via ``SessionLocal`` so we never hold a
  transaction across sleeps (SQLite would block every writer otherwise).
* Call ``process_pending`` — any exception propagates and kills the daemon,
  matching the brief's explicit "no respawn in this PR" stance.
* Sleep ``interval`` seconds between iterations. ``KeyboardInterrupt`` is
  the graceful stop signal; systemd will send SIGTERM in production, and
  Python translates that to the same exception.
"""

from __future__ import annotations

import logging
import time

from ..db import SessionLocal
from .core import process_pending


logger = logging.getLogger("niwa.executor")


def run_forever(interval: float = 5.0) -> None:
    """Poll the queue forever with ``interval`` seconds between iterations.

    Each iteration runs in its own session. A crash inside ``process_pending``
    is not swallowed — the daemon dies and systemd (or the operator) is in
    charge of respawning.
    """

    logger.info("executor starting (interval=%.2fs)", interval)
    try:
        while True:
            session = SessionLocal()
            try:
                count = process_pending(session)
                if count:
                    logger.info("iteration done: %d task(s) processed", count)
            finally:
                session.close()
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("executor stopped (KeyboardInterrupt)")


__all__ = ["run_forever"]
