from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from src.config import Target
from src.detector import BLOCKED_ALERT, IN_STOCK_ALERT, POSSIBLE_STOCK_ALERT, Alert
from src.models import CheckResult, Status
from src.telegram import TelegramNotifier, format_alert

NOW = datetime(2026, 10, 1, 10, 17, 32, tzinfo=ZoneInfo("Asia/Kolkata"))
TARGET = Target("t", "HMT Janata", 534, "https://www.hmtwatches.in/product_all_details?id=x&y=1")
TOKEN = "123456:SECRET-TOKEN"


class Resp:
    def __init__(self, status, text="{}"):
        self.status_code, self.text = status, text

    def json(self):
        import json
        return json.loads(self.text)


class Session:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_in_stock_message_format():
    r = CheckResult("t", Status.IN_STOCK, title="HMT Janata <Blue>", price=2750.0, quantity=5)
    text = format_alert(Alert(IN_STOCK_ALERT, r), TARGET, NOW)
    assert "HMT STOCK ALERT" in text and "AVAILABLE" in text
    assert "10:17:32 IST" in text and "₹2,750" in text
    assert "HMT Janata &lt;Blue&gt;" in text  # HTML-escaped
    assert 'href="https://www.hmtwatches.in/product_all_details?id=x&amp;y=1"' in text


def test_other_message_kinds():
    r = CheckResult("t", Status.UNKNOWN, note="unrecognised", possible_stock=True)
    assert "POSSIBLE STOCK" in format_alert(Alert(POSSIBLE_STOCK_ALERT, r), TARGET, NOW)
    b = CheckResult("t", Status.BLOCKED, note="forbidden (403)", http_status=403)
    assert "paused" in format_alert(Alert(BLOCKED_ALERT, b, "paused for 30 min"), TARGET, NOW)


def test_dry_run_never_calls_telegram():
    s = Session([])
    assert TelegramNotifier(TOKEN, "42", dry_run=True, session=s).send("hi") is True
    assert s.calls == []


def test_send_success():
    s = Session([Resp(200)])
    assert TelegramNotifier(TOKEN, "42", session=s).send("hi")
    url, payload = s.calls[0]
    assert url.endswith("/sendMessage") and payload["chat_id"] == "42" and payload["parse_mode"] == "HTML"


def test_retry_once_then_give_up(caplog):
    s = Session([requests.ConnectionError(f"https://api.telegram.org/bot{TOKEN}/sendMessage failed"), Resp(500)])
    sleeps = []
    assert not TelegramNotifier(TOKEN, "42", session=s, sleep=sleeps.append).send("hi")
    assert len(s.calls) == 2 and sleeps == [2.0]
    assert TOKEN not in caplog.text  # token never logged


def test_bad_chat_id_does_not_retry():
    s = Session([Resp(400, '{"description":"chat not found"}')])
    assert not TelegramNotifier(TOKEN, "42", session=s, sleep=lambda _: None).send("hi")
    assert len(s.calls) == 1


def test_missing_credentials():
    assert not TelegramNotifier("", "", session=Session([])).send("hi")
