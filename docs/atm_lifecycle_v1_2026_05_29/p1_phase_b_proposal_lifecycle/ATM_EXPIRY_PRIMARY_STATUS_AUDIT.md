# ATM Expiry Primary Status Audit — 2026-05-29

## Issue
`scripts/atm_auto_approver.py` lines 302-306: When ATM expires a proposal (age >4h, 5+ failures, or enrichment failed 3x), it sets `atm_expired_at` and `atm_expiry_reason` but does NOT update primary `status` from `PENDING`.

This creates a ghost state: the proposal is PENDING in `status` but invisible to ATM (filtered by `atm_expired_at IS NULL`). Other sweepers (cleanup_stale_proposals, _expire_stale_proposals) eventually catch it, but there's a window where status and ATM state disagree.

## Code Path
```python
# atm_auto_approver.py:302-306 (BEFORE fix)
cur.execute("""
    UPDATE paper_trade_proposals
    SET atm_expired_at = NOW(), atm_expiry_reason = %s
    WHERE id = %s
""", (expiry_reason, pid))
```

## Current Affected Rows
**0** — all 4 ATM-expired proposals already have `status=EXPIRED` (caught by other sweepers). No backfill needed.

```
 status  | count
---------+-------
 EXPIRED |     4
```

## Fix Applied
```python
# atm_auto_approver.py:302-306 (AFTER fix)
cur.execute("""
    UPDATE paper_trade_proposals
    SET atm_expired_at = NOW(), atm_expiry_reason = %s,
        status = 'EXPIRED', lifecycle_status = 'EXPIRED',
        lifecycle_message = %s
    WHERE id = %s AND status NOT IN ('APPROVED_FOR_PAPER_TEST', 'BROKER_SUBMITTED')
""", (expiry_reason, f"ATM expired: {expiry_reason}", pid))
```

## Safety Guards
- `WHERE status NOT IN ('APPROVED_FOR_PAPER_TEST', 'BROKER_SUBMITTED')` prevents expiring proposals that have already been approved or submitted to broker
- No trade state changes
- No broker calls
- No order placement
- Uses uppercase `EXPIRED` consistent with P0 fix

## No Backfill Required
All 4 existing ATM-expired rows already have correct status. The fix prevents future drift only.
