# Order Timing Capture Patch Design

## Where orders are created
- `scripts/proposal_paper_submitter.py` — calls alpaca_paper_adapter
- `scripts/alpaca_paper_adapter.py` — `submit_order()` function

## Patch points

### order_submitted_at
Set in `alpaca_paper_adapter.py` immediately before `api.submit_order()`:
```python
paper_trades.order_submitted_at = datetime.now(timezone.utc)
```

### broker_order_id
Already partially captured. Ensure `api.submit_order()` response `order.id` is stored.

### order_filled_at
Set when `paper_execution_sweep.py` or `alpaca_paper_adapter.py` detects fill:
```python
paper_trades.order_filled_at = fill_event.filled_at or datetime.now(timezone.utc)
```

### time_to_fill_seconds
Computed in TCA: `order_filled_at - order_submitted_at`

## Safety
- No new orders placed by this patch
- Only writes to existing paper_trades rows that already have orders
