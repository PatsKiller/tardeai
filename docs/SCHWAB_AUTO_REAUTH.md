# Schwab True Auto-Reauth

**Why this exists (2026-07-22).** Schwab refresh tokens have a FIXED 7-day lifetime from the
browser login. Rotation does NOT extend it — proven from `broker_oauth_token_audit`: every
login since 06-21 died at exactly login+7d despite hundreds of successful 30-min access
refreshes between (the 06-21 "rotating refresh tokens reset the clock" conclusion, commit
f7196367, was founded on a fingerprint artifact: `_fp()` hashes the Fernet CIPHERTEXT, which
differs on every write even for an identical token). The DB's `refresh_expires_at` is rolled
to now+7d on every rotation write, so it can never warn — the TRUE clock is the audit table's
last `event='reauth'` row.

**What it does.** `scripts/schwab_auto_reauth.py` (cron `--check`, every 17 min, 08–21h):

1. Computes due-ness from the last true login (audit) + 6 days, or immediately if the token
   is degraded/missing. Rate-limited (≥120 min between attempts, ≤4/day).
2. **Notifies Telegram + email FIRST** — the operator has Schwab 2FA and must know the login
   is legitimate — then waits ~2 min.
3. Launches a persistent-profile headless Chromium (`data/runtime/schwab_browser_profile/`,
   0700, gitignored — carries "remember this device" cookies so later logins may skip 2FA),
   walks the OAuth authorize flow, fills credentials, waits up to 7 min for the operator's
   2FA approval, and captures the `?code=` callback via route interception (no listener).
4. Exchanges the code (`schwab_token_manager.exchange_code` → `seed_token`), `live_probe`s,
   and reports success/failure on both channels. Failure = screenshot to
   `data/runtime/schwab_reauth_debug/` + manual-fallback instructions; the prior token is
   never touched.

**Credentials — Bitwarden SM only.** `SCHWAB_LOGIN_ID` / `SCHWAB_LOGIN_PASSWORD` (and
optional `SCHWAB_TOTP_SECRET` if 2FA is an authenticator; leave absent for push/SMS) live in
the `trade-ai-prod` Bitwarden Secrets Manager project and reach the process only via the
tmpfs render (`/run/user/<uid>/tradeai/env`). Store/rotate them with:

    .venv/bin/python scripts/secrets/store_schwab_login.py     # getpass — never echoed

**Operator surface.**

    .venv/bin/python scripts/schwab_auto_reauth.py --status        # schedule + token state
    .venv/bin/python scripts/schwab_auto_reauth.py --now           # force attempt (notifies first)
    .venv/bin/python scripts/schwab_auto_reauth.py --now --no-wait # interactive test
    .venv/bin/python scripts/schwab_auto_reauth.py --notify-test   # channel check

**Caveats.** Automating an interactive brokerage login is ToS-sensitive and brittle against
bot defenses (operator accepted 2026-07-22). Selectors are candidate lists (login/OTP/terms/
continue) scanned across all frames; an unrecognized page fails safe with a screenshot and
the manual flow. If Schwab blocks headless Chromium, install xvfb and switch to headed.
