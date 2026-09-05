# Phase 9 — High-risk Telegram sender migration

**Date:** 2026-09-04  
**Branch:** `wt/comms-gateway-phase0`  
**Goal:** Move a prioritized HIGH-RISK cohort off raw Bot API / token+chat selection onto `telegram_alert.send_telegram`, then shrink the chokepoint ratchet baseline.

## Pattern applied

- Delivery: `from telegram_alert import send_telegram` then `send_telegram(text)`.
- No producer reads of `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` for sending.
- No `telegram_transport` imports for sending.
- Optional best-effort SHADOW ledger via `scripts.lib.comms.publish_communication` (never owns delivery; failures ignored).
- Dual-path fallbacks (router then raw `api.telegram.org`) removed where present.

## Files migrated (10/10)

| File | Prior baseline count | After |
|---|---|---|
| `scripts/protection_alerts.py` | 4 | removed |
| `scripts/system_health_alerts.py` | 1 | removed |
| `scripts/pipeline_watchdog.py` | 4 | removed |
| `scripts/pipeline_health_monitor.py` | 4 | removed |
| `scripts/freshness_watchdog_heartbeat.py` | 4 | removed |
| `scripts/system_freshness_monitor.py` | 4 | removed |
| `scripts/send_no_leads_diagnostic_alert.py` | 5 | removed |
| `scripts/send_watchpool_maturity_alerts.py` | 5 | removed |
| `scripts/youtube_cookie_health_check.py` | 4 | removed |
| `scripts/premarket_watcher.py` | 4 | removed |
| **Cohort sum** | **39** | **0** |

## Baseline before / after

| Metric | Before `--update-baseline` | After |
|---|---|---|
| Known files | 46 | 35 |
| Violations | 142 | 97 |
| Delta | — | **−11 files, −45 violations** |

Live scan immediately before migration edits was already slightly under the recorded baseline (45 files / 133 violations); after the cohort migration the scan and refreshed baseline match at **35 / 97**.

## Verification

```text
python3 scripts/check_telegram_chokepoint.py --report   # 35 producers, 97 violations
python3 scripts/check_telegram_chokepoint.py --update-baseline
python3 scripts/check_telegram_chokepoint.py            # pass (ratchet)
python3 -m py_compile <all 10 migrated files>           # OK
```

## Explicit non-goals (honored)

- Did **not** flip `COMMS_GATEWAY_MODE` to ACTIVE.
- Did **not** modify `telegram_transport` to require `event_id`.
- Did **not** touch Phase 10 channel adapters or Phase 11 docs.
- Alerts still attempt delivery via the approved wrapper.
