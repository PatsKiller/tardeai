# BLMN Duplicate Reconciliation Repair

**Date:** 2026-05-27

## Before State

| ID | Symbol | Entry | Exit Time | Exit Reason | Journal |
|----|--------|-------|-----------|-------------|---------|
| 37 | BLMN | $8.26 | NULL | NULL | closed |
| 38 | BLMN | $8.28 | NULL | NULL | **open** |

## Repairs Applied

### #37 — Closed as duplicate
```sql
UPDATE paper_trades SET exit_reason='duplicate_submit_race', exit_time=NOW()
WHERE id=37 AND symbol='BLMN' AND exit_time IS NULL;
```

### #38 — entry_time backfilled
```sql
UPDATE paper_trades SET entry_time='2026-05-27T11:15:03.545959-04:00'
WHERE id=38 AND symbol='BLMN' AND entry_time IS NULL;
```
Source: automated-journal `filled_at` field.

## After State

| ID | Symbol | Entry | Exit Time | Exit Reason | Journal |
|----|--------|-------|-----------|-------------|---------|
| 37 | BLMN | $8.26 | 2026-05-27 19:10 | duplicate_submit_race | closed |
| 38 | BLMN | $8.28 | NULL | NULL | **open** |

Open trade count: **4** (NWG #28, AGNC #31, CMCSA #33, BLMN #38)

## Lifecycle Audit Events Added

1. #37: `duplicate_reconciliation` — BLMN #37 closed as duplicate submit race
2. #38: `metadata_backfill` — entry_time populated from journal filled_at

## Safety

- Orders placed: **NONE**
- Broker writes: **NONE**
- Stops modified: **NONE**
- Changes limited to #37 exit + #38 entry_time: **YES**
- ALPACA_MODE=paper, LLM_DISABLE=true

## Rollback

```sql
UPDATE paper_trades SET exit_reason=NULL, exit_time=NULL WHERE id=37 AND symbol='BLMN' AND exit_reason='duplicate_submit_race';
UPDATE paper_trades SET entry_time=NULL WHERE id=38 AND symbol='BLMN';
```
