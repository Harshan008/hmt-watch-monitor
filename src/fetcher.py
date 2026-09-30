"""Polite HTTP fetching: one request at a time, bounded timeouts, limited retries.

Never tries to get around blocking. 403 / 429 / challenge pages are reported as
`blocked` and are NOT retried.
"""
from __future__ import annotations

import logging
import random
import time
from email.utils import parsedate_to_datetime
from typing import Callable, Optional

import requests

from .config import RequestConfig
from .models import FetchResult

log = logging.getLogger(__name__)

CHALLENGE_MARKERS = (
    "captcha",
    "cf-chl",
    "challenge-platform",
    "just a moment...",
    "attention required",
    "access denied",
    "are you a robot",
)


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        dt = parsedate_to_datetime(value)
        return max(0.0, dt.timestamp() - time.time())
    except (TypeError, ValueError):
        return None


def looks_like_challenge(body: str) -> bool:
    """Only meaningful for non-JSON bodies; a JSON answer is never a challenge page."""
    stripped = body.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return False
    lowered = body[:20000].lower()
    return any(marker in lowered for marker in CHALLENGE_MARKERS)


class Fetcher:
    def __init__(
        self,
        cfg: RequestConfig,
        session: Optional[requests.Session] = None,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[], float] = random.random,
    ):
        self.cfg = cfg
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": cfg.user_agent,
            "Accept": "application/json, text/html;q=0.8",
            "X-Requested-With": "XMLHttpRequest",
        })
        self.sleep = sleep
        self.rand = rand

    def _backoff(self, attempt: int) -> float:
        return self.cfg.backoff_base_seconds * (2 ** attempt) + self.rand() * self.cfg.jitter_seconds

    def get(self, url: str, referer: Optional[str] = None) -> FetchResult:
        headers = {"Referer": referer} if referer else {}
        attempts_allowed = 1 + int(self.cfg.max_retries)
        started = time.monotonic()
        last_error = None
        last_status = None

        for attempt in range(attempts_allowed):
            try:
                resp = self.session.get(
                    url,
                    headers=headers,
                    timeout=(self.cfg.connect_timeout_seconds, self.cfg.timeout_seconds),
                    allow_redirects=True,
                )
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                log.warning("attempt %d/%d network error: %s", attempt + 1, attempts_allowed, last_error)
                if attempt + 1 < attempts_allowed:
                    self.sleep(self._backoff(attempt))
                continue

            latency = int((time.monotonic() - started) * 1000)
            code = resp.status_code
            last_status = code
            body = resp.text or ""

            if code == 429:
                return FetchResult(code, body[:2000], latency, attempt + 1, "rate limited (429)",
                                   blocked=True, retry_after_seconds=parse_retry_after(resp.headers.get("Retry-After")))
            if code == 403:
                return FetchResult(code, body[:2000], latency, attempt + 1, "forbidden (403)", blocked=True)
            if looks_like_challenge(body) and code in (200, 202, 503):
                return FetchResult(code, body[:2000], latency, attempt + 1, "challenge/CAPTCHA page", blocked=True)
            if 500 <= code < 600:
                last_error = f"server error {code}"
                log.warning("attempt %d/%d: %s", attempt + 1, attempts_allowed, last_error)
                if attempt + 1 < attempts_allowed:
                    self.sleep(self._backoff(attempt))
                continue
            error = None if code in (200, 304) else f"unexpected HTTP {code}"
            return FetchResult(code, body, latency, attempt + 1, error)

        latency = int((time.monotonic() - started) * 1000)
        return FetchResult(last_status, "", latency, attempts_allowed, last_error or "failed")
