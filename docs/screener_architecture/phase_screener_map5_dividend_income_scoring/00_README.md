# SCREENER-MAP-5 — Dividend Income Scoring

**Status:** COMPLETE
**Date:** 2026-05-21

## Changes

### 1. New dividend-specific scoring policy
`dividend_income_scoring_policy.py` — replaces momentum-style scoring for DIVIDEND_INCOME candidates with 6 income-specific factors:

| Factor | Points | What it measures |
|--------|--------|-----------------|
| Dividend yield | 0-25 | Yield level (3-5% = 20pts, >5% = 25pts, >12% = yield trap warning) |
| Payout quality | 0-20 | Payout ratio sustainability (≤60% = 20pts) |
| Dividend growth | 0-20 | Consecutive growth years (≥25yr = aristocrat 20pts) |
| Income safety | 0-15 | PE ratio + market cap (value PE + institutional cap) |
| Liquidity | 0-10 | Average volume (≥1M shares = 10pts) |
| Quote readiness | 0-10 | Known quote available |

**Total: 100 points. Floor: 15 (was 30 momentum-style).**

### 2. Score floor lowered from 30 to 15
- `_DIVERSITY_SCORE_FLOOR` in promoter: 30 → 15
- `min_score` for DIVIDEND_INCOME family thresholds: 10 → 15
- This allows 122 dividend_growth_compounder + 29 income_add candidates to be evaluated

### 3. Yield trap protection
Yields above 12% trigger `REVIEW_REQUIRED` status and `yield_trap_warning`. Prevents blindly promoting unsustainably high-yield stocks.

### 4. Missing data handling
Dividend yield, payout ratio, and growth years are NOT in the current enrichment cache. The policy:
- Awards small base points (5 each) for being classified as income
- Uses available data (PE, market cap, volume) for safety/liquidity scoring
- Flags missing fields as warnings, not hard blocks
- NEE scores 47/100 with no yield data (from PE, cap, volume alone)

## Test Results (NEE example)
```
NEE: score=47 status=READY_PROMOTER
  yield=5, payout=5, growth=5, safety=12, liquidity=10, quote=10
  missing: dividend_yield, payout_ratio, dividend_growth_years
```

## Safety
- ALPACA_MODE=paper
- Promoter readiness ≠ execution approval
- No trades/orders created
- No YAML/Finviz changes
- No strategy activation changes
- Rollback: `scripts/rollback_screener_map5_dividend_income_scoring.sh`
