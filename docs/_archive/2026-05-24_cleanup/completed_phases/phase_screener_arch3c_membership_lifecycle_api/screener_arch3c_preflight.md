# SCREENER-ARCH-3C Preflight

**Date:** 2026-05-19

## Safety

- ALPACA_MODE=paper
- LLM_DISABLE_LIVE_EXECUTION=true
- Holdings guard: $1,194,906

## Git State

```
4e48fa4 JOURNAL-UX-1 closed trade postmortem dashboard and lessons model
7ecf9a6 SCREENER-ARCH-3B populate screener membership lifecycle
d85f928 SCREENER-ARCH-3 add ticker catalog lifecycle
f2f4682 SCREENER-ARCH-2B add broad screener cap overrides
```

## Current Membership State

| Metric | Value |
|--------|-------|
| Total memberships | 1,941 |
| All status | present (100%) |
| History events | 1,941 entered |
| Dropped events | 0 |
| Reentered events | 0 |
| Stale events | 0 |
| Expired events | 0 |

## Screener IDs in Membership

- `screener` (FinViz)
- `social` (StockTwits/Reddit)
- `screener+social` (combined)
- `premarket_social`

## Run Labels (time slots)

0400, 0700, 0900, 1000, 1200, 1400, 1600, 1730, Pre-Market StockTwits, Social Scalp

## Scans by Date (last 14d)

| Date | Count |
|------|-------|
| 2026-05-19 | 1,304 |
| 2026-05-18 | 1,409 |
| 2026-05-15 | 347 |
| 2026-05-14 | 45 |
| 2026-05-13 | 34 |
| 2026-05-12 | 42 |
| 2026-05-11 | 45 |
| 2026-05-08 | 41 |
| 2026-05-07 | 123 |
| 2026-05-06 | 388 |

## Gap Analysis

- **479 symbols** in membership NOT seen in last 3 days — should be marked dropped
- No `screener_label` column populated (individual screener names not tracked in scans)
- Membership uses `source` as screener_id (screener/social/premarket_social/screener+social)
- No multi-screener symbol overlap detected (each symbol appears in one source type)

## Conclusion

Preflight PASSED. Safe to proceed with transition detection.
