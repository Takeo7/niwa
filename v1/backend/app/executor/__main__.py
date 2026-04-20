"""Entrypoint for ``python -m app.executor``.

Two modes:

* ``--once`` drains the queue one time and exits with code ``0``. Useful for
  smoke tests, cron-style runs, or manually verifying the pipeline.
* Default mode runs ``run_forever`` with the polling interval from
  ``--interval`` (default ``5.0`` s). ``--verbose`` bumps the log level.
"""

from __future__ import annotations

import argparse
import logging

from ..db import SessionLocal
from .core import process_pending
from .runner import run_forever


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="niwa-executor")
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Polling interval in seconds (default: 5.0).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Drain the queue once and exit instead of polling forever.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.once:
        session = SessionLocal()
        try:
            processed = process_pending(session)
        finally:
            session.close()
        logging.getLogger("niwa.executor").info(
            "one-shot done: %d task(s) processed", processed
        )
        return 0

    run_forever(interval=args.interval)
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
