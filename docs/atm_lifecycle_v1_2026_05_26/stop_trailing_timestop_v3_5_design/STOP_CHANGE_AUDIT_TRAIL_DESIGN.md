# Stop-Change Audit Trail Design

## Current State
- Stop changes are NOT recorded structurally anywhere
- APPS $6.54→$6.17 repair has zero audit trail in lifecycle_events
- unified_stop_supervisor updates stop_loss in paper_trades without logging the change
- No way to see what the previous stop was

## Proposed Model
Use lifecycle_events with stage='stop_change':

| Field | Purpose |
|-------|---------|
| paper_trade_id | Which trade |
| symbol | For display |
| old_stop (in payload) | Previous stop_loss value |
| new_stop (in payload) | New stop_loss value |
| change_type (event_type) | initial_stop / trailing_update / repair / manual_operator / broker_reconcile / stop_hit / target_hit |
| source_script | Which script made the change |
| reason (in payload) | Why the stop changed (e.g. "trailing tier lock 0.5R" or "APPS orphan repair") |
| broker_confirmation (in payload) | Stop order ID if available |

## Patch Points
1. `unified_stop_supervisor.py` — before updating paper_trades.stop_loss, write lifecycle_event
2. Manual/repair changes — must also write lifecycle_event
3. Backfill APPS repair as a lifecycle_event with change_type='repair'

## UI Visibility
StopChangeAuditPanel shows:
- Symbol, Paper Trade #, Old Stop, New Stop, Change Type, Source, Reason, Broker Proof, Changed At
- APPS example: APPS #34, $6.54→$6.17, repair, manual, "orphan position reconciliation"
