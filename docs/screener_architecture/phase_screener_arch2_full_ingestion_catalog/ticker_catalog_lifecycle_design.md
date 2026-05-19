# SCREENER-ARCH-2 Ticker Catalog and Lifecycle Design

## Current State

Tickers are tracked in:
- `trade_ai_scans` — per-scan records with DISTINCT ON (symbol) for latest
- `incubator_universe` — candidates for promotion
- `strategy_watchpool` — Bucket 2 candidates with TTL
- `watchlist_items` — discovery tracking

## Screener Membership Lifecycle

When a ticker is fetched from a screener:
- If NEW: add to watchlist_items + ticker_strategy_classifications
- If EXISTING: update last_seen timestamp

When a ticker falls OFF a screener:
- Keep in incubator/watchpool for strategy TTL
- Mark `source_missing` after 2 consecutive runs without appearance
- Decay maturity score gradually
- Expire after TTL if no renewed signal
- Archive (not delete) after expiry

When a ticker RE-ENTERS:
- Mark `reentered`
- Reset/refresh maturity
- Log reentry event

## Design Principles

1. Never silently delete operator-relevant candidates
2. Track first_seen / last_seen / consecutive_missing per screener
3. Retain history for strategy proof analysis
4. Use existing tables — avoid schema sprawl
5. Incubator `days_active` and `status` already support lifecycle
