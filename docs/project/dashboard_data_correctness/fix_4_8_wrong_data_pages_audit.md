# Fix 4-8: Wrong Data Pages Audit

**Date:** 2026-05-16
**Status:** RESOLVED — all pages either fixed or correctly showing insufficient-data states

## Summary

| Page | Status | Explanation |
|------|--------|-------------|
| Attribution | CORRECT | Shows "N/A" + tooltip "insufficient benchmark return data" — this is accurate |
| Governance | CORRECT | Returns ok=True with 9 rows of real data |
| Profit factor | FIXED (42846b6) | COALESCE NULL sums + all-wins edge case |
| Returns | CORRECT | Shows "—" + "Insufficient snapshot history" — requires 180/365 days of snapshots |
| Plan-vs-perf | FIXED (42846b6) | Now shows 11.1% adherence (was 0%) |

## Detail

### 1. Attribution (alpha, benchmark CAGR)
- **Endpoint:** `/api/v2/attribution`
- **Current:** alpha=None, bench_cagr=None
- **Root cause:** No benchmark price history for ITA component
- **Frontend handles it:** YES — shows "N/A" with clear explanation tooltip
- **Fix needed:** DATA POPULATION (import SPY/ITA/AGG prices), not code change
- **Status:** Correctly displays insufficient state

### 2. Governance
- **Endpoint:** `/api/v2/paper-performance-governance`
- **Current:** ok=True, 9 rows
- **Status:** WORKING correctly

### 3. Profit Factor (scoreboard)
- **Endpoint:** `/api/v2/strategy-analytics/scoreboard`
- **Fixed in:** commit 42846b6 (COALESCE NULL sums, all-wins = 999.0, all-losses = 0.0)
- **Status:** FIXED

### 4. Returns (6M, 1Y)
- **Endpoint:** `/api/v2/paper-portfolio-performance` (served via portfolio_server)
- **Current:** Shows "—" with "Insufficient snapshot history"
- **Root cause:** System started ~10 days ago — needs 180+ days of daily snapshots for 6M
- **Frontend handles it:** YES — shows clear insufficient-data state with explanation
- **Fix needed:** TIME (accumulate daily snapshots), not code change
- **Status:** Correctly displays insufficient state

### 5. Plan-vs-Performance
- **Endpoint:** `/api/v2/plan-vs-performance`
- **Fixed in:** commit 42846b6 (recognizes stop_hit/target_hit as planned exits)
- **Current:** adherence=11.1%, closed=9, win_rate=22.2%
- **Status:** FIXED

## Conclusion

All 5 pages are either:
- Already fixed (profit_factor, plan-vs-perf) — commit 42846b6
- Correctly showing insufficient-data states (attribution, returns) — needs time/data, not code
- Working correctly (governance)

No further code changes needed. The dashboard is showing honest data.
