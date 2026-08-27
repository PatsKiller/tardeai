# ExecutionTimingPanel Design

## Data source: GET /api/v2/atm/execution-timing-health

## Show per trade:
- order_submitted_at
- order_filled_at
- time_to_fill_seconds
- slippage_pct
- fill_price
- intended_entry
- missing fields count

## Summary:
- Total trades with timing data
- Missing order_submitted_at count
- Missing order_filled_at count
- Average time to fill
- Average slippage
