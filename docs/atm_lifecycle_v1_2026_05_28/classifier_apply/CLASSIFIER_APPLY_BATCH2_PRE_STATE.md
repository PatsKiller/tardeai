# Classifier Apply Batch 2 — Pre-State

**Date:** 2026-05-28
**Pre-apply snapshot before batch 2 (limit 30)**

## Remaining Unclassified Trades

| Source | Count |
|--------|-------|
| schwab/schwab_rollover_ira (trade_transactions) | 31 |
| schwab/schwab_taxable (trade_transactions) | 23 |
| schwab/schwab_roth_ira (trade_transactions) | 1 |
| **Total** | **55** |

Note: These are the same 55 symbols from batch 1. The `trades` view pulls from `trade_transactions` which was not directly updated by the classifier. The classifier updates `strategy_backtest_trades.strategy_id`. Some of these 55 have already had their backtest rows classified in batch 1, but the trade_transactions rows remain "unclassified" in the view.

## Remaining Unclassified Backtest Trades

4 rows with NULL/empty/unknown strategy_id.

## Existing Backtest Classification Distribution (Top 15)

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
| speculative_growth | 37 |

## Hold-Period Gate Status

Commit 97cf173 active. Rules: hard gate, caution gate, exception path, conflict gate, ADBE rule.
