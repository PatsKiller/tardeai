# Validation and Rollback Plan

## Pre-change
- Count paper_trades columns
- Count existing data in timing fields (expect all null)
- Capture current open trade count

## After schema migration
- Verify 4 new columns exist: `\d paper_trades`
- Verify no data was lost
- Verify open trade count unchanged

## After code patches
- Syntax check all patched scripts
- API endpoint returns correct shape
- Frontend builds clean
- Screenshots captured

## Rollback SQL
```sql
ALTER TABLE paper_trades DROP COLUMN IF EXISTS order_submitted_at;
ALTER TABLE paper_trades DROP COLUMN IF EXISTS order_filled_at;
ALTER TABLE paper_trades DROP COLUMN IF EXISTS stop_order_id;
ALTER TABLE paper_trades DROP COLUMN IF EXISTS stop_verified_at;
```

## Git rollback
```bash
git revert HEAD
```
