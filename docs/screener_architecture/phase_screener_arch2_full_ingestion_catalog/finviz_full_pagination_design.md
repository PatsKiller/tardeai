# SCREENER-ARCH-2 FinViz Full Ingestion Design

## Key Finding

**FinViz Elite `/export?` endpoint returns ALL matching rows as a single CSV.**
There is no pagination needed. The export is a complete result set.

The old `[:50]` and SCREENER-ARCH-1's `[:500]` were both Python-side truncation
of an already-complete CSV download. The fix is simply removing the cap.

## New Behavior

- No artificial truncation — all CSV rows are returned
- Emergency safety cap at 5,000 rows per screener (prevents memory issues)
- If emergency cap is hit, status = `EMERGENCY_CAP` and operator is alerted
- New ticker incubator insertion raised from 10 to 200 per screener per run

## Stop Conditions

| Condition | Behavior |
|-----------|----------|
| CSV complete | Return all rows (normal) |
| Empty CSV | Return empty, log warning |
| Rows > 5000 | Cap at 5000, log EMERGENCY_CAP |
| Auth/cookie failure | Return empty, send Telegram alert |
| Rate limit (429) | Retry 3x with 5s delay, then fail |
| Network error | Return empty, log error |

## Config

| Parameter | Value | Location |
|-----------|-------|----------|
| MAX_ROWS_PER_SCREENER | 5000 | finviz_screener_runner.py |
| MAX_NEW_PER_SCREENER | 200 | finviz_screener_runner.py |
| Retry attempts | 3 | finviz_ingestion.py |
| Rate limit delay | 5s | finviz_ingestion.py |

## Before/After

| Metric | Before (50 cap) | ARCH-1 (500) | ARCH-2 (full) |
|--------|-----------------|--------------|---------------|
| Max per screener | 50 | 500 | All (5000 emergency) |
| New per screener | 10 | 10 | 200 |
| Data loss | 95%+ | ~50% on large screeners | 0% normal |
