# Stop/Trailing Source of Truth

| Field | Source | Table/Script |
|-------|--------|-------------|
| DB stop_loss | paper_trades.stop_loss | unified_stop_supervisor.py |
| Broker stop order ID | paper_trades.stop_order_id | unified_stop_supervisor.py |
| Stop verified at | paper_trades.stop_verified_at | atm_position_reconciler.py (future) |
| Strategy trailing policy | strategy_trailing_policy.py TRAILING_TIERS | hardcoded in script |
| Strategy family | strategy_trailing_policy.py STRATEGY_FAMILIES | hardcoded |
| Current trailing tier | computed from current R vs tier thresholds | unified_stop_supervisor.py |
| Time-stop config | strategy_trailing_policy.py time_stop dict | per-family |
| Time-stop status | computed from entry_time + max_hold_days | api_v2.py (P0.5B) |
| Stop change history | NOT RECORDED | **GAP** |
