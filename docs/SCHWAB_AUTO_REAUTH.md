# Schwab OAuth Reauth (manual-first)

**Why this exists (2026-07-22; manual-first 2026-08-11).** Schwab refresh tokens have a FIXED
7-day lifetime from the browser login. Rotation does NOT extend it — proven from
`broker_oauth_token_audit`: every login dies at exactly login+7d despite hundreds of successful
30-min access refreshes (the 06-21 "rotating refresh tokens reset the clock" conclusion, commit
f7196367, was founded on a fingerprint artifact: `_fp()` hashes the Fernet CIPHERTEXT, which
differs on every write even for an identical token). The DB's `refresh_expires_at` is rolled
to now+7d on every rotation write, so it can never warn — the TRUE clock is the audit table's
last `event='reauth'` row.

## Primary path (2026-08-11+): Command Center manual renewal

Browser auto-login of Schwab 2FA proved unreliable (stuck on authenticator/OTP pages; timeouts).
**Default mode is manual** via Command Center.

| Step | Where | Action |
|------|--------|--------|
| 1 | CC **Ops → Schwab Reauth** (`/v3/system/schwab-reauth`) | **Request renewal URL** |
| 2 | Phone / browser | Open authorize link, complete Schwab login + 2FA |
| 3 | Same browser | Copy full address-bar URL (`https://127.0.0.1/?code=…` — page may not load) |
| 4 | CC page | Paste URL → **Submit & renew token** |

**APIs (portfolio server):**

| Method | Path | Role |
|--------|------|------|
| `GET` | `/api/v2/brokers/schwab/reauth-url` | Build authorize URL (`schwab_token_manager.reauth_url`) |
| `POST` | `/api/v2/brokers/schwab/exchange-code` | Body `{redirect_url, account_key?}` → exchange + seed |
| `GET` | `/api/v2/brokers/schwab/token-health` | Health + `show_banner`, `true_expiry`, `days_to_true_expiry` |

Site-wide **Schwab reauth banner** appears on all CC v3 pages when `show_banner` is true
(degraded / needs_reauth / day-6 true-login window). Links to the reauth page.

**Telegram backup:** pasting the same `127.0.0.1?code=…` URL into Telegram still auto-exchanges
via `run_telegram_callback_poller.py`. Prefer CC.

Codes expire ~5 minutes after login — paste promptly. Never log the code/URL.

## Notify-only schedule agent

`scripts/schwab_auto_reauth.py` (optional cron `--check`):

1. Computes due-ness from last true login (audit) + 6 days, or immediately if degraded/missing.
2. Rate-limited (≥120 min between notifies, ≤4/day).
3. **Default: notify only** (Telegram + email) pointing at Command Center — **no Chromium**.
4. Browser automation is **opt-in only**: `--browser` or `SCHWAB_AUTO_REAUTH_BROWSER=1`
   (emergency recovery). Off by default; production cron should stay disabled or notify-only.

As of 2026-08-11 the production crontab line for `--check` is **commented out** (manual CC
is the operator path). Re-enable only as notify-only after code deploy, not browser mode.

**Operator surface.**

```bash
.venv/bin/python scripts/schwab_auto_reauth.py --status          # schedule + token state
.venv/bin/python scripts/schwab_auto_reauth.py --now             # force manual notify (no browser)
.venv/bin/python scripts/schwab_auto_reauth.py --browser --now   # emergency Chromium path
.venv/bin/python scripts/schwab_auto_reauth.py --notify-test     # channel check
```

**Credentials (browser mode only).** `SCHWAB_LOGIN_ID` / `SCHWAB_LOGIN_PASSWORD` live in
Bitwarden SM (`trade-ai-prod`) via tmpfs render. Store with:

```bash
.venv/bin/python scripts/secrets/store_schwab_login.py
```

Portal OAuth app creds (`SCHWAB_APP_KEY` / `SCHWAB_APP_SECRET` / `SCHWAB_CALLBACK_URL=https://127.0.0.1`)
are required for reauth-url + exchange-code (manual or browser).

## True clock

- Anchor: `max(created_at)` from `broker_oauth_token_audit` where `event='reauth' AND status='ok'`
- True expiry = last reauth + 7 days
- Proactive window = last reauth + 6 days (banner / notify)

## History

- **2026-07-22** — True auto-reauth (Chromium + 2FA wait) built and proven once.
- **2026-08-11** — Auto browser path disabled after repeated OTP/authenticator failures; CC
  manual page + APIs + site banner shipped; token renewed successfully via CC (true expiry
  advanced ~7 days).
