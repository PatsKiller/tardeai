# v3.5 Stop / Trailing / Time-Stop Implementation Plan

## Current State
- 3 open trades (NWG, AGNC, CMCSA) — all have stop_order_id
- unified_stop_supervisor runs every 3 min, updates DB stop_loss and places broker stops
- strategy_trailing_policy.py defines trailing tiers per strategy family
- Time-stop defined per family but not enforced (review-only via P0.5B)
- APPS stop was replaced $6.54→$6.17 as repair — NOT captured in any audit trail
- Zero stop-change events exist in lifecycle_events

## Proposed Implementation

### 1. Stop-Change Audit Trail
Use lifecycle_events table (stage='stop_change') rather than a new table.
Required fields in payload: old_stop, new_stop, change_type, source_script, reason, broker_confirmation.

### 2. Read-Only Stop/Trailing/Time-Stop API
`GET /api/v2/atm/stop-trailing-control` — per-trade stop status, trailing tier, time-stop, audit history.

### 3. StopTrailingControlPanel
Show DB stop, broker proof, current R, trailing tier, next tier, time-stop status, recent stop changes.

### 4. StopChangeAuditPanel
Show all stop changes with old/new/reason/source. APPS repair must be backfilled as audit event.

### What v3.5 Will NOT Do
- No broker writes
- No auto-close
- No auto-adjust stops
- No stop replacement
- No order placement
