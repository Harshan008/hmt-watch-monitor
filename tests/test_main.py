"""End-to-end style tests of the monitor loop with a fake clock, fake HMT and fake Telegram."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import parse_config
from src.main import Monitor, main
from src.models import FetchResult
from src.state import load_state
from tests.conftest import fixture_text

IST = ZoneInfo("Asia/Kolkata")
OOS = fixture_text("product_view_out_of_stock.json")


def in_stock_body(qty=5):
    d = json.loads(OOS)
    d["product_details"].update(in_stock="yes", quantity=qty)
    return json.dumps(d)


class Clock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)


class FakeFetcher:
    def __init__(self, clock, responses):
        self.clock, self.responses, self.urls = clock, list(responses), []

    def get(self, url, referer=None):
        self.urls.append(url)
        self.clock.now += timedelta(seconds=35)  # HMT is slow
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return r if isinstance(r, FetchResult) else FetchResult(200, r, latency_ms=35000, attempts=1)


class FakeNotifier:
    def __init__(self, ok=True):
        self.sent, self.ok = [], ok

    def send(self, text):
        self.sent.append(text)
        return self.ok


def build(raw, tmp_path, start, responses, notifier=None):
    cfg = parse_config(raw)
    clock = Clock(start)
    fetcher = FakeFetcher(clock, responses)
    notifier = notifier or FakeNotifier()
    m = Monitor(cfg, tmp_path / "state.json", notifier, fetcher=fetcher, clock=clock,
                sleep=clock.sleep, rand=lambda: 0.0)
    return m, fetcher, notifier, clock


def at(h, m):
    return datetime(2026, 10, 1, h, m, tzinfo=IST)


def test_outside_window_makes_no_request(raw_config, tmp_path):
    m, f, n, _ = build(raw_config, tmp_path, at(13, 0), [OOS])
    assert m.run() == 0
    assert f.urls == [] and n.sent == []


def test_pre_window_waits_then_checks(raw_config, tmp_path):
    raw_config["pre_window_wait_minutes"] = 15
    m, f, _, clock = build(raw_config, tmp_path, at(8, 50), [OOS])
    m.run()
    assert len(f.urls) == 1 and clock.now >= at(9, 0)


def test_strict_free_single_check(raw_config, tmp_path):
    m, f, n, _ = build(raw_config, tmp_path, at(9, 30), [OOS])
    m.run()
    assert f.urls == ["https://www.hmtwatches.in/product_view?id=534"]
    assert n.sent == []
    assert load_state(tmp_path / "state.json")["stellar_dasl10"].last_status == "OUT_OF_STOCK"


def test_restock_alerts_once_across_runs(raw_config, tmp_path):
    m, _, n, _ = build(raw_config, tmp_path, at(9, 30), [OOS])
    m.run()
    m, _, n, _ = build(raw_config, tmp_path, at(9, 35), [in_stock_body()])
    m.run()
    assert len(n.sent) == 1 and "AVAILABLE" in n.sent[0]
    m, _, n2, _ = build(raw_config, tmp_path, at(9, 40), [in_stock_body()])
    m.run()
    assert n2.sent == []  # persistent IN_STOCK: no spam


def test_near_realtime_polls_until_window_end(raw_config, tmp_path):
    raw_config.update(mode="near_realtime", interval_seconds=60)
    m, f, n, clock = build(raw_config, tmp_path, at(11, 50), [OOS, OOS, OOS, in_stock_body(), in_stock_body()])
    m.run()
    assert clock.now <= at(12, 1)
    assert 8 <= len(f.urls) <= 10  # ~1 per minute for 10 minutes, then clean exit
    assert len(n.sent) == 1


def test_429_pauses_target_no_request_storm(raw_config, tmp_path):
    raw_config.update(mode="near_realtime", interval_seconds=60)
    blocked = FetchResult(429, "", blocked=True, error="rate limited (429)", retry_after_seconds=None)
    m, f, n, _ = build(raw_config, tmp_path, at(9, 0), [blocked])
    m.run()  # full 3h window
    # 1st block -> ~2 min pause, 2nd -> 30 min circuit: ~8 requests in 3 hours, not 180
    assert len(f.urls) <= 10
    assert sum("paused" in s for s in n.sent) >= 1


def test_telegram_failure_retries_next_cycle(raw_config, tmp_path):
    raw_config.update(mode="near_realtime", interval_seconds=60)
    notifier = FakeNotifier(ok=False)
    m, f, _, _ = build(raw_config, tmp_path, at(11, 57), [in_stock_body()], notifier=notifier)
    m.run()
    assert len(notifier.sent) >= 2  # retried on following cycles


def test_force_runs_outside_window(raw_config, tmp_path):
    m, f, _, _ = build(raw_config, tmp_path, at(22, 0), [OOS])
    m.run(force=True)
    assert len(f.urls) == 1


def test_cli_dry_run_requires_no_secrets_and_bad_config_exit_code(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    bad = tmp_path / "bad.yml"
    bad.write_text("mode: turbo\n")
    assert main(["--config", str(bad)]) == 2
    # missing secrets without dry run -> clear failure
    assert main(["--state", str(tmp_path / "s.json")]) == 2
