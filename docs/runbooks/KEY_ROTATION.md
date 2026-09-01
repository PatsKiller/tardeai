# Key Rotation Runbook (2026-07-18)

Status:      ACTIVE
as_of:       2026-07-18T14:36:08-04:00
Measured at: efcc51365 / not measured

**Why now:** the repo is intentionally PUBLIC (external developer review). Anything in
git history is world-readable. `scripts/check_secret_exposure.sh` (names-only, run it
locally any time) scanned every current secret value against the full history:

**Verdict 2026-07-18: 2 EXPOSED · 24 clean · 1 unset.**
- `DB_PASSWORD` — in history since `e1264197` (the d793f290 "remove hardcoded DB
  password" commit removed the *references*, not the history).
- `SLACK_WEBHOOK_URL` — in history since `8fde958c`.
- Everything else (Schwab, Alpaca, Anthropic, OpenAI, Telegram, SnapTrade, Twilio,
  SMTP, Finviz, data vendors) has NEVER appeared in a commit — `.env` hygiene held.

## Priority 1 — the two exposed values (do these; ~15 min total)

### 1. DB_PASSWORD (Postgres `trade_ai` role)
Local-only listener, but Tailscale + the :9090 web console make "local" soft. Rotate:
```bash
# 1. new password into Postgres (single statement, no downtime for existing conns)
psql -h localhost -U trade_ai -d trade_ai -c "ALTER ROLE trade_ai PASSWORD '<NEW>'"
# 2. update the two credential stores
#    .env               → DB_PASSWORD=<NEW>
#    ~/.pgpass          → localhost:5432:trade_ai:trade_ai:<NEW>   (chmod 600)
# 3. bounce the readers (hot-reload does NOT re-read .env)
systemctl --user list-units 'trade*' --no-legend   # then for each main service:
#    kill -TERM <MainPID>   (per docs/…server restart protocol; api_v2 hot-reload excluded — full restart needed here)
# 4. verify
.venv/bin/python -c "import sys; sys.path.insert(0,'scripts'); from db_adapter import _get_conn; _get_conn().cursor().execute('SELECT 1'); print('db ok')"
bash scripts/check_secret_exposure.sh   # DB_PASSWORD now 'clean' (new value never committed)
# 5. re-run the encrypted secrets backup so Drive holds the new value
bash scripts/backup_secrets_state.sh
# 6. update the Bitwarden entry (bw CLI or app): item 'trade-ai .env'
```
Downtime: none if step 3 is done service-by-service; worst case one watchdog cycle.

### 2. SLACK_WEBHOOK_URL
`ENABLE_SLACK` is off — the webhook is dormant. Cheapest correct move: **revoke, don't
rotate.** Slack → app settings → Incoming Webhooks → delete the webhook; blank the
value in `.env`. If Slack is ever re-enabled, mint a fresh webhook then.

## Priority 2 — defense in depth (optional, ~20 min, no downtime)
The 24 clean keys are not exposed by the repo, but they live in one plaintext `.env`
on a Tailscale-reachable box. If rotating anyway, the order that costs nothing:
| Key | Where to rotate | Post-rotation step | Notes |
|---|---|---|---|
| TELEGRAM_BOT_TOKEN | @BotFather /revoke | .env + restart alert lanes | alerts drop for seconds |
| ALPACA_API_KEY/SECRET | Alpaca dashboard → regenerate | .env + restart paper pipeline | paper only |
| ANTHROPIC/OPENAI/XAI/GEMINI | provider consoles | .env; request-path is local-LLM so impact ≈ 0 | |
| Data vendors (FINNHUB/FMP/FRED/POLYGON/AV/NEWSAPI/YOUTUBE/2CAPTCHA) | each console | .env | low blast radius |
| SMTP_PASSWORD / TWILIO_AUTH_TOKEN | provider | .env | |
| SNAPTRADE_CONSUMER_KEY/USER_SECRET | SnapTrade portal (user secret via API re-register) | .env | read-only Fidelity sync re-links |
| FINVIZ_COOKIE | re-login to Elite, copy cookie | .env | expires naturally anyway |

## The one to handle with gloves: Schwab
`SCHWAB_APP_KEY`/`SCHWAB_APP_SECRET` are **clean** — no rotation required. If you ever
must rotate them (developer.schwab.com → app → regenerate secret): the stored OAuth
tokens die with the old secret, and the AUTO refresh lane cannot resurrect them — one
manual OAuth re-auth (the `SCHWAB_CALLBACK_URL` flow) is required immediately after.
Do it outside market hours; stops/quotes/journal ingest pause until re-auth completes.
**Do not touch this while it isn't exposed.**

## Not in scope / already safe
- `~/.pgpass`, `~/.config/gh`, gog keyring, Bitwarden vault, gpg passphrase — never in
  the repo (checked); GitHub token rotates via `gh auth refresh` any time.
- `data/`, `*.env` are gitignored; the public repo ships code only.

## Standing verification
`bash scripts/check_secret_exposure.sh` after ANY rotation — a rotated key goes
"clean" because the *new* value has no history. Exit code 2 while anything is EXPOSED
(cron-able if wanted).
