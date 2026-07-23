# Active Trader — Credential Requirements (Stage 0 discovery)

**Run ID:** 20260722-01 · **Date:** 2026-07-22
No credential value was created, read, copied, displayed, emailed, or committed in Stage 0.
Existing convention: Bitwarden Secrets Manager, project `trade-ai-prod`, rendered to tmpfs by
`scripts/secrets/render_env.py` (`tradeai-sm-render.service`); machine tokens at
`~/.openclaw/credentials/bws_read_token` / `bws_write_token` (never stored in SM — Rule 1,
`secrets_admin.py:38,207`). Registry: `config/secret_registry.yaml`.

## Already-existing secrets (names only; no action needed for Stage 1-13 unless noted)

| Family | Names | State |
|---|---|---|
| Alpaca | ALPACA_PAPER_API_KEY/SECRET_KEY; ALPACA_TAXABLE_*/ALPACA_IRA_* (live, read-only scaffolds); legacy ALPACA_API_KEY/SECRET_KEY | present in .env/SM |
| Schwab | SCHWAB_APP_KEY, SCHWAB_APP_SECRET, SCHWAB_REFRESH_TOKEN, SCHWAB_ACCT_<LABEL>, SCHWAB_LOGIN_ID, SCHWAB_LOGIN_PASSWORD, SCHWAB_TOKEN_ENC_KEY (Fernet) | present; auto-reauth PROVEN via SM |
| SnapTrade | SNAPTRADE_CLIENT_ID, SNAPTRADE_CONSUMER_KEY, SNAPTRADE_USER_ID, SNAPTRADE_USER_SECRET | present |
| Telegram | TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID | present |
| DB | DB_HOST/PORT/NAME/USER/PASSWORD | present |

## Required NEW credential/config slots for the Active Trader program

| secret_name | project | environment | required_by_stage | purpose | operator_supplied | placeholder_allowed |
|---|---|---|---|---|---|---|
| MOOMOO_DATA_LOGIN / MOOMOO_DATA_* | trade-ai-lab → trade-ai-prod | data-only first | Stage 5 (P5) | OpenD data-only login | YES | YES (sentinel) |
| MOOMOO_TRADE_UNLOCK_* | trade-ai-prod ONLY | live, operator-present ceremony | Stage 14 only | OpenD trade unlock — NEVER stored on disk per §15.3 | YES | NO (never pre-created) |
| GOOGLE_DRIVE_SYNC_* (or reuse gog keyring) | trade-ai-prod | prod | Stage 11 | idempotent Drive sync for night-run controller | YES (decide gog vs API) | YES |
| GMAIL_NOTIFICATION_CREDENTIAL_SLOT | trade-ai-prod | prod | Stage 11 (night-run preflight requires PROVEN send) | Gmail API messages.send minimal scope | YES | YES |
| GMAIL_SEND_AS | config (non-secret) | prod | Stage 11 | send-as identity | YES | YES |
| OPERATOR_NOTIFICATION_EMAIL | config (non-secret) | prod | Stage 0+ | operator notify target — discovered as john@jwwhiting.com (hardcoded in `email_notifier.py:13-14`; should become config) | confirm | n/a |
| ACTIVE_TRADER_DRIVE_FOLDER_ID | config (non-secret) | prod | Stage 11 | canonical Drive run folder — Stage 0 used Trade_AI_Docs_v2 id `1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR` | confirm | n/a |
| BWS lab machine token (`trade-ai-lab`) | Bitwarden org | lab | Stage 1 | lab placeholder writes; **lab project does not exist yet** | YES | n/a |
| Test-DB DSN (TRADE_AI_TEST_DATABASE_URL or equivalent) | trade-ai-lab | lab | Stage 1 | migration forward/rollback testing | YES | YES |

## Rules carried forward
- Sentinel placeholder value: `UNSET__OPERATOR_REQUIRED`; runtime must reject sentinel values (to be implemented Stage 1).
- No live broker credential mounted in lab/shadow; production BWS token never copied to candidate envs.
- Bitwarden lab placeholders were NOT created in Stage 0: the `trade-ai-lab` project does not exist and no explicit lab-write authorization was granted. Exact operator steps are in OPERATOR_TODO.md.
