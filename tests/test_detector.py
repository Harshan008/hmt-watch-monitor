from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import AlertConfig, RequestConfig
from src.detector import (BLOCKED_ALERT, IN_STOCK_ALERT, POSSIBLE_STOCK_ALERT, RECOVERED_ALERT,
                          decide, is_paused, mark_failed, mark_sent)
from src.models import CheckResult, Status
from src.state import TargetState

IST = ZoneInfo("Asia/Kolkata")
T0 = datetime(2026, 10, 1, 9, 30, tzinfo=IST)
REQ = RequestConfig(blocked_threshold=2, blocked_cooldown_minutes=30)


def res(status, **kw):
    return CheckResult("t", status, title="HMT X", price=1000.0, **kw)


def run(states, now=T0, alerts=None):
    """Feed a sequence of statuses; returns list of alert kinds per step and final state."""
    st = TargetState()
    history = []
    for i, s in enumerate(states):
        t = now + timedelta(minutes=5 * i)
        prev = st
        st, out = decide(prev, s if isinstance(s, CheckResult) else res(s), t, alerts or AlertConfig(), REQ)
        for a in out:
            mark_sent(st, a, t)
        history.append([a.kind for a in out])
    return history, st


def test_out_to_in_emits_exactly_one_alert():
    h, st = run([Status.OUT_OF_STOCK, Status.IN_STOCK, Status.IN_STOCK, Status.IN_STOCK])
    assert h == [[], [IN_STOCK_ALERT], [], []]
    assert st.last_status == "IN_STOCK"


def test_back_out_then_in_again_alerts_again_after_cooldown():
    seq = [Status.OUT_OF_STOCK, Status.IN_STOCK, Status.OUT_OF_STOCK, Status.OUT_OF_STOCK, Status.IN_STOCK]
    h, _ = run(seq)  # second IN is 15 min after the first alert (> 10 min cooldown)
    assert h == [[], [IN_STOCK_ALERT], [], [], [IN_STOCK_ALERT]]


def test_flapping_within_cooldown_is_suppressed():
    h, _ = run([Status.IN_STOCK, Status.OUT_OF_STOCK, Status.IN_STOCK], alerts=AlertConfig(cooldown_minutes=30))
    assert h == [[IN_STOCK_ALERT], [], []]


def test_errors_between_do_not_create_duplicate_alerts():
    h, _ = run([Status.IN_STOCK, Status.ERROR, Status.UNKNOWN, Status.IN_STOCK])
    assert h == [[IN_STOCK_ALERT], [], [], []]


def test_error_during_restock_still_alerts_when_in_stock_seen():
    h, _ = run([Status.OUT_OF_STOCK, Status.ERROR, Status.IN_STOCK])
    assert h == [[], [], [IN_STOCK_ALERT]]


def test_unknown_never_treated_as_in_stock():
    h, st = run([Status.OUT_OF_STOCK, Status.UNKNOWN, Status.UNKNOWN])
    assert h == [[], [], []]
    assert st.last_status == "OUT_OF_STOCK"


def test_possible_stock_alerts_once():
    ps = res(Status.UNKNOWN, possible_stock=True)
    h, _ = run([Status.OUT_OF_STOCK, ps, ps, Status.OUT_OF_STOCK, ps])
    assert h == [[], [POSSIBLE_STOCK_ALERT], [], [], [POSSIBLE_STOCK_ALERT]]


def test_block_circuit_breaker_opens_after_threshold():
    st = TargetState()
    st, out = decide(st, res(Status.BLOCKED), T0, AlertConfig(), REQ)
    assert out == [] and st.consecutive_blocks == 1
    assert is_paused(st, T0 + timedelta(seconds=60))
    assert not is_paused(st, T0 + timedelta(minutes=3))
    st, out = decide(st, res(Status.BLOCKED), T0, AlertConfig(), REQ)
    assert [a.kind for a in out] == [BLOCKED_ALERT]
    assert is_paused(st, T0 + timedelta(minutes=29))
    assert not is_paused(st, T0 + timedelta(minutes=31))
    # a third block keeps it paused but does not re-alert
    st, out = decide(st, res(Status.BLOCKED), T0, AlertConfig(), REQ)
    assert out == []


def test_retry_after_is_honoured():
    st, _ = decide(TargetState(), res(Status.BLOCKED), T0, AlertConfig(), REQ, retry_after_seconds=3600)
    assert is_paused(st, T0 + timedelta(minutes=59))


def test_recovery_resets_breaker_and_optional_alert():
    st = TargetState(consecutive_blocks=2, blocked_until=T0.isoformat())
    st2, out = decide(st, res(Status.OUT_OF_STOCK), T0, AlertConfig(alert_recovery=True), REQ)
    assert [a.kind for a in out] == [RECOVERED_ALERT]
    assert st2.consecutive_blocks == 0 and st2.blocked_until is None
    _, out = decide(st, res(Status.OUT_OF_STOCK), T0, AlertConfig(), REQ)
    assert out == []


def test_failed_send_rolls_back_so_next_cycle_retries():
    prev = TargetState(last_status="OUT_OF_STOCK")
    st, out = decide(prev, res(Status.IN_STOCK), T0, AlertConfig(), REQ)
    mark_failed(st, prev, out[0])
    assert st.last_status == "OUT_OF_STOCK"
    st2, out2 = decide(st, res(Status.IN_STOCK), T0, AlertConfig(), REQ)
    assert [a.kind for a in out2] == [IN_STOCK_ALERT]
