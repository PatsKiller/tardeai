# REGIME-CRON-1 Transaction Recovery Report

## Changes

### market_regime_classifier.py — `save_snapshot()`

**Before:** Single INSERT with no error handling. If any prior query on the connection poisoned the transaction (InFailedSqlTransaction), the INSERT would fail silently and the snapshot would never be written.

**After:**
1. Transaction health check: `SELECT 1` before critical write
2. On failure: `conn.rollback()` to clear poisoned state
3. Wrapped INSERT in try/except with explicit rollback on error
4. Returns `True` on success, `False` on failure
5. Never marks stale data current on failure

### market_regime_classifier.py — `_record_run_log()`

New function that writes to `risk_regime_run_log` after each classifier run:
- `run_id`, `mode`, `started_at`, `finished_at`
- `status` (success/failed)
- `snapshot_id` (only if write succeeded)
- `indicators_read`
- `errors` (JSON array)
- Own transaction health check + rollback recovery

### Atomic Guarantees

- Snapshot write and commit are in a single try block
- If INSERT fails, rollback ensures clean state
- Run log is written AFTER snapshot write (so it records actual outcome)
- Run log has its own transaction recovery (doesn't depend on snapshot transaction)
- Failed classifier cannot produce rotation signals (rotation engine reads latest snapshot, which won't be updated on failure)

## Verification

```
Classifier apply result:
  write_ok: true
  run_id: RUN_20260520155002_e9f1ccde
  status: success
  snapshots_created: 1
```
