# SCREENER-MAP-2 — Shadow Source Runs

**Status:** COMPLETE
**Date:** 2026-05-21

## Shadow Source Health: 10/23 strategies HEALTHY

| Health Status | Count | Strategies |
|---------------|-------|------------|
| HEALTHY | 10 | momentum_scalp, gap_and_go, swing_breakout, swing_trade, recovery_watch, speculative_growth, sector_rotation, dividend_growth_compounder, earnings_catalyst, core_growth_compounder |
| NEEDS_PROMOTER_THRESHOLD_REVIEW | 4 | income_add (29 inc, 0 prop), fib_retracement_bounce (27, 0), earnings_pre_buildup (18, 0), earnings_post_momentum (10, 0) |
| LOW_CANDIDATE_VOLUME | 6 | bond_income (2), cash_or_stable (1), core_index (4), covered_call_income (1), defense_thesis (2), reit_income (5) |
| CLASSIFIED_NOT_INCUBATED | 2 | high_yield_income_bdc (1,377 classified, 0 incubator), international_dividend (213 classified, 0 incubator) |

## Pipeline Flow Summary

```
Finviz Screeners (27 active) → Classification (9,273 symbols, 14 types)
                                     ↓
                            Incubator (1,533 symbols, 22 strategies)
                                     ↓
                            Promoter (hourly 7-5 M-F)
                                     ↓
                            Proposals (94 total, 13 strategies)
```

## Key Findings

### 1. Four strategies need PROMOTER threshold review (SCREENER-MAP-3)
- `income_add`: 29 incubator candidates, 0 proposals → promoter likely blocking on momentum-style score/spread gates
- `fib_retracement_bounce`: 27 candidates, 0 proposals → promoter doesn't know how to evaluate retracement setups
- `earnings_pre_buildup`: 18 candidates, 0 proposals → needs earnings date proximity logic
- `earnings_post_momentum`: 10 candidates, 0 proposals → needs post-earnings confirmation logic

### 2. Two strategies classified but not incubated
- `high_yield_income_bdc`: 1,377 classified symbols but 0 in incubator → weekly builder doesn't pick them up (likely no GO/WAIT scans)
- `international_dividend`: 213 classified but 0 in incubator → same issue

### 3. Six strategies have low but non-zero flow
These have 1-5 incubator candidates. They work but need more screener diversity or broader criteria.

### 4. Source types fully functional
- **Finviz momentum/gap/breakout**: HEALTHY (10 strategies producing proposals)
- **Finviz dividend/income**: HEALTHY at classification level (1,377-1,739 symbols), BLOCKED at incubator/promoter level
- **Finviz sector/defense**: Working (sector_rotation producing proposals)
- **Earnings calendar**: STUB only (no actual earnings date provider)
- **Options chain**: STUB only (no options data provider)
- **Technical pattern**: STUB only (uses existing OHLCV but no dedicated pattern engine)

## What MAP-2 Proved

1. All 27 Finviz screeners are active and classifying symbols ✓
2. Classification → incubator pipeline works for most strategies ✓
3. The "single screener" diagnosis was wrong — 14 strategy types are actively classified ✓
4. The bottleneck for non-momentum strategies is the **promoter**, not the screeners
5. Two strategies (high_yield_income_bdc, international_dividend) have a builder gap — classified but not incubated

## Recommendations for SCREENER-MAP-3

1. **Family-specific promoter thresholds** — income/dividend strategies need different score/spread/rvol gates than momentum
2. **Fix weekly builder** to include high_yield_income_bdc and international_dividend classifications
3. **Add earnings date awareness** to promoter for earnings_pre/post strategies
4. **Add technical pattern scoring** for fib_retracement_bounce
5. **Reduce spread gate** from 3% to 5-8% for income/dividend strategies (they're large-cap, more liquid)

## Safety
- No proposals created
- No trades created
- No orders submitted
- No strategy activation changed
- No YAML thresholds changed
- No Finviz criteria changed
- ALPACA_MODE=paper
