"""Logging setup and the per-check health line (FR-11)."""
from __future__ import annotations

import logging
import sys
from datetime import datetime

from .models import PARSER_VERSION, CheckResult


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def health_line(result: CheckResult, now: datetime) -> str:
    return (
        f"CHECK target={result.target_id} at={now.isoformat(timespec='seconds')} "
        f"http={result.http_status} result={result.status.value} latency_ms={result.latency_ms} "
        f"qty={result.quantity} price={result.price} parser={PARSER_VERSION} note={result.note!r}"
    )
