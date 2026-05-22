# Stop Management v2 — Design Document

**Date:** 2026-05-22
**Status:** DESIGN (not implemented)
**Prerequisite:** ATM-SAFE-1 complete, maturity 6.2

---

## Current State (v1)

### What Works
- **Broker-level stop orders**: All 5 open positions have GTC stop orders on Alpaca
- **4-tier R-multiple trailing**: paper_trade_monitor adjusts stops upward at R=1.0/1.5/2.0/3.0
- **Auto-close on stop hit**: open_trade_monitor detects price <= stop and closes
- **Time stops**: Intraday closes at 3:45 PM ET, swing after max_hold_days
- **Critical news auto-close**: Detects halt/bankruptcy/fraud keywords, closes immediately
- **Near-stop alerts**: Graduated Telegram alerts at 50% and 75% risk consumed

### What's Missing (Gaps)
1. **No trailing stop on Alpaca**: Software computes new stops but the broker-side
   stop order is NOT always updated. `paper_trade_monitor.replace_stop()` exists
   but relies on the 5-min cron successfully running. If the cron dies, stops go stale.

2. **Duplicate monitoring**: Both `open_trade_monitor.py` (*/2) and
   `paper_trade_monitor.py` (*/5) manage stops independently. They can race —
   one cancels a stop order while the other is checking it.

3. **No stop validation on existing positions**: After a cron restart or server
   reboot, there's no check that Alpaca stop orders still exist and match DB.

4. **R-multiple trailing is hardcoded**: The 4-tier schedule (1.0R→breakeven,
   1.5R→0.5R, 2.0R→1.0R, 3.0R→2.0R) can't be configured per strategy.

5. **`planned_stop` not always set**: 3 of 5 open trades have `planned_stop=NULL`.
   R-multiple calculation falls back to `stop_loss` but this changes with trailing,
   making R-calculations drift.

6. **No stop-loss order reconciliation**: If Alpaca rejects a stop modification
   (e.g., GTC expired, price through stop), no alert fires.

---

## v2 Design

### Principle: Broker Is Source of Truth for Stops

The #1 safety principle: **a stop order must exist on the broker at all times
for every open position.** Software stops are monitoring aids, not safety nets.

### Architecture

```
ENTRY:
  submit_entry()
    → Place position + bracket stop + take-profit (existing)
    → Verify stop order exists on Alpaca within 30s of fill
    → If no stop order confirmed: ALERT + auto-place standalone stop
    → Write stop_order_id to paper_trades

ONGOING (single monitor — merge v1 duplicates):
  unified_trade_monitor.py (*/2 9-16 weekdays)
    → Step 1: RECONCILE — verify every open DB trade has a matching
              Alpaca stop order (symbol, qty, stop_price)
    → Step 2: TRAIL — compute new stop per strategy's trailing config
              If new_stop > current_stop: replace on Alpaca
    → Step 3: ALERT — near-stop, near-target, time-stop, stale
    → Step 4: CLOSE — if broker reports position closed (phantom check)

CLOSE:
  On stop/target/time/news close:
    → Cancel any remaining stop/take-profit orders
    → Update DB with exit price, exit reason, PnL
    → Trigger post-trade analysis
```

### Proposed Changes

#### 1. Merge Monitors Into `unified_trade_monitor.py`

**Currently:**
- `open_trade_monitor.py` (*/2): alerts, auto-closes, trailing
- `paper_trade_monitor.py` (*/5): trailing, target closes, phantom detection

**Proposed:** Single `unified_trade_monitor.py` running */2:
- Eliminates race conditions between two monitors
- Single source of truth for stop adjustments
- One log file, one audit trail

**Effort:** M (merge logic from both scripts, keep all safety checks)
**Risk:** LOW (test in dry-run with existing positions first)

#### 2. Stop Order Reconciliation

New step at the start of every monitor cycle:

```python
def reconcile_stops(conn, adapter):
    """Verify every open trade has a matching broker stop order."""
    open_trades = fetch_open_trades(conn)
    broker_orders = adapter.get_open_orders()  # GET /v2/orders?status=open
    
    for trade in open_trades:
        matching_stop = find_stop_for(trade.symbol, broker_orders)
        if not matching_stop:
            # CRITICAL: No stop order on broker!
            alert_critical(f"{trade.symbol}: NO STOP ORDER ON BROKER")
            place_emergency_stop(adapter, trade)
        elif abs(float(matching_stop.stop_price) - trade.stop_loss) > 0.01:
            # Stop price mismatch between DB and broker
            alert_warning(f"{trade.symbol}: stop mismatch DB={trade.stop_loss} broker={matching_stop.stop_price}")
            # DB follows broker — broker is source of truth
            update_db_stop(conn, trade.id, float(matching_stop.stop_price))
    
    return reconciliation_report
```

**Effort:** S
**Risk:** NONE (read-only check + emergency placement only)

#### 3. Strategy-Configurable Trailing Schedule

Move the hardcoded 4-tier trailing from code to strategy YAML:

```yaml
# config/strategies/momentum_scalp.yaml
stop_management:
  trailing_enabled: true
  trailing_tiers:
    - r_threshold: 1.0
      lock_r: 0.0       # breakeven
    - r_threshold: 1.5
      lock_r: 0.5
    - r_threshold: 2.0
      lock_r: 1.0
    - r_threshold: 3.0
      lock_r: 2.0
  time_stop:
    type: intraday
    close_at: "15:45"
  max_hold_days: null    # intraday — no multi-day hold

# config/strategies/dividend_growth_compounder.yaml
stop_management:
  trailing_enabled: true
  trailing_tiers:
    - r_threshold: 1.0
      lock_r: 0.0
    - r_threshold: 2.0
      lock_r: 0.5
    - r_threshold: 3.0
      lock_r: 1.5
  time_stop:
    type: calendar
    max_hold_days: 90
```

**Effort:** M (add YAML fields, read in monitor, fallback to current hardcoded)
**Risk:** LOW (strategies without config use existing defaults)

#### 4. `planned_stop` Backfill + Enforcement

Ensure `planned_stop` is always set at trade creation (immutable reference):

```python
# In submit_entry(), after fill:
if not planned_stop:
    planned_stop = stop_price  # snapshot at entry time
```

Backfill existing trades:
```sql
UPDATE paper_trades SET planned_stop = stop_loss
WHERE planned_stop IS NULL AND status = 'open';
```

**Effort:** S
**Risk:** NONE

#### 5. Stop Order ID Tracking

Add `stop_order_id` column to `paper_trades`:

```sql
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS stop_order_id TEXT;
```

When a stop order is placed or replaced, store the Alpaca order ID.
Reconciliation uses this to match broker orders to trades.

**Effort:** S
**Risk:** NONE

---

## Prioritized Implementation Plan

| Phase | What | Effort | Risk | Dependency |
|-------|------|--------|------|------------|
| **v2.0** | planned_stop backfill + enforcement | S | NONE | None |
| **v2.0** | stop_order_id column + tracking | S | NONE | None |
| **v2.1** | Stop order reconciliation | S | NONE | v2.0 |
| **v2.2** | Merge monitors → unified_trade_monitor | M | LOW | v2.1 |
| **v2.3** | Strategy-configurable trailing schedule | M | LOW | v2.2 |

### v2.0 — Immediate (safe, no behavior change)
- Backfill `planned_stop` on open trades
- Add `stop_order_id` column
- Track stop order IDs on new trades
- **Can ship today**

### v2.1 — Stop Reconciliation (highest safety value)
- Add reconciliation step to start of monitor cycle
- Emergency stop placement if broker has no stop
- Alert on stop price mismatches
- **Ship within 1 session**

### v2.2 — Monitor Merge (eliminate race conditions)
- Merge open_trade_monitor + paper_trade_monitor
- Single cron (*/2), single log, single audit trail
- All safety checks from both monitors preserved
- **Ship within 1-2 sessions**

### v2.3 — Configurable Trailing (per-strategy flexibility)
- YAML-based trailing tiers per strategy
- Default fallback to current 4-tier schedule
- Income/dividend strategies get wider trailing (they're not scalps)
- **Ship within 1 session after v2.2**

---

## Decisions Required from John

1. **Trailing schedule for income/dividend strategies**: The current 4-tier
   (breakeven at 1R, lock 0.5R at 1.5R, lock 1R at 2R, lock 2R at 3R) is
   designed for scalps. Dividend_growth_compounder, reit_income, etc. should
   probably have wider trailing. What tiers?

2. **Monitor merge cadence**: Currently */2 (every 2 min) and */5. Merged
   monitor at */2 or */3? More frequent = faster stop adjustment but more
   API calls.

3. **Stop reconciliation action**: When broker has no stop order, should we:
   a. Auto-place emergency stop (recommended)
   b. Alert only, wait for operator
   c. Auto-close the position (nuclear option)

4. **Time stop for position strategies**: Current max_hold_days for
   dividend_growth_compounder is undefined. What's the right hold period?
   90 days? 180 days? No time stop (hold until target/stop)?

5. **Stop adjustment during after-hours**: Should the trailing logic run
   after 4 PM? Pre-market? Alpaca supports extended hours for some operations.

---

## Safety Notes

- **v2 does NOT change any existing safety gate** — it adds layers
- **Broker stops remain the primary safety net** — software monitors are secondary
- **No changes to entry logic, scoring, or proposal pipeline**
- **All changes are paper-only until maturity ≥ 7.0**

---

## Metrics to Track Post-Implementation

| Metric | Baseline (v1) | Target (v2) |
|--------|---------------|-------------|
| Trades with broker stop verified | Unknown | 100% |
| Stop reconciliation mismatches | Not tracked | <5% |
| Monitor race conditions | Possible | Eliminated |
| Trailing stop adjustments/day | ~2 | Same, but reliable |
| Time from R-threshold to stop update | 5-15 min | <3 min |
| Planned_stop coverage | 40% (2/5) | 100% |
