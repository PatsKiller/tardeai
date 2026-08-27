# Backtesting Lifecycle Validation After Classifier Fix

**Date:** 2026-05-28

## strategy_backtest_trades Status

| Metric | Count |
|--------|-------|
| Total rows | 2,568 |
| Classified | 2,567 (99.96%) |
| Unclassified | 1 (SHFS id=860, needs enrichment data) |

## trades View Status

| Metric | Count |
|--------|-------|
| Unclassified closed trades | 153 |
| Source | trade_transactions (no strategy_id column) |

These 153 rows will always appear unclassified because `trade_transactions` has no `strategy_id` column. This is now understood and documented — the classifier no longer targets these rows for `--apply`. The `--source strategy_backtest_trades` mode bypasses this entirely.

## Source/Writer Mismatch Impact

**Resolved.** The classifier's `--apply` mode now requires `--source strategy_backtest_trades`, which reads and writes the same table. trade_transactions rows no longer control backtest classification completeness.

## Classification Distribution (Top 20)

| Strategy | Count |
|----------|-------|
| earnings_pre_buildup | 216 |
| bond_income | 216 |
| cash_or_stable | 216 |
| tax_loss_harvest | 216 |
| core_index | 216 |
| covered_call_income | 216 |
| high_yield_income_bdc | 216 |
| international_dividend | 216 |
| income_add | 216 |
| earnings_post_momentum | 216 |
| momentum_scalp | 88 |
| fib_retracement_bounce | 61 |
| all_signals | 59 |
| swing_breakout | 40 |
| speculative_growth | 39 |
| gap_and_go | 32 |
| swing_trade | 31 |
| recovery_watch | 19 |
| sector_rotation | 11 |
| dividend_growth_compounder | 8 |

## Validation Checks

- Classified rows no longer resurface due to trade_transactions mismatch: **PASS**
- Remaining unclassified count is accurate for strategy_backtest_trades: **PASS** (1 row)
- No LLM apply was run for lifecycle validation: **PASS**
