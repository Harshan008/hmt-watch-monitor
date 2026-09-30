import requests

from src.config import RequestConfig
from src.fetcher import Fetcher, looks_like_challenge, parse_retry_after


class FakeResponse:
    def __init__(self, status, text="", headers=None):
        self.status_code = status
        self.text = text
        self.headers = headers or {}


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.headers = {}
        self.last_headers = None

    def get(self, url, **kwargs):
        self.calls += 1
        self.last_headers = kwargs.get("headers")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make(responses, **cfg):
    sleeps = []
    session = FakeSession(responses)
    fetcher = Fetcher(RequestConfig(max_retries=2, **cfg), session=session, sleep=sleeps.append, rand=lambda: 0.5)
    return fetcher, session, sleeps


def test_200_ok():
    f, s, sleeps = make([FakeResponse(200, '{"a":1}')])
    r = f.get("https://x")
    assert r.http_status == 200 and not r.blocked and r.error is None
    assert s.calls == 1 and sleeps == []


def test_429_backs_off_without_retry_and_honours_retry_after():
    f, s, sleeps = make([FakeResponse(429, "slow down", {"Retry-After": "120"})])
    r = f.get("https://x")
    assert r.blocked and r.retry_after_seconds == 120
    assert s.calls == 1  # no aggressive retry


def test_403_is_blocked_no_retry():
    f, s, _ = make([FakeResponse(403, "Forbidden")])
    r = f.get("https://x")
    assert r.blocked and s.calls == 1


def test_challenge_page_is_blocked():
    f, s, _ = make([FakeResponse(200, "<html><title>Just a moment...</title>cf-chl</html>")])
    assert f.get("https://x").blocked and s.calls == 1


def test_5xx_retries_with_exponential_backoff_then_errors():
    responses = [FakeResponse(502), FakeResponse(503), FakeResponse(502)]
    f, s, sleeps = make(responses, backoff_base_seconds=5, jitter_seconds=2)
    r = f.get("https://x")
    assert s.calls == 3 and r.error == "server error 502" and not r.blocked
    assert sleeps == [5 + 1.0, 10 + 1.0]


def test_5xx_then_success():
    f, s, _ = make([FakeResponse(502), FakeResponse(200, "{}")])
    assert f.get("https://x").http_status == 200 and s.calls == 2


def test_timeout_bounded_retry():
    f, s, sleeps = make([requests.Timeout("t1"), requests.ConnectionError("c"), requests.Timeout("t2")])
    r = f.get("https://x")
    assert r.http_status is None and "Timeout" in r.error
    assert s.calls == 3 and len(sleeps) == 2


def test_extra_headers_merge_with_referer():
    f, s, _ = make([FakeResponse(200, "{}")])
    f.get("https://x", referer="https://y", extra_headers={"X-Requested-With": None, "Accept": "text/html"})
    assert s.last_headers == {"Referer": "https://y", "X-Requested-With": None, "Accept": "text/html"}


def test_helpers():
    assert parse_retry_after("30") == 30
    assert parse_retry_after("garbage") is None
    assert parse_retry_after(None) is None
    assert not looks_like_challenge('{"captcha": "field in json is fine"}')
    assert looks_like_challenge("<html>please complete the CAPTCHA</html>")
