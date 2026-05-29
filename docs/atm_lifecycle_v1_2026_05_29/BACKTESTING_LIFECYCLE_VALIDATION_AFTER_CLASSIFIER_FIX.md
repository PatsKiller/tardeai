# Backtesting Lifecycle Validation After Classifier Fix

**Date:** 2026-05-29
**Health check:** PASS (7/7)

## strategy_backtest_trades Completeness

| Metric | Count |
|--------|-------|
| Total rows | 3,593 |
| Classified | 3,592 (99.97%) |
| Unclassified | 1 (SHFS id=860 — no enrichment data available) |

## Source Type Distribution

| Source Type | Count | Description |
|-------------|-------|-------------|
| champion_simulation (BT_*) | 3,516 | Hypothetical strategy simulations |
| replay (ER_*) | 77 | Actual trade replays from paper/broker data |

Champion simulations are clearly distinguishable by `run_id` prefix (`BT_` vs `ER_`). The backtesting view can filter on this to separate hypothetical from real.

## trades View Status

| Source | Unclassified | Notes |
|--------|-------------|-------|
| trade_transactions | 153 | Expected — no strategy_id column exists. These will always show unclassified. |

The source/writer fix means this no longer controls backtest classification completeness. The classifier now reads and writes `strategy_backtest_trades` directly via `--source strategy_backtest_trades`.

## Validation Checks

| Check | Result |
|-------|--------|
| Champion simulations identifiable by run_id prefix | PASS (BT_* = 3,516) |
| Replay trades identifiable by run_id prefix | PASS (ER_* = 77) |
| Real paper trades in paper_trades table | 38 with strategy_id, 16 closed |
| Source filters are data-driven (run_id prefix) | PASS |
| Classified backtest rows no longer resurface | PASS (--source strategy_backtest_trades reads same table it writes) |
| Remaining unclassified count accurate | PASS (1 row: SHFS) |
| No LLM apply run for this validation | PASS (read-only) |

## Strategy Distribution (Top 10)

| Strategy | Count |
|----------|-------|
| income_add | 311 |
| earnings_pre_buildup | 311 |
| tax_loss_harvest | 311 |
| core_index | 311 |
| international_dividend | 311 |
| high_yield_income_bdc | 311 |
| bond_income | 311 |
| covered_call_income | 311 |
| earnings_post_momentum | 311 |
| cash_or_stable | 311 |

The even distribution across 10 strategies (311 each) indicates these are champion simulations run uniformly across all strategies. The remaining strategies (momentum_scalp, swing_breakout, etc.) have lower counts from actual replay trades and targeted classifications.

## Recommendation

Backtesting lifecycle is validated. The classifier phase is complete for strategy_backtest_trades. Only SHFS (id=860) remains unclassified pending enrichment data. No further classifier batches needed.
