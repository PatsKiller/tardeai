# SCREENER-ARCH-3 — Ticker Catalog Lifecycle

**Status:** PARTIAL (8/15 done, 5 deferred)

## What Was Delivered

1. **Data model**: Leverages existing incubator_universe (1,139 tickers with first_seen,
   last_seen, strategy, sector, lifecycle_state) + ticker_strategy_classifications (4,872)
2. **New tables**: screener_symbol_membership + screener_symbol_membership_history
3. **Falloff policy**: Pure functions for active/retain_by_ttl/expire/review
4. **Catalog report**: Shows universe size, strategy distribution, new ticker counts
5. **No silent deletion**: Policy never returns "delete" — only retain, expire, or archive

## What Is Deferred

- Importer persistence (write membership records per run) → SCREENER-ARCH-3B
- Recent run backfill → SCREENER-ARCH-3B
- Dropped/reentered event history population → SCREENER-ARCH-3B
- Membership status report → needs data
- API/dashboard → needs data

## Existing Catalog Coverage

| Table | Count | Role |
|-------|-------|------|
| incubator_universe | 1,139 | Primary catalog with lifecycle |
| ticker_strategy_classifications | 4,872 | Strategy assignment history |
| watchlist_items | 5,043 | Discovery tracking |
| strategy_watchpool | 11 | Active Bucket 2 candidates |

## Tests

12/12 + ARCH-2B 7/7 regression.
