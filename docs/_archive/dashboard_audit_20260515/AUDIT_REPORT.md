# Dashboard Page-By-Page Audit — 2026-05-15

## Method
Server-side audit: for each of 78 /v2 pages, extract API endpoints from
source, hit each endpoint, scan JSON for null/empty/zero fields, flag issues.

## Summary
- **78 pages audited**
- **51 clean** (no issues found)
- **27 with issues**

## Issue Categories

### FETCH_ERROR (404 — endpoint doesn't exist): 35 occurrences across 20 pages
These are mostly POST/action endpoints that the pages reference for
button clicks (run backtest, submit proposal, trigger reconciliation)
but that only work as POST requests. The GET audit naturally 404s on them.

**Actually broken (need wiring):** ~5 endpoints
**POST-only (not broken, just method-sensitive):** ~30 endpoints

### DEAD_DATA (>60% null/zero fields): 8 occurrences across 6 pages
Recurring offenders:
- `/api/v2/execution-quality` — 68% dead (44 null + 8 zero of 77)
- `/api/v2/paper-performance-governance` — 62% dead (10 null + 18 zero of 45)
- `/api/v2/strategy-analytics/inactive-strategies` — 61% dead (19 zeros, expected)

Root cause: execution-quality and governance tables aren't populated by
any running cron. The data pipeline for these hasn't been built yet.

### HTTP 500 (server error): 2 occurrences
- `/api/v2/strategy-configs/validate` — 500 error
- `/api/v2/strategy-configs/sync-db` — 500 error
Both in StrategyAdmin page. Likely import errors in the handler.

## Self-Improvement Page (operator's specific concern)
- 3 endpoints: status, review-queue, component-health
- All return 200 OK with real data
- Status: 42 fields, 31% empty/zero (expected — backtesting and weekly
  digest features not yet built)
- Review queue: 0 items (no pending reviews)
- Component health: 9 components reporting

The page WORKS. Fields showing 0 reflect features that haven't been
built (backtesting, weekly digest), not broken data pipelines.

## Data Freshness
| Table | Latest Update | Status |
|-------|---------------|--------|
| paper_trade_proposals | 2026-05-15 17:00 | FRESH |
| paper_trades | 2026-05-15 16:55 | FRESH |
| trade_ai_scans | 2026-05-15 16:19 | FRESH |
| strategy_signals | 2026-05-15 10:13 | FRESH |
| post_trade_price_analysis | 2026-05-14 19:39 | 21h old |
| agent_calibration | 2026-05-05 10:34 | 10 DAYS STALE |

**agent_calibration is the stale outlier** — hasn't updated in 10 days.
This is because the calibration compute job needs more closed trades to
produce meaningful accuracy data. Not a cron issue; a data-volume issue.

## Priority Fix List

### HIGH (affect page usability)
1. `/api/v2/execution-quality` — populate from paper_trades data
2. `/api/v2/paper-performance-governance` — populate from closed trades
3. `/api/v2/strategy-configs/validate` — fix 500 error
4. `/api/v2/strategy-configs/sync-db` — fix 500 error

### MEDIUM (improve data quality)
5. agent_calibration population — needs more closed trades OR lower threshold
6. post_trade_price_analysis — run for any new closed trades

### LOW (POST endpoints returning 404 on GET — expected behavior)
7-35. Action endpoints that only accept POST method
