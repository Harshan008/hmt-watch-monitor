"""Entry point: python -m src.main [--once] [--force] [--dry-run] [--test-telegram]

strict_free   : one check cycle, then exit (GitHub cron provides the 5-min cadence).
near_realtime : poll every `interval_seconds` until the current window closes.
Outside the configured windows no request is made to HMT unless --force is given.
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Optional

from . import detector
from .config import Config, ConfigError, load_config
from .fetcher import Fetcher
from .logging_utils import health_line, setup_logging
from .parser import classify, product_view_url
from .scheduler import active_window_end, next_window_start
from .store_parser import classify_store, store_product_url
from .state import TargetState, load_state, save_state
from .telegram import TelegramNotifier, format_alert

log = logging.getLogger("hmt")
ROOT = Path(__file__).resolve().parent.parent


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


class StopFlag:
    def __init__(self):
        self.stopped = False

    def __call__(self, signum, _frame):
        log.warning("received signal %s; finishing current step and exiting", signum)
        self.stopped = True


class Monitor:
    def __init__(
        self,
        cfg: Config,
        state_path: Path,
        notifier: TelegramNotifier,
        fetcher: Optional[Fetcher] = None,
        clock: Optional[Callable[[], datetime]] = None,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[], float] = random.random,
    ):
        self.cfg = cfg
        self.state_path = state_path
        self.notifier = notifier
        self.fetcher = fetcher or Fetcher(cfg.request)
        self.clock = clock or (lambda: datetime.now(cfg.tz))
        self.sleep = sleep
        self.rand = rand
        self.stop = StopFlag()
        self.states: Dict[str, TargetState] = load_state(state_path)
        self.requests_made = 0

    # -- helpers ---------------------------------------------------------------------
    def _sleep_until(self, when: datetime) -> None:
        """Interruptible sleep (wakes every few seconds to honour SIGTERM)."""
        while not self.stop.stopped:
            remaining = (when - self.clock()).total_seconds()
            if remaining <= 0:
                return
            self.sleep(min(remaining, 5))

    def _save(self) -> None:
        if save_state(self.state_path, self.states, [t.id for t in self.cfg.targets]):
            log.info("state updated: %s", self.state_path)

    # -- one cycle -------------------------------------------------------------------
    def run_cycle(self) -> None:
        targets = self.cfg.enabled_targets
        for i, target in enumerate(targets):
            if self.stop.stopped:
                break
            if i > 0 and self.cfg.request.jitter_seconds:
                self.sleep(self.rand() * self.cfg.request.jitter_seconds)
            now = self.clock()
            prev = self.states.get(target.id, TargetState())
            if detector.is_paused(prev, now):
                log.warning("SKIP target=%s paused until %s (blocked/rate-limited)", target.id, prev.blocked_until)
                continue

            if target.site == "store":
                url = store_product_url(self.cfg.store_base_url, target.product_id)
                # a normal page load, not an AJAX call: the .store site's WAF blocks
                # AJAX-looking requests to some paths, so look like a browser here.
                extra_headers = {"X-Requested-With": None, "Accept": "text/html,application/xhtml+xml"}
                fetch = self.fetcher.get(url, referer=target.url, extra_headers=extra_headers)
                self.requests_made += 1
                result = classify_store(target.id, target.product_id, fetch)
            else:
                url = product_view_url(self.cfg.base_url, target.product_id)
                fetch = self.fetcher.get(url, referer=target.url)
                self.requests_made += 1
                result = classify(target.id, target.product_id, fetch)
            now = self.clock()
            log.info(health_line(result, now))

            new_state, alerts = detector.decide(
                prev, result, now, self.cfg.alerts, self.cfg.request,
                retry_after_seconds=fetch.retry_after_seconds,
                base_pause_seconds=max(60, self.cfg.interval_seconds),
            )
            for alert in alerts:
                text = format_alert(alert, target, now)
                if self.notifier.send(text):
                    detector.mark_sent(new_state, alert, now)
                    log.info("ALERT sent kind=%s target=%s", alert.kind, target.id)
                else:
                    detector.mark_failed(new_state, prev, alert)
                    log.error("ALERT failed kind=%s target=%s (will retry next cycle)", alert.kind, target.id)
            self.states[target.id] = new_state
        self._save()

    # -- session ---------------------------------------------------------------------
    def run(self, once: bool = False, force: bool = False) -> int:
        cfg = self.cfg
        start = self.clock()
        window_end = active_window_end(cfg.active_windows, start)

        if window_end is None and not force:
            upcoming = next_window_start(cfg.active_windows, start)
            wait = (upcoming - start).total_seconds()
            if wait <= cfg.pre_window_wait_minutes * 60:
                log.info("window opens at %s; waiting %.0fs", upcoming.strftime("%H:%M"), wait)
                self._sleep_until(upcoming)
                if self.stop.stopped:
                    return 0
                start = self.clock()
                window_end = active_window_end(cfg.active_windows, start)
            if window_end is None:
                log.info("outside active windows (%s) at %s; no HMT request made. Next window: %s",
                         ", ".join(map(str, cfg.active_windows)), start.strftime("%H:%M %Z"),
                         upcoming.strftime("%Y-%m-%d %H:%M"))
                return 0

        single = once or force or cfg.mode == "strict_free"
        deadline = start + timedelta(minutes=cfg.max_session_minutes)
        if window_end is not None:
            deadline = min(deadline, window_end)
        log.info("session start mode=%s single=%s targets=%d until=%s", cfg.mode, single,
                 len(cfg.enabled_targets), deadline.strftime("%H:%M:%S"))

        while not self.stop.stopped:
            cycle_start = self.clock()
            self.run_cycle()
            if single:
                break
            jitter = self.rand() * cfg.request.jitter_seconds
            next_at = cycle_start + timedelta(seconds=cfg.interval_seconds + jitter)
            if next_at >= deadline:
                break
            self._sleep_until(next_at)
        log.info("session end; %d HMT request(s) made", self.requests_made)
        self._save()
        return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="HMT watch stock monitor")
    parser.add_argument("--config", default=str(ROOT / "config" / "targets.yml"))
    parser.add_argument("--state", default=str(ROOT / "state" / "state.json"))
    parser.add_argument("--once", action="store_true", help="run a single check cycle")
    parser.add_argument("--force", action="store_true", help="ignore sale windows (manual test; implies --once)")
    parser.add_argument("--dry-run", action="store_true", help="never send Telegram messages (or DRY_RUN=true)")
    parser.add_argument("--test-telegram", action="store_true", help="send a test message and exit")
    args = parser.parse_args(argv)

    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        log.error("CONFIG ERROR: %s", exc)
        return 2

    dry_run = args.dry_run or _env_flag("DRY_RUN")
    force = args.force or _env_flag("FORCE_CHECK")
    notifier = TelegramNotifier(os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID"), dry_run)

    if args.test_telegram:
        now = datetime.now(cfg.tz)
        watched = "\n".join(f"• {t.name}" for t in cfg.enabled_targets)
        ok = notifier.send(
            "✅ <b>HMT monitor connected</b>\n\n"
            f"Mode: {cfg.mode} (every {cfg.interval_seconds}s)\n"
            f"Windows (IST): {', '.join(map(str, cfg.active_windows))}\n"
            f"Watching:\n{watched}\n\nTime: {now:%Y-%m-%d %H:%M:%S} IST"
        )
        return 0 if ok else 1

    if not dry_run and not notifier.configured:
        log.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set (GitHub Secrets), or use DRY_RUN=true")
        return 2

    monitor = Monitor(cfg, Path(args.state), notifier)
    signal.signal(signal.SIGTERM, monitor.stop)
    signal.signal(signal.SIGINT, monitor.stop)
    return monitor.run(once=args.once, force=force)


if __name__ == "__main__":
    sys.exit(main())
