# Stop Order Proof Patch Design

## Where stops are placed
- `scripts/unified_stop_supervisor.py` — `_place_stop()` or `_update_stop()`
- `scripts/alpaca_paper_adapter.py` — `submit_stop_order()` if exists

## Patch
After successful stop order creation via Alpaca API:
```python
UPDATE paper_trades SET stop_order_id = %s WHERE id = %s
```

## Verification (read-only)
After stop_order_id is stored, reconciler can query:
```python
alpaca_api.get_order(stop_order_id)
```
If order exists and status is 'accepted'/'new', set stop_verified_at = now().

## Safety
- Never cancel/replace stops in this patch
- Verification is read-only API query only
