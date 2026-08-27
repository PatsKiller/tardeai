# Stop Proof Reconciler Patch Design

## Target: scripts/atm_position_reconciler.py

## Add stop verification mode
New flag: `--verify-stops`

Behavior:
1. For each open paper_trade with stop_order_id:
   - Query Alpaca API: `GET /v2/orders/{stop_order_id}`
   - If order exists and status in (accepted, new, held): classify as stop_verified
   - If order not found or canceled: classify as stop_order_missing
2. For trades without stop_order_id:
   - Classify as stop_order_id_missing
3. Write audit rows only (atm_position_reconciliation_items)
4. Set stop_verified_at on paper_trades if in apply mode

## Safety
- Default: audit-only, no broker writes
- Never cancel/replace/submit stop orders
