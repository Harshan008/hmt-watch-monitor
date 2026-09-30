# HMT Watch Stock Monitor ⌚ → 📱

Get a **Telegram alert the moment an HMT watch comes back in stock** on
[hmtwatches.in](https://www.hmtwatches.in). Runs entirely on **free GitHub Actions**:
no server, no laptop, no paid services.

```
🚨 HMT STOCK ALERT

Model: HMT Stellar DASL 10 R Black
Status: ✅ AVAILABLE
Detected: 10:17:32 IST
Price: ₹11,299
Link: Open product page
Source: HMT official website
```

## How it works

- During your sale windows (default **09:00–12:00** and **15:00–17:00 IST**) GitHub starts the monitor.
- For each watch it makes **one small request** to the same "quick view" data the HMT website itself
  uses (`/product_view?id=<product id>`), which contains `in_stock` and `quantity`.
- When a watch goes **out of stock → in stock**, you get **one** Telegram message. There are no repeats
  while it stays in stock.
- Outside the windows it makes **zero** requests to HMT.

| Mode (`config/targets.yml`) | How often | Notes |
|---|---|---|
| `near_realtime` (default) | every ~90 s inside windows | One long job per window. Free because the repo is public. |
| `strict_free` | every 5 min (GitHub minimum) | Gentlest option, but can miss very fast sell-outs. |

It is polite by design: one request at a time, a truthful `User-Agent`, and a 60 s timeout (HMT often takes
~35 s). It backs off on errors. On **403 / 429 / CAPTCHA** it **pauses** instead of trying to get around the
block, and tells you on Telegram.

## One-time setup

1. **Telegram secrets**: repo → **Settings → Secrets and variables → Actions → New repository secret**
   - `TELEGRAM_BOT_TOKEN`: the token from @BotFather
   - `TELEGRAM_CHAT_ID`: your numeric chat id. To get it, open Telegram, message **@userinfobot**, and copy the `Id`.
2. **Press Start on your bot**: open your bot in Telegram and send it `/start` (bots can't message you first).
3. **Test it**: **Actions → HMT Stock Monitor → Run workflow → action: `test-telegram`**.
   You should get a "✅ HMT monitor connected" message.
4. **Check the site once**: run it again with **action: `check-now`**. The log shows a line like
   `CHECK ... result=OUT_OF_STOCK latency_ms=37000`.

That's it. The schedule runs by itself every day.

## Add a watch (no coding)

1. Open the watch on hmtwatches.in and copy the link from the address bar.
2. **Actions → Add a watch → Run workflow**, paste the link, then **Run**.
3. The bot finds HMT's product number, checks it, and adds it to `config/targets.yml`.

To **pause** a watch, edit `config/targets.yml` on GitHub (pencil icon) and set `enabled: false`.
To **remove** one, delete its block.

## Change sale times

Edit `active_windows` in `config/targets.yml` **and** the matching `cron:` lines in
`.github/workflows/monitor.yml`. Both are in IST.

## Run locally (optional)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q                                      # all tests, no network
python -m src.main --force --dry-run                     # one live check, no Telegram
python -m src.add_target "https://www.hmtwatches.in/product_all_details?id=..."
```

Environment: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DRY_RUN=true`, `LOG_LEVEL=DEBUG`.

## Status meanings

| Status | Meaning | Alert? |
|---|---|---|
| `IN_STOCK` | `in_stock` says yes and quantity > 0 | ✅ once, on the transition |
| `OUT_OF_STOCK` | `in_stock` is no and quantity is 0 | no |
| `UNKNOWN` | data missing, changed, or contradictory. **Never treated as in stock.** | only "⚠️ possible stock" if quantity > 0 |
| `BLOCKED` | 403 / 429 / challenge page; the watch is paused 2–30 min | "⛔ paused" once |
| `ERROR` | timeout / 5xx after a retry | no (next cycle tries again) |

## Troubleshooting

- **No test message**: check both secrets are set, and that you pressed *Start* in your bot chat.
  The run log shows the Telegram error (the token is never printed).
- **`result=ERROR ... Timeout`**: HMT is slow or down. This is normal during busy sales; it retries next cycle.
- **`BLOCKED`**: HMT is refusing requests. The bot pauses by itself. If it keeps happening, switch to
  `mode: strict_free`.
- **`UNKNOWN` everywhere**: HMT changed its site. Open an issue or update `src/parser.py`.
- **"Add a watch" says 404**: product links can expire. Open the watch on hmtwatches.in again and copy a fresh link.
- **Many "cancelled" runs in Actions (near_realtime)**: this is expected. While one job is polling, later
  schedule ticks are queued and replaced.
- **Schedule stopped**: GitHub pauses schedules on inactive public repos. The *Keep schedule alive*
  workflow prevents this; if it ever happens, open **Actions → HMT Stock Monitor → Enable workflow**.

## Honest limits

- GitHub may start scheduled runs late during busy periods. Detection isn't guaranteed and neither is buying the watch.
- Only the out-of-stock response has been seen live so far (2026-09-30). The in-stock value is assumed to be
  `in_stock: "yes"` with quantity > 0. Any other value with quantity > 0 still sends a "possible stock" alert.
- This bot never logs in, adds to cart, buys, or bypasses CAPTCHA, rate limits or blocks.

## Project layout

```
src/        main.py (loop) · fetcher.py (polite HTTP) · parser.py (HMT data) · detector.py (alerts, dedup,
            circuit breaker) · state.py · telegram.py · scheduler.py (IST windows) · config.py · add_target.py
config/     targets.yml     ← the only file you normally edit
state/      state.json      ← updated by the bot
tests/      unit + end-to-end tests with real saved HMT responses
.github/workflows/  monitor · add-watch · keepalive · tests
```
