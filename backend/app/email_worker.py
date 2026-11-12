"""CLI worker for dispatching transactional email outbox messages."""
from __future__ import annotations

import argparse
import logging
import os
import time

from .db import SessionLocal
from .email_delivery import dispatch_outbox_batch
from .smtp_email_provider import SMTPEmailProvider


logger = logging.getLogger("hw_catalog.email_worker")


def run_worker(*, once: bool = False, poll_seconds: float = 5, batch_size: int = 20) -> None:
    if poll_seconds < 1 or batch_size < 1 or batch_size > 100:
        raise ValueError("poll_seconds must be >= 1 and batch_size must be 1..100")
    provider = SMTPEmailProvider.from_env()
    while True:
        result = dispatch_outbox_batch(SessionLocal, provider, limit=batch_size)
        if any(result.values()):
            logger.info(
                "Email outbox batch: sent=%d retrying=%d failed=%d",
                result["sent"], result["retrying"], result["failed"],
            )
        if once:
            return
        time.sleep(poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="HW Catalog transactional email worker")
    parser.add_argument("--once", action="store_true", help="process one batch and exit")
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=float(os.environ.get("HW_EMAIL_WORKER_POLL_SECONDS", "5")),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.environ.get("HW_EMAIL_WORKER_BATCH_SIZE", "20")),
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=os.environ.get("HW_EMAIL_WORKER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run_worker(
        once=args.once,
        poll_seconds=args.poll_seconds,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
