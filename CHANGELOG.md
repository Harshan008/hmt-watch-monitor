# Changelog

All notable changes to this project. Format based on [Keep a Changelog](https://keepachangelog.com/).

## [1.0.0] - 2026-09-30

First release.

### Added
- Stock monitoring for hmtwatches.in through the site's `product_view` JSON.
- Support for hmtwatches.store through the product page's `__NEXT_DATA__` JSON (best-effort: that site
  blocks GitHub Actions).
- Telegram alerts on sold out → in stock, with no duplicates and a 10-minute cooldown per watch.
- Sale-window scheduling in IST (09:00–12:00 and 15:00–17:00), with no requests outside the windows.
- `near_realtime` mode checking every 30 s, and `strict_free` mode (every 5 min).
- Polite fetching: one request at a time, timeouts, retries with backoff, and a pause after repeated
  403 / 429 / challenge responses.
- GitHub Actions workflows: monitor, add a watch from a link, keep the schedule alive, and tests.
- 92 automated tests using real saved responses from both sites. Lint with ruff.

### Verified
- Live end-to-end test: a real in-stock watch produced one Telegram alert, and the next run sent no duplicate.
