# Source Export: config/atm_config.yaml

| Field | Value |
|-------|-------|
| **Original Path** | `config/atm_config.yaml` |
| **Git Branch** | `main` |
| **Git Commit** | `c1286d314deb377df49713e1646f139db7f43643` |
| **Export Timestamp** | `2026-05-26T15:48:59Z` |
| **SHA256** | `09ab50de29f8109626ec423ad4693e079f19bc2e310c99a4b7ec8579ac42de81` |
| **File Size** | 1695 bytes |

## Full Source

```yaml
# Automated Trade Mode v1 configuration
# Per-account caps. Global state machine. No broker hardcoded.
#
# ATM does NOT control where trades execute. That is governed by:
#   - ALPACA_MODE / LLM_DISABLE_LIVE_EXECUTION (existing env flags)
#   - accounts table routing_adapter / mode fields
#   - the proposal's target_account assignment
version: 1

defaults:
  position_limits:
    max_concurrent: 6
    max_new_per_day: 3
    max_pct_per_trade: 0.10
    max_pct_per_strategy: 25
    max_pct_per_sector: 35
  strategy_filter:
    # TEMPORARY: lowered from 0.50 to 0.0 during DRY_RUN cold-start
    # (0 closed trades per strategy → health=0.0 → gate blocks everything)
    # Restore to 0.50 once ≥3 paper trades close per active strategy.
    min_classifier_health: 0.0
    whitelist: []
    blacklist: []
  kill_switches:
    daily_loss_pct_hard_pause: 0.25
  operating_hours:
    start_et: "09:35"
    stop_new_entries_et: "15:30"

# Same-day strategies that the 15-min ATM cron is too slow for.
same_day_skip_strategies:
  - momentum_scalp
  - gap_and_go

# Per-account overrides. account_label must exist in accounts table.
accounts:
  alpaca_paper:
    enabled: true
    position_limits:
      max_concurrent: 6
      max_new_per_day: 3
      max_pct_per_trade: 0.10

global:
  daily_loss_pct_hard_pause_aggregate: 10.0
  manual_kill_switch_only: true
  config_backup_dir: "config/.atm_config_backups"

# B-1 observation window protection.
b1_tracking:
  enabled: true
  observation_end: "2026-05-25"
  exclude_bucket2_during_observation: true
  bucket2_strategies:
    - swing_breakout
    - swing_trade
    - earnings_post_momentum
    - recovery_watch
    - fib_retracement_bounce
```
