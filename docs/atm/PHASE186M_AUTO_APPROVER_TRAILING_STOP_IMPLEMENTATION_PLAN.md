# Phase 186M: Auto-Approver & Trailing Stop Implementation Plan

Status:      HISTORICAL
as_of:       2026-06-02T01:02:56-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-02

## Implementation Steps (ordered by priority)

### Step 1: Fix Proposal Expiry (Immediate — prevents lost proposals)

**File**: `scripts/auto_proposal_generator.py`

Change 4-hour flat expiry to next-trading-window-aware expiry:
- During market hours: keep 4-hour expiry
- Outside market hours: expire at next day's market close (or next ATM window end)
- Prevents overnight proposals from dying before ATM can evaluate them

### Step 2: Extend Auto-Approver Cron Window

**File**: crontab

Change: `*/15 7-15 * * 1-5` → `*/15 4-19 * * 1-5`

This matches Alpaca's full extended-hours window (4 AM - 8 PM ET). The auto-approver's `_in_operating_hours()` function still gates actual execution using configurable `start_et` / `stop_new_entries_et`.

### Step 3: Add Extended-Hours Config to atm_config.yaml

```yaml
extended_hours:
  enabled: true
  premarket_start_et: "04:00"
  afterhours_end_et: "20:00"
  allow_extended_entries: true
  allow_extended_exits: true
  max_spread_pct: 1.0
  reduced_size_multiplier: 0.5
  limit_orders_only: true   # Already enforced by adapter
```

### Step 4: Update _in_operating_hours()

**File**: `scripts/atm_auto_approver.py`

If `extended_hours.enabled`, use `premarket_start_et` as start time and `afterhours_end_et` as stop time for exits. Keep `stop_new_entries_et` for new entry cutoff.

### Step 5: Add Extended-Hours Risk Gates

**File**: `scripts/proposal_paper_submitter.py` (or new `extended_hours_gate.py`)

Before extended-hours submission:
- Check spread (max 1.0%)
- Check quote freshness (max 30 seconds)
- Force limit order (already done)
- Reduce position size (0.5x multiplier)
- Block momentum/gap_and_go strategies in extended hours

### Step 6: Add PENDING_TRADING_WINDOW Lifecycle

**File**: `scripts/auto_proposal_generator.py`

New status for proposals created outside Alpaca trading hours. Auto-approver picks these up when the next trading window opens.

### Step 7: Stop/Trailing Audit Dashboard

**File**: `scripts/api_v2.py` + frontend

Add stop conversion metrics to existing Paper Trading Status page or Queue Control Tower.

### Step 8: Trailing Stop Shadow Mode (Paper Only)

**Files**: `scripts/paper_trade_monitor.py`, `scripts/strategy_trailing_policy.py`

Run parallel trailing calculations without executing. Log what trailing WOULD have done. Compare to actual outcomes. This requires no behavior change — purely observational.

## What NOT to Implement Now

- Real trailing stop threshold changes (Step 8 is shadow only)
- Live trading anything
- Extended-hours for non-paper accounts
- After-hours trailing stop execution (policy says `after_hours_trail: False`)
- ATR-based or MFE-based trailing (design only, implement after shadow data)

## Dependencies

| Step | Depends On | Risk |
|------|-----------|------|
| 1 | None | Low — affects expiry only |
| 2 | None | Low — cron window only |
| 3 | None | Low — config only |
| 4 | Step 3 | Low — function change |
| 5 | Steps 3-4 | Medium — new gate logic |
| 6 | Step 1 | Low — new status |
| 7 | Steps 1-6 | Low — read-only |
| 8 | None | Low — shadow/observe only |

## Operator Approval Required For

- Steps 1-4 can be applied now (timing fixes, no behavior change in trade execution)
- Steps 5-6 need review (new risk gates affect which proposals pass)
- Steps 7-8 are read-only (no execution impact)
