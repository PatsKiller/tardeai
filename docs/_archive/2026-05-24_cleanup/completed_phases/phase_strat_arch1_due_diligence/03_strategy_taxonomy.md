# STRAT-ARCH-1: Strategy Taxonomy Architecture

## Current Taxonomy (23 strategies)

| Family | Timeframe | Bucket | Strategies |
|--------|-----------|--------|------------|
| **Intraday** | INTRADAY | SAME_DAY | momentum_scalp (3 criteria), gap_and_go (3) |
| **Short Swing** | SHORT_SWING | MULTI_DAY | swing_breakout (4), swing_trade (4), earnings_catalyst (1), earnings_post_momentum (3), earnings_pre_buildup (3), speculative_growth (3), fib_retracement_bounce (4) |
| **Medium Swing** | MEDIUM_SWING | MULTI_DAY | recovery_watch (3+4dq), sector_rotation (3) |
| **Position** | POSITION | LONG_CYCLE | dividend_growth_compounder (0), core_growth_compounder (1), income_add (2), covered_call_income (2), bond_income (0), reit_income (0), high_yield_income_bdc (0), international_dividend (0), defense_thesis (0) |
| **Cash** | CASH | LONG_CYCLE | cash_or_stable (0), core_index (0) |
| **Tax** | SHORT_SWING | LONG_CYCLE | tax_loss_harvest (0) |

## Architecture Gaps

### Gap T-1: 9 Strategies Have Zero Entry Criteria
bond_income, cash_or_stable, core_index, defense_thesis, dividend_growth_compounder,
high_yield_income_bdc, international_dividend, reit_income, tax_loss_harvest all have
0 entry criteria in their YAML. The router scores them at 0+bonuses = max ~30 (price+rvol+catalyst).
They will never win a route competition against strategies with criteria.

**Impact:** These strategies can only be assigned through manual selection or incubator
metadata, never through the router. They are effectively invisible to the routing engine.

**Recommended fix:** Add at minimum 2-3 entry criteria per strategy (market cap range,
dividend yield threshold, sector filter) so they can participate in routing.

### Gap T-2: No Family-Level Gating
An INTRADAY micro-cap runner should not be evaluated against POSITION dividend strategies.
Currently all 23 strategies are evaluated for every candidate regardless of family.

**Recommended fix:** Pre-filter by family before scoring. Only evaluate strategies
whose timeframe_class is compatible with the candidate's characteristics.

### Gap T-3: Earnings Strategies Overlap
earnings_catalyst (1 criteria), earnings_post_momentum (3), earnings_pre_buildup (3)
all target earnings-related setups but have different criteria counts. The router
may prefer earnings_post_momentum over earnings_catalyst simply because it has more
criteria (3 x 10 = 30 vs 1 x 10 = 10).

**Recommended fix:** Earnings strategies should have consistent criteria counts or
weighted scoring. An earnings_catalyst with 1 strong criterion should not automatically
lose to earnings_post_momentum with 3 weak criteria.

### Gap T-4: Speculative/Growth Strategies Overlap
speculative_growth, core_growth_compounder, and swing_breakout all target growth
setups but at different timeframes. No mutual exclusion rules exist.

**Recommended fix:** Add co-enablement/exclusion rules that prevent a POSITION
strategy from being primary when an equivalent SHORT_SWING is available and stronger.

## Criteria Coverage Summary

| Criteria Count | Strategies | Issue |
|---------------|------------|-------|
| 0 | 9 strategies | Cannot participate in routing |
| 1 | 1 (earnings_catalyst) | Chronically underscored |
| 2 | 2 (covered_call, income_add) | Low scoring potential |
| 3 | 7 strategies | Standard |
| 4 | 3 (swing_breakout, swing_trade, fib) | Highest base scores |
