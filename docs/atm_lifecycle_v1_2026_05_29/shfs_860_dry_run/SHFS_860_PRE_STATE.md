# SHFS id=860 Pre-State — 2026-05-29 (Dry-Run Session)

## strategy_backtest_trades id=860
| Field | Value |
|-------|-------|
| id | 860 |
| simulated_trade_id | ER_ER_20260_SHFS_2025-09-24 |
| run_id | ER_20260521121822_32aeb8 |
| strategy_id | NULL |
| symbol | SHFS (SHF Holdings Inc Class A — cannabis banking/fintech micro-cap) |
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

## Backtest Run Metadata
| Field | Value |
|-------|-------|
| run_id | ER_20260521121822_32aeb8 |
| run_type | replay_trades |
| status | completed |
| engine | enterprise_backtester |
| mode | trades (price_replay) |
| date_range | 2022-12-28 to 2026-05-14 |
| symbols | 36 symbols including SHFS |

## Related Rows
| Table | Count |
|-------|-------|
| paper_trade_proposals | 0 |
| paper_trades | 0 |
| watchlist_strategy_cards | 0 |
| ticker_strategy_classifications | 0 |
| trade_transactions | 3 (Buy 2025-09-24 @6.78, Sell 2025-09-25 @6.57, partial fill @0.17) |
| market_ohlcv_bars | 0 |
| news_articles | 0 |

## Peer Trades (same ER run, similar profile)
Sub-$10 micro-cap, 1-day hold, stop_hit, -5%:
| ID | Symbol | Strategy | Entry | Exit | PnL% |
|----|--------|----------|-------|------|------|
| 837 | BNAI | speculative_growth | 4.05 | 3.85 | -5.0% |
| 827 | GXAI | speculative_growth | 2.02 | 1.92 | -5.0% |
| 849 | IBIO | speculative_growth | 2.02 | 1.92 | -5.0% |
| 816 | PHIO | speculative_growth | 1.37 | 1.30 | -5.0% |
| 831 | SHPH | speculative_growth | 4.29 | 4.08 | -5.0% |
| 808 | DFSC | speculative_growth | 3.00 | 2.85 | -5.0% |
| 821 | TRX | speculative_growth | 2.12 | 2.01 | -5.0% |
| 847 | MSGM | speculative_growth | 5.23 | 4.97 | -5.0% |
| 818 | FUSE | speculative_growth | 2.96 | 2.81 | -5.0% |

9/9 comparable peers classified as speculative_growth.

Non-speculative peers (different profile):
| ID | Symbol | Strategy | Notes |
|----|--------|----------|-------|
| 802 | GCTS | momentum_scalp | $1.49 (ultra-micro) |
| 809 | FATN | swing_trade | $3.53 |
| 824 | NUWE | recovery_watch | $4.37 |
| 872 | BRO | recovery_watch | $104 (not micro-cap) |
