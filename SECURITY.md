# Security

## Secrets

- The Telegram bot token and chat id are stored only as **GitHub Actions secrets**
  (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). They are never committed to this repository.
- The code never logs the token. Telegram error messages are scrubbed before they're logged.
- The workflows use the built-in `GITHUB_TOKEN` with the minimum permissions they need.

This repository is **public**. Never put a token, password, cookie or personal data in any file here.

## If the bot token leaks

1. In Telegram, message **@BotFather** → `/revoke` → choose the bot. This creates a new token and the old
   one stops working.
2. Update the `TELEGRAM_BOT_TOKEN` secret in **Settings → Secrets and variables → Actions**.
3. Run **Actions → HMT Stock Monitor → Run workflow → `test-telegram`** to confirm.

## Scope

This bot only reads public product data. It never logs in to HMT, adds to cart, buys anything, or tries
to get around CAPTCHAs, rate limits or firewalls.

## Reporting

Please report security problems privately to the repository owner, not in a public issue.
