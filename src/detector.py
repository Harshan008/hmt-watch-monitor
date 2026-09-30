"""Transition detection, deduplication, cooldown and the blocking circuit breaker.

Pure logic: takes the previous state + a fresh CheckResult, returns the new state and the
alerts that should be sent. The caller sends them and calls `mark_sent` / `mark_failed`.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from .config import AlertConfig, RequestConfig
from .models import CheckResult, Status
from .state import TargetState

IN_STOCK_ALERT = "in_stock"
POSSIBLE_STOCK_ALERT = "possible_stock"
UNKNOWN_ALERT = "unknown"
BLOCKED_ALERT = "blocked"
RECOVERED_ALERT = "recovered"


@dataclass
class Alert:
    kind: str
    result: CheckResult
    note: str = ""


def is_paused(state: TargetState, now: datetime) -> bool:
    until = state.blocked_until_dt()
    return until is not None and now < until


def decide(
    prev: TargetState,
    result: CheckResult,
    now: datetime,
    alerts_cfg: AlertConfig,
    request_cfg: RequestConfig,
    retry_after_seconds: Optional[float] = None,
    base_pause_seconds: float = 120,
) -> Tuple[TargetState, List[Alert]]:
    st = copy.deepcopy(prev)
    out: List[Alert] = []
    if result.title:
        st.title = result.title

    # ---- blocking / circuit breaker --------------------------------------------------
    if result.status == Status.BLOCKED:
        st.consecutive_blocks += 1
        cooldown = timedelta(minutes=request_cfg.blocked_cooldown_minutes)
        if st.consecutive_blocks >= request_cfg.blocked_threshold:
            pause = cooldown
        else:
            pause = min(cooldown, timedelta(seconds=base_pause_seconds * (2 ** (st.consecutive_blocks - 1))))
        if retry_after_seconds:
            pause = max(pause, timedelta(seconds=retry_after_seconds))
        st.blocked_until = (now + pause).isoformat(timespec="seconds")
        circuit_just_opened = st.consecutive_blocks == request_cfg.blocked_threshold
        if circuit_just_opened and alerts_cfg.alert_blocked:
            out.append(Alert(BLOCKED_ALERT, result, f"paused for {int(pause.total_seconds() // 60)} min"))
        return st, out

    was_blocked = prev.consecutive_blocks >= request_cfg.blocked_threshold
    if result.status in (Status.IN_STOCK, Status.OUT_OF_STOCK, Status.UNKNOWN):
        st.consecutive_blocks = 0
        st.blocked_until = None
        if was_blocked and alerts_cfg.alert_recovery:
            out.append(Alert(RECOVERED_ALERT, result))

    # ---- stock transitions -----------------------------------------------------------
    if result.status == Status.IN_STOCK:
        st.unknown_alerted = False
        if result.price is not None:
            st.last_price = result.price
        if prev.last_status != Status.IN_STOCK.value:
            st.last_status = Status.IN_STOCK.value
            last_alert = prev.last_alert_dt()
            in_cooldown = (
                prev.last_alert_kind == IN_STOCK_ALERT
                and last_alert is not None
                and now - last_alert < timedelta(minutes=alerts_cfg.cooldown_minutes)
            )
            if not in_cooldown:
                out.append(Alert(IN_STOCK_ALERT, result))
    elif result.status == Status.OUT_OF_STOCK:
        st.unknown_alerted = False
        st.last_status = Status.OUT_OF_STOCK.value
        if result.price is not None:
            st.last_price = result.price
    elif result.status == Status.UNKNOWN:
        if not prev.unknown_alerted:
            if result.possible_stock and alerts_cfg.alert_possible_stock:
                st.unknown_alerted = True
                out.append(Alert(POSSIBLE_STOCK_ALERT, result))
            elif alerts_cfg.alert_unknown:
                st.unknown_alerted = True
                out.append(Alert(UNKNOWN_ALERT, result))
    # Status.ERROR: transient; keep previous knowledge, just log.
    return st, out


def mark_sent(state: TargetState, alert: Alert, now: datetime) -> None:
    state.last_alert_at = now.isoformat(timespec="seconds")
    state.last_alert_kind = alert.kind


def mark_failed(state: TargetState, prev: TargetState, alert: Alert) -> None:
    """Telegram failed: roll back so the next cycle tries the alert again."""
    if alert.kind == IN_STOCK_ALERT:
        state.last_status = prev.last_status
    elif alert.kind in (POSSIBLE_STOCK_ALERT, UNKNOWN_ALERT):
        state.unknown_alerted = prev.unknown_alerted
