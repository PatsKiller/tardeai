# Phase 186H: Alpaca Extended-Hours Capability Audit

Status:      HISTORICAL
as_of:       2026-06-02T01:02:56-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-02

## Alpaca Adapter Extended-Hours Support

### Already Implemented (alpaca_paper_adapter.py:410-444)

The adapter **already supports extended hours**:

```python
_extended_hours = (_wd < 5 and ((4 <= _h < 9) or (_h == 9 and _m < 30) or (16 <= _h < 20)))
```

- **Premarket**: 4:00 AM - 9:30 AM ET (weekdays)
- **After-hours**: 4:00 PM - 8:00 PM ET (weekdays)
- **Regular**: 9:30 AM - 4:00 PM ET (weekdays)

### Extended-Hours Order Rules (Already Enforced)

| Rule | Status |
|------|--------|
| Market orders in extended hours | BLOCKED — forced to limit |
| Bracket orders in extended hours | BLOCKED — simple limit only |
| `extended_hours: true` flag | SET on order payload |
| `time_in_force: 'day'` | SET |
| Limit price required | YES — uses entry_price |

### Outside All Windows

Orders attempted outside all trading windows (weekends, 8PM-4AM) are BLOCKED with `'outside_trading_hours'` status.

## Auto-Approver Timing Issue

### Current Configuration

| Setting | Value | Source |
|---------|-------|--------|
| `start_et` | 07:00 | atm_config.yaml |
| `stop_new_entries_et` | 15:30 | atm_config.yaml |
| Cron schedule | `*/15 7-15 * * 1-5` | crontab |
| Default fallback in code | 09:35 | atm_auto_approver.py:138 |

### The Problem

The auto-approver config says `start_et: "07:00"`, but:
1. The code fallback (line 138) defaults to `09:35` if config is missing
2. The Alpaca adapter accepts orders from 4:00 AM ET
3. Proposals expire after 4 hours — a midnight proposal expires at ~4:00 AM ET
4. Even a 7:00 PM proposal expires by 11:00 PM ET — before next morning's window

### Gap Analysis

| Scenario | Created | Expires | ATM First Eval | Status |
|----------|---------|---------|----------------|--------|
| Midnight scan | 00:13 ET | 04:13 ET | 07:00 ET | EXPIRED before eval |
| Evening scan | 20:00 ET | 00:00 ET | 07:00 ET next day | EXPIRED |
| 7 AM scan | 07:00 ET | 11:00 ET | 07:00 ET | OK — 4h window |
| Market hours | 10:00 ET | 14:00 ET | 10:00 ET | OK — immediate |

**ELMT #160**: Created 00:13 ET, expires 08:13 ET, first ATM eval at 07:00 ET → has 1h13m. This will work IF the 07:00 cron fires reliably. But the 4-hour expiry window is too short for overnight proposals.

## Recommended Configuration

```yaml
# Add to atm_config.yaml
extended_hours:
  enabled: true                    # Alpaca paper supports extended hours
  premarket_start_et: "04:00"      # Alpaca premarket
  afterhours_end_et: "20:00"      # Alpaca after-hours
  allow_extended_entries: true     # Submit limit orders in extended hours
  allow_extended_exits: true       # Close positions in extended hours
  max_spread_pct: 1.0             # Stricter spread gate for thin liquidity
  min_volume_ratio: 0.1           # Allow lower volume in extended hours
  limit_orders_only: true         # Already enforced by adapter
  reduced_size_multiplier: 0.5    # Half position size in extended hours
```

### What Needs to Change

1. **Auto-approver `start_et`**: Change from 07:00 to match Alpaca premarket if extended entries enabled
2. **Cron schedule**: Expand from `*/15 7-15` to `*/15 4-19` if extended hours enabled
3. **Proposal expiry**: Extend from 4h to next-trading-window for overnight proposals
4. **Spread/volume gates**: Add extended-hours-specific risk checks
5. **Stop behavior**: Strategy trailing policy has `after_hours_trail: False` — review per strategy
