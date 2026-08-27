# Emergency Cap Review

## Is 5,000 still truncating data?

**YES.** 4 broad ETF/income screeners exceed 5,000 rows.

## Recommendation

Raise per-screener cap for these 4 screeners to 10,000.
Keep global default at 5,000.

**Deferred to SCREENER-ARCH-2B** — requires per-screener config mechanism.
Current code uses a single `MAX_ROWS_PER_SCREENER = 5000` constant.

## Missed Rows

~3,194 rows across 4 screeners. These are mostly ETFs and broad income
instruments — important for position/compounder strategies but not
urgent for intraday/momentum pipeline.
