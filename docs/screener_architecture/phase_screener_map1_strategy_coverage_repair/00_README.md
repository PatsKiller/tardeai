# SCREENER-MAP-1 — Strategy Source Coverage Repair

**Status:** COMPLETE
**Date:** 2026-05-21

## Executive Summary

The initial diagnosis ("single momentum screener feeds all strategies") was **wrong**. The system has:
- **27 active Finviz screeners** in `finviz_screeners` DB table, all ran within 2 days
- **18 screener definitions** in `assets/screeners.yaml` with run_windows
- **9,273 classified symbols** across 14 strategy types in `ticker_strategy_classifications`
- **23 strategy YAML files** defining the full strategy universe

## Root Cause

The pipeline broke at **one point**: the `weekly_incubator_builder.py` script had no cron job scheduled. It was designed to run weekly on Sunday but was never added to crontab. Result:
- Screeners ran and classified 9,273 symbols ✓
- Classifications sat in `ticker_strategy_classifications` ✓
- Incubator universe was last updated May 11 (10 days stale) ✗
- Promoter found no fresh incubator candidates ✗
- No proposals generated for non-momentum strategies ✗

## Fix Applied

1. **Ran `weekly_incubator_builder.py --apply`** — populated 20 strategy buckets with fresh candidates
2. **Added cron**: daily refresh at 8:15 AM + weekly rebuild Sunday 7 PM

## Incubator Coverage After Fix

| Strategy | Incubator Symbols | Status |
|----------|------------------|--------|
| speculative_growth | 213 | COVERED |
| earnings_catalyst | 195 | COVERED |
| recovery_watch | 185 | COVERED |
| sector_rotation | 177 | COVERED |
| swing_breakout | 159 | COVERED |
| screener | 145 | COVERED |
| dividend_growth_compounder | 121 | COVERED |
| swing_trade | 91 | COVERED |
| momentum_scalp | 44 | COVERED |
| gap_and_go | 41 | COVERED |
| income_add | 29 | COVERED |
| core_growth_compounder | 28 | COVERED |
| fib_retracement_bounce | 27 | COVERED (was 0!) |
| earnings_pre_buildup | 18 | COVERED (was 0!) |
| earnings_post_momentum | 10 | COVERED (was 0!) |
| reit_income | 5 | COVERED |
| tax_loss_harvest | 4 | COVERED |
| core_index | 4 | COVERED |
| defense_thesis | 2 | COVERED |
| bond_income | 2 | COVERED |
| cash_or_stable | 1 | COVERED |
| covered_call_income | 1 | COVERED |
| high_yield_income_bdc | 0 | NEEDS REFRESH |
| international_dividend | 0 | NEEDS REFRESH |

## Screener-to-Strategy Mapping (27 Finviz screeners)

All 27 screeners are active and running. Each is mapped to a specific strategy_type:
- Momentum: prime_setups, watchlist_setups (momentum_scalp, gap_and_go)
- Income: income_candidates, dividend_aristocrats, div_growth_quality, high_yield_income, etc.
- Earnings: earnings_catalyst_pre, post_earnings_gappers
- Technical: oversold_reversion, quality_pullback
- Sector: sector_leaders, defense_basket, defense_momentum
- ETF/Index: core_index_broad, bond_etf_income, covered_call_etf

## What Was NOT Missing

- Screener definitions — 27 exist and run ✓
- Strategy classifications — 9,273 active ✓  
- Finviz diversity — dividend, earnings, covered call, bond, sector screeners all defined ✓
- Source tracking columns — exist in DB ✓

## Remaining Gaps (for SCREENER-MAP-2)

1. **Earnings calendar source**: earnings_pre_buildup and earnings_post_momentum use screener signals but don't have actual earnings date data
2. **Options chain source**: covered_call_income classified 1 symbol but needs options liquidity data
3. **Strategy promoter thresholds**: income strategies may be blocked by momentum-style spread gates
4. **`strategy_id='screener'`**: 6 proposals classified as generic "screener" instead of a real strategy

## Safety

- ALPACA_MODE=paper
- No trades, orders, or approvals created
- No strategy activation changes
- No YAML thresholds changed
- No Finviz criteria changed
- No existing screeners deleted
