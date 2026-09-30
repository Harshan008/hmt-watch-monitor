"""Telegram Bot API notifier. The bot token is never logged."""
from __future__ import annotations

import html
import logging
import time
from datetime import datetime
from typing import Callable, Optional

import requests

from .config import Target
from .detector import BLOCKED_ALERT, IN_STOCK_ALERT, POSSIBLE_STOCK_ALERT, RECOVERED_ALERT, UNKNOWN_ALERT, Alert

log = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/sendMessage"


def _price(value: Optional[float]) -> str:
    if value is None:
        return "unknown"
    return f"₹{value:,.0f}"


def format_alert(alert: Alert, target: Target, now: datetime, tz_label: str = "IST") -> str:
    r = alert.result
    name = html.escape(r.title or target.name)
    link = html.escape(target.url, quote=True)
    detected = f"{now:%H:%M:%S} {tz_label}"
    if alert.kind == IN_STOCK_ALERT:
        qty = f"\nQuantity: {r.quantity}" if r.quantity else ""
        return (
            "🚨 <b>HMT STOCK ALERT</b>\n\n"
            f"Model: <b>{name}</b>\n"
            "Status: ✅ <b>AVAILABLE</b>\n"
            f"Detected: {detected}\n"
            f"Price: {_price(r.price)}{qty}\n"
            f'Link: <a href="{link}">Open product page</a>\n'
            "Source: HMT official website"
        )
    if alert.kind == POSSIBLE_STOCK_ALERT:
        return (
            "⚠️ <b>HMT: POSSIBLE STOCK - check now</b>\n\n"
            f"Model: <b>{name}</b>\n"
            f"Detected: {detected}\n"
            f"Details: {html.escape(r.note)}\n"
            f'Link: <a href="{link}">Open product page</a>\n'
            "The site returned unusual data with quantity &gt; 0. Please check manually."
        )
    if alert.kind == BLOCKED_ALERT:
        return (
            "⛔ <b>HMT monitor paused</b>\n\n"
            f"Model: {name}\n"
            f"Reason: {html.escape(r.note)} (HTTP {r.http_status})\n"
            f"Action: {html.escape(alert.note)}; the bot will not try to bypass this.\n"
            f"Time: {detected}"
        )
    if alert.kind == RECOVERED_ALERT:
        return f"🟢 <b>HMT monitor recovered</b>\n\nModel: {name}\nTime: {detected}"
    if alert.kind == UNKNOWN_ALERT:
        return (
            "❓ <b>HMT: could not read stock status</b>\n\n"
            f"Model: {name}\nDetails: {html.escape(r.note)}\nTime: {detected}"
        )
    return f"HMT monitor: {html.escape(alert.kind)} for {name} at {detected}"


class TelegramNotifier:
    def __init__(
        self,
        token: Optional[str],
        chat_id: Optional[str],
        dry_run: bool = False,
        session: Optional[requests.Session] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.token = (token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.dry_run = dry_run
        self.session = session or requests.Session()
        self.sleep = sleep

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def _scrub(self, text: str) -> str:
        return text.replace(self.token, "***") if self.token else text

    def send(self, text: str) -> bool:
        if self.dry_run:
            log.info("DRY_RUN: Telegram message suppressed:\n%s", text)
            return True
        if not self.configured:
            log.error("Telegram is not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing)")
            return False
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                   "disable_web_page_preview": True}
        for attempt in (1, 2):
            try:
                resp = self.session.post(API.format(token=self.token), json=payload, timeout=(10, 20))
                if resp.status_code == 200:
                    log.info("Telegram message sent")
                    return True
                detail = self._scrub(resp.text[:300])
                log.error("Telegram HTTP %s (attempt %d): %s", resp.status_code, attempt, detail)
                wait = 2.0
                if resp.status_code == 429:
                    try:
                        wait = float(resp.json().get("parameters", {}).get("retry_after", 2))
                    except ValueError:
                        pass
                elif 400 <= resp.status_code < 500:
                    return False  # bad token / chat id: retrying will not help
            except requests.RequestException as exc:
                log.error("Telegram network error (attempt %d): %s", attempt, self._scrub(str(exc))[:300])
                wait = 2.0
            if attempt == 1:
                self.sleep(min(wait, 30))
        return False
