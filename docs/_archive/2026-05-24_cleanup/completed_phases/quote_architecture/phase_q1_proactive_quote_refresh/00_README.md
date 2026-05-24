# Q-1 — Proactive Quote Refresh

**Status:** COMPLETE

## Purpose

Fix the quote readiness gap: 22/83 proposals had stale quotes, 17 had unknown provider.
Quotes were only fetched on manual operator action.

## What Was Added

- **quote_provider_trust_policy.py** — Provider classification, spread/age limits per strategy
- **select_quote_refresh_targets.py** — Target selection: pending proposals + incubator candidates
- **run_proactive_quote_refresh.py** — Refresh runner (dry-run default, --apply to fetch)
- **run_scheduled_quote_refresh.sh** — Cron wrapper with safety guards, flock, market-session check
- **rollback_q1_quote_refresh_cron.sh** — Removes only Q-1 cron entries

## Cron Schedule

| Time | Day | Target | Limit |
|------|-----|--------|-------|
| */5 9:00-15:55 | M-F | Pending proposals | 50 |
| 09:20 | M-F | Incubator candidates | 100 |
| 12:00 | M-F | Incubator candidates | 100 |
| 15:30 | M-F | Incubator candidates | 100 |

## Provider Trust

- Alpaca/Polygon with bid/ask: execution-eligible
- Finnhub/FMP: informational
- yfinance/Finviz: display-only (never execution-eligible)
- Unknown: blocker

## Current Targets

6 symbols need refresh: 1 pending proposal (DWSN), 5 incubator candidates (stale).

## Tests

20/20 Q-1 + 15/15 R-2 regression.
