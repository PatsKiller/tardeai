# Dashboard Data Correctness — Closeout

**Date:** 2026-05-16
**Status:** COMPLETE

## Fix Summary

| Task | Status | Commit/Evidence |
|------|--------|-----------------|
| Fix 1-3: Hard broken pages | DONE | TaxLots hooks, StrategyDesk Decimal, MorningBriefBot timeout (42846b6) |
| Fix 4: Attribution | DATA GAP | Shows "N/A" correctly — needs benchmark price import |
| Fix 5: Governance | WORKING | Returns 9 rows of real data |
| Fix 6: Profit factor | FIXED | COALESCE + edge cases (42846b6) |
| Fix 7: Returns | DATA GAP | Shows "Insufficient snapshot history" correctly — needs time |
| Fix 8: Plan-vs-perf | FIXED | Recognizes stop_hit/target_hit (42846b6), now 11.1% |
| Fix 9: Cross-page consistency | VERIFIED | 9 closed trades across all endpoints |

## Data Gaps (Not Code Defects)

These require data population, not code changes:

1. **No benchmark price history** — Attribution shows "N/A" until SPY/ITA/AGG daily prices are imported
2. **No portfolio snapshot series** — Returns shows "—" until 180+ days of daily snapshots accumulate
3. **Insufficient closed trade sample** — Strategy scorecards correctly marked "insufficient" (< 5 trades each)

## Verification

- Tests: 107/107 pass (83 Phase 6 + 15 Phase 7 + 9 Phase 8B)
- ALPACA_MODE: paper
- LLM_DISABLE_LIVE_EXECUTION: true
- Holdings: $1,189,125
- Phase 8B scorecards: human_review_only
- Strategy activation: unchanged
- No code changes needed for Fix 4-9

## Remaining Action

Wait for A-5 observation final review on 2026-05-22.
