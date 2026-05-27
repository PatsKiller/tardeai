# API Design v3.3/v3.4

## GET /api/v2/atm/stop-proof
Returns per open trade: symbol, stop_loss, stop_order_id, stop_verified_at, verification_status.
Read-only. No order writes.

## GET /api/v2/atm/execution-timing-health
Returns: total trades, timing field population counts, average TTF, average slippage.
Read-only. No order writes.

## Safety block in both:
```json
{
  "read_only_endpoint": true,
  "orders_placed": "NONE",
  "stops_modified": "NONE"
}
```
