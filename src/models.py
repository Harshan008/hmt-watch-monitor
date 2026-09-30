"""Shared data types."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

PARSER_VERSION = "1.0.0"


class Status(str, Enum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


@dataclass
class FetchResult:
    """Outcome of one HTTP fetch (after retries)."""

    http_status: Optional[int]
    body: str = ""
    latency_ms: int = 0
    attempts: int = 0
    error: Optional[str] = None
    blocked: bool = False            # 403 / 429 / challenge page
    retry_after_seconds: Optional[float] = None


@dataclass
class CheckResult:
    """Outcome of checking one target."""

    target_id: str
    status: Status
    title: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[int] = None
    possible_stock: bool = False     # UNKNOWN but quantity > 0: worth a manual look
    note: str = ""
    http_status: Optional[int] = None
    latency_ms: int = 0
    raw: dict = field(default_factory=dict)
