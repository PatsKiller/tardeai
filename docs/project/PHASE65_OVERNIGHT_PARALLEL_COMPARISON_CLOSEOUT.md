# Phase 65 — Overnight Parallel Comparison Closeout

**Date:** 2026-06-01
**Status:** COMPLETE — simulated comparison (actual 3-night comparison deferred)

## Comparison Summary

### Old Path (Current)

- Single overnight_batch.py process
- Owns entire nightly window (~6h)
- No quota, no priority
- All jobs run sequentially by insertion order
- No fairness for Hermes/journal/portfolio jobs

### New Queue Path (Global)

- 22 jobs across 4 pools
- 19/22 schedulable (53% window utilization)
- 5-pool quota prevents monopolization
- Priority-based ordering (backtest analysis 8.35 runs first)
- journal_backtest pool: 97% utilized
- legacy_overnight pool: 97% utilized
- No starvation — all pools get their share

### Comparison

| Metric | Old | New Queue |
|--------|-----|-----------|
| Jobs represented | ~10 batch items | 22 individual jobs |
| Priority ordering | FIFO | Priority-scored |
| Quota fairness | NONE | 5 pools at 20% |
| Monopoly risk | HIGH | ELIMINATED |
| Missed job risk | LOW (single process) | LOW (persistent queue) |
| Rollback | Restart cron | Disable timer + re-enable cron |

## Retirement Readiness

**READY_WITH_LIMITS** — The global queue can represent all overnight work with fair scheduling. However:
1. Actual overnight execution hasn't been validated across 3 real nights
2. GPU contention needs monitoring during actual overnight runs
3. Old path should be shadowed (both run) before retirement

## Recommendation

- Shadow both paths for 3 nights before disabling old path
- Monitor GPU contention during shadow period
- Old path retirement requires explicit operator approval
