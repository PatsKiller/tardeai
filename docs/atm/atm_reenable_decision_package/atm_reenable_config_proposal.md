# ATM Re-enable Configuration Proposal

**Status:** PROPOSAL ONLY — do not apply until John approves

## Proposed Initial Config (Mode 1 Dry-run)

```yaml
mode: dry_run
active_execution: false
account_scope: paper_only
max_daily_entries: 1
max_concurrent_positions: 2
max_per_trade_risk_pct: 0.10
max_daily_loss_pct: 0.25
require_broker_native_stop: true
require_stop_order_id: true
require_fresh_quote: true
require_route_audit: true
require_valid_strategy_id: true
require_operator_freeze_available: true
allowed_strategies: []  # empty = observe only
excluded_strategies: all_until_approved
burn_in_days: 3_to_5
after_hours_execution: false
after_hours_trailing: false
stop_reconciliation_required_before_each_cycle: true
```

## What File Would Change
`config/atm_config.yaml` — only after John approves.

## Rollback Strategy
1. Set `mode: disabled` in config
2. Or direct DB: `UPDATE atm_state SET mode='disabled' WHERE id=1;`
3. Rollback script: `scripts/rollback_stop_v22_monitor_merge.sh` for stop supervisor

## No Actual Config Change in This Phase
This document is a proposal. The config file remains unchanged.
