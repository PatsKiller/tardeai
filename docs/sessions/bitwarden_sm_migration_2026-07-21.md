# Bitwarden Secrets Manager Migration — Session Handoff (S0–S7)

**Date:** 2026-07-21  
**Host:** MS-01  
**Project:** `trade-ai-prod`  
**Constraint:** No secret **values** in this document.

## Phase status

| Phase | Status | Notes |
|-------|--------|-------|
| **S0** | **Complete** (prior) | bws 2.1.0; tokens 95B mode 600; project visible |
| **S1** | **Complete** | `scripts/secrets/bws_env.sh`; both tokens list `trade-ai-prod` |
| **S2** | **Complete** | 100 nonempty keys imported; 2 empty skipped (`GEMINI_API_KEY`, `REPORT_CLAUDE_MODEL`); `BWS_in_sm=0` |
| **S3** | **Complete** | `/run/user/1000/tradeai/env` 600; hash parity 100/100; user timer 4h; LKG unit tests |
| **S4** | **Complete** (post-16:15 ET) | `.env` → `.env.pre-sm-migration` 600; bootstrap tmpfs; staged portfolio_server restart; health 200 + db_ok |
| **S5** | **Complete** | Modal → SM upsert + render; `/api/env/write` → **410**; Vite build ok; no BWS in list API |
| **S6** | **Partial** | Framework + registry + probes + **DB_PASSWORD rotated**; paper Alpaca + Telegram BotFather **operator-pending** |
| **S7** | **Scheduled tomorrow** | Precondition: one clean trading day on tmpfs. Do **not** shred `.env.pre-sm-migration` yet |

## Import parity (S2)

- env keys (non-BWS): 102 total; 2 empty values skipped  
- SM secrets: **100**  
- `parity_nonempty_env_in_sm=True`  
- `BWS_*` never imported  

## Render (S3)

- Path: `/run/user/1000/tradeai/env`  
- Manifest: `/run/user/1000/tradeai/env.manifest.json` (hashes only)  
- systemd user: `tradeai-sm-render.timer` enabled (every 4h)  
- Tests: `tests/test_sm_render_env.py` — 4 passed  

## Cutover matrix (S4)

| Consumer | Load path |
|----------|-----------|
| `env_bootstrap.py` | tmpfs → disk `.env` → `.env.pre-sm-migration` |
| `db_adapter` | bootstrap first |
| `alpaca_credentials` / live read sync | bootstrap |
| `telegram_alert` | bootstrap on first `_env()` |
| `portfolio_server` | bootstrap before knobs |
| cron | still per-script; bootstrap via imports |

Legacy disk: **`.env.pre-sm-migration`** (mode 600). Live `.env` **absent**.

## Modal (S5)

- Backend: `secrets_admin.set_secret` → `bws secret create/edit` (write token) → `render_env.py --now` → audit jsonl + Telegram (key name only)  
- `POST /api/env/write` → **410 gone** (verified live)  
- Vite: production build succeeded  

## Shakedown (S6)

| Secret | Result |
|--------|--------|
| **DB_PASSWORD** | **OK** — generated → `ALTER ROLE` → SM edit → render → staged restart → `SELECT 1` + db_ok |
| Paper Alpaca keys | **Pending operator** — regenerate at Alpaca dashboard, then `rotate.py ALPACA_API_KEY` / `SECRET` |
| TELEGRAM_BOT_TOKEN | **Pending operator** — BotFather last; `rotate.py` + getMe + test msg to both chats |

### Probes after cutover (value-free)

| Probe | Result |
|-------|--------|
| db_select_1 | ok |
| alpaca paper `/v2/account` | ACTIVE |
| alpaca taxable `/v2/account` | ACTIVE |
| telegram getMe | ok (`tradeai_bigjohn718_bot`) |

## Holdings

| When | n | total |
|------|--:|------|
| Session earlier | 36 | ~1,258,430 |
| Post S4/S6 | 36 | ~1,077,878 |

**Not zero** — position count held. Total drop likely marks/valuation (flag for operator glance); iron rule not triggered.

## Flag-backs

1. SM free tier **rate limits** on bulk create — import used 1.2s pacing + 429 backoff.  
2. Empty env values cannot enter SM — skipped.  
3. **Paper Alpaca + Telegram rotations still owed** (Phase-0 exposure) — operator-driven.  
4. S7 shred deferred until **one clean trading day** on tmpfs.  
5. ATM full cycle observation: portfolio_server health + broker-accounts 200; deeper ATM open-cycle not forced off-hours.  
6. Screenshot of modal from served bundle: operator can capture System→Admin after hard refresh (dist rebuilt).  

## Commits (this session, approx)

- S1 `bws_env.sh`  
- S2 `import_env_to_sm.py`  
- S3 render + timer + tests + bootstrap  
- S4/S5/S6 wiring, modal, registry, rotation tools  

## S7 tomorrow checklist

1. Confirm tmpfs render + crons healthy through RTH  
2. Encrypted SM export → passphrase in password **vault** (not ms01)  
3. `shred -u .env.pre-sm-migration`  
4. Tighten `check_no_secrets.py` (refuse stray `*.env*` outside tmpfs)  
5. One-page rotation runbook in OPERATOR docs  

## Final line

**2026-07-21 ~16:16 ET — Completed S1–S5 + S6 framework and DB_PASSWORD shakedown. Remaining: operator paper Alpaca + Telegram rotations; S7 decommission after one clean trading day.**
