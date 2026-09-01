# ATM-SAFE-1 — Execution Containment Phase

Status:      ACTIVE
as_of:       2026-05-22T16:02:12-04:00
Measured at: efcc51365 / not measured

**Priority:** P0
**Prerequisite:** Context sync 2026-05-22 complete
**Must complete before:** Any further ATM enhancements, maturity re-scoring, or feature work

---

## Objective

Freeze ATM active execution, reconcile all paper positions, fix remaining
safety gates, and verify no unintended orders or trades exist.

## Hard Rules

- Do not enable live trading
- Do not submit new orders
- Do not approve proposals
- Do not change strategy activation
- Do not change YAML thresholds or Finviz criteria
- Do not modify .env

## Tasks

### 1. Freeze ATM Active Execution

Set ATM mode to `disabled` or `dry_run` (operator's choice). Document the
mode change with timestamp and reason.

Verify: no new ATM approval cycles fire after the freeze.

### 2. Reconcile Paper Positions

Verify all 5 open positions match between paper_trades table and Alpaca paper:
- NWG #28: 189 shares, stop $15.05
- NVDA #29: 13 shares, stop $210.58
- AGNC #31: 293 shares, stop $9.71
- CMCSA #33: 120 shares, stop $23.61
- ASPN #27: 553 shares, stop $5.15

Verify no unexpected positions exist in Alpaca that aren't in paper_trades.
Verify no pending/orphan paper_trades rows remain.

### 3. Fix Audit Logging Schema

The `audit_log` table is missing an `event` column. Every approval attempt
writes to this table and fails silently.

Options:
a. Add the `event` column to audit_log
b. Update the INSERT query to use the correct column name
c. Both

Verify: run a test INSERT to audit_log and confirm it succeeds.

### 4. Enforce Quote-Failure Fail-Closed

The current fix (switched to data.alpaca.markets) mitigates the 404 issue
but the validated_price fallback still exists. Evaluate:

- Should the adapter BLOCK order submission if no live quote is available?
- Or is the fallback acceptable with a warning?

Recommended: block if no price source returns within the last 60 seconds.
The adapter should never submit an order using a price that's >1 minute old.

### 5. Verify No New Orders/Trades After Freeze

After ATM is frozen, run:
```sql
SELECT * FROM paper_trades WHERE created_at > '<freeze_timestamp>' ORDER BY created_at;
SELECT * FROM atm_decision_log WHERE decided_at > '<freeze_timestamp>' ORDER BY decided_at;
```

Both should return 0 rows.

### 6. Run Tests

- Syntax check all modified Python files
- Verify frontend builds cleanly
- Verify API endpoints respond

### 7. Commit and Sync

Commit all changes with message:
```
fix(atm-safe-1): freeze active execution, fix audit schema, enforce quote fail-closed
```

Sync docs to Drive.

## Verification Checklist

- [ ] ATM mode frozen (disabled or dry_run)
- [ ] All 5 positions reconciled (DB matches Alpaca)
- [ ] audit_log INSERT succeeds
- [ ] Quote failure behavior documented (fail-closed or acceptable fallback)
- [ ] No new orders/trades after freeze
- [ ] Tests pass
- [ ] Committed and synced
- [ ] Telegram both IDs with completion summary

## After ATM-SAFE-1

- Re-run maturity board
- Decide on stop management v2 (pending John's 7 decisions)
- Consider ATM v2 enhancements only after maturity re-scores above 7.0
