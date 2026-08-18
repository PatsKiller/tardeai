# Daily Intelligence Watchdog (Program 4)

READ_ONLY_ADVISORY. The watchdog observes, classifies, records, and alerts.
It does **not** trade, change risk, rotate credentials, or grant itself authority.

## Why this exists

CIO financial Telegram is a **material-event** channel. A quiet day with
`0 IMMEDIATE` / `N SUPPRESSED` is often healthy. Operators still need daily
proof that the intelligence office actually ran.

## What it produces

- One `DailyIntelligenceHeartbeat@v1` per America/New_York calendar day
- Append-only `data/cio/daily_intelligence_heartbeats.jsonl`
- Latest snapshot `data/cio/daily_intelligence_heartbeat.json`
- Command Center **Health → Daily Intelligence**
- GET `/api/v3/maturity/heartbeat` and `/heartbeat/history`
- Exactly one daily **SYSTEM** Telegram after 08:15 ET
- State-transition / recovery SYSTEM alerts (deduped)
- Explicit `--telegram-canary` (never scheduled)

## System vs financial Telegram

| Family | Transport | Purpose |
|--------|-----------|---------|
| CIO financial | dedicated CIO bot / notification lineage | IMMEDIATE material decisions only |
| SYSTEM | generic `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | daily heartbeat, canary, state alerts |

`CIO_TELEGRAM_INTERDICT` continues to block financial CIO sends. SYSTEM
messages are a different family and do not create CIO notification lineage.

Daily identity: `system-heartbeat:YYYY-MM-DD` (restart does not resend).

## States

`HEALTHY` · `EXPECTED_IDLE` · `DEGRADED` · `STALE` · `FAILED` · `NOT_CONFIGURED`

`EXPECTED_IDLE` is never remapped to `FAILED`.
`NOT_CONFIGURED` is never remapped to `HEALTHY`.

`MEMORY_BEHAVIOR_INFLUENCE != 0` is CRITICAL.

## Units

`tradeai-autonomy-watchdog.service` + `.timer` (5 minutes, flock singleton).

```bash
python3 scripts/autonomy_watchdog.py --dry-run
python3 scripts/autonomy_watchdog.py --once --no-telegram
python3 scripts/autonomy_watchdog.py --telegram-canary
```
