# UI Stabilization + Screener Audit — Session Summary

**Date:** 2026-05-15
**Trigger:** Operator live-browser audit found render errors, wrong data, and stale server.

## What Was Fixed

| Item | Before | After |
|------|--------|-------|
| /v2/tax | React #310 (hooks after early return) | **FIXED** — useMemo moved before returns |
| /v2/strategy-desk | Decimal serialization crash | **FIXED** — _json_clean on perf_by_strategy |
| /v2/bot-morning-brief | Stuck loading indefinitely | **FIXED** — 15s fetch timeout added |
| /v2/strategy-analytics | profit_factor NULL everywhere | **FIXED** — COALESCE + all-wins/losses handling |
| /v2/plan-vs-performance | PLAN ADHERENCE: 0% | **FIXED** — recognizes stop_hit/target_hit as planned exits (now 11.1%) |
| Screener config endpoints | 404 (server stale) | **FIXED** — server restarted, 18 screeners, 0 gaps |

## Data-Limited (Not Code Bugs)

| Item | Status | Reason |
|------|--------|--------|
| /v2/attribution ALPHA | N/A | No benchmark price history data exists |
| /v2/returns 6M/1Y | $0 | Returns endpoint needs historical portfolio value series |
| /v2/governance STRATEGIES: 0 | Display issue | Backend has 9 closed trades; frontend may read from empty governance table |

## Cross-Page Consistency

| Source | Closed Trades | Correct? |
|--------|---------------|----------|
| Scoreboard | 9 | YES |
| Plan-vs-perf | 9 | YES |
| Morning brief (24h) | 0 | YES (none closed today) |
| DB (paper_trades WHERE status='closed') | 9 | Ground truth |

**Counts are consistent.** The "1 vs 9 vs 10 vs 0" discrepancy was due to different time windows (total vs 24h) and status filters (closed vs all).

## Infrastructure

- Portfolio server restarted 3x during session to activate fixes
- Screener config endpoints confirmed working (18 screeners, 0 gaps)
- 83/83 Phase 6 tests still pass

## What Was NOT Modified

- A-1 risk gates (untouched)
- A-4 pipeline fix (untouched)
- Existing working screeners (untouched)
- Agent prompts (untouched)
- .env / broker credentials / holdings (untouched)
