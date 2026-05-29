# SHFS id=860 Pre-State Export — 2026-05-29

## Summary
SHFS id=860 is the **sole unclassified row** in `strategy_backtest_trades` (3,592/3,593 classified).

## Row Data
| Field | Value |
|-------|-------|
| id | 860 |
| simulated_trade_id | ER_ER_20260_SHFS_2025-09-24 |
| run_id | ER_20260521121822_32aeb8 |
| strategy_id | NULL (empty) |
| symbol | SHFS (SHF Holdings Inc, Class A — cannabis banking/fintech micro-cap) |
| signal_time | 2025-09-24 |
| direction | long |
| entry_price | 6.78 |
| stop_price | 6.441 |
| target_price | 7.3224 |
| exit_price | 6.441 |
| pnl | -0.339 (-5.0%) |
| r_multiple | -1.0 |
| exit_reason | stop_hit |
| hold_days | 1 |
| MFE | 5.6% |
| MAE | -13.27% |
| broker | schwab |
| account | schwab_rollover_ira |

## Related Rows
| Table | Count | Notes |
|-------|-------|-------|
| paper_trade_proposals | 0 | No proposals exist for SHFS |
| paper_trades | 0 | No paper trades for SHFS |
| watchlist_strategy_cards | 0 | No watchlist cards for SHFS |
| ticker_strategy_classifications | 0 | No ticker classifications for SHFS |
| trade_transactions | 3 | Buy 2025-09-24 @6.78, Sell 2025-09-25 @6.57, partial fill @0.00 — all json_migration imports |
| market_ohlcv_bars | 0 | No market data |
| news_articles | 0 | No news |
| screener_symbol_membership | 0 | No screener data |

## Why Unclassified
- `strategy_id` is NULL/empty string
- Classifier filter: `WHERE strategy_id IS NULL OR strategy_id = '' OR strategy_id = 'unknown'`
- All three enrichment sources (ticker_strategy_classifications, watchlist_strategy_cards, paper_trade_proposals) have zero data for SHFS

## Full JSON Export
See: `shfs_860_pre_state.json`
