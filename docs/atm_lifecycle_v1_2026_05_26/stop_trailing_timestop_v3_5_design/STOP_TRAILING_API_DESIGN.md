# Stop/Trailing API Design

## GET /api/v2/atm/stop-trailing-control
Per open trade:
- symbol, account, strategy_id, strategy_family
- entry_price, current_price (if available), current R
- db_stop, stop_order_id, stop_verified_at, broker_stop_status
- trailing_tier_current, trailing_tier_next, trailing_threshold
- time_stop_type, time_stop_max_hold, days_held, time_stop_status, overdue_by
- recent_stop_changes (from lifecycle_events)
- recommended_action, safe_actions, blocked_actions

## GET /api/v2/atm/stop-change-audit
- All stop-change lifecycle_events sorted by time DESC
- Per event: paper_trade_id, symbol, old_stop, new_stop, change_type, source, reason, broker_proof, timestamp
- Filters: change_type, symbol, date range
