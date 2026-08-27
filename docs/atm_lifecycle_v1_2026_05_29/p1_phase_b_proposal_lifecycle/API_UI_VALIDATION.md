# API/UI Validation — 2026-05-29

## Python Compile
- `py_compile scripts/api_v2.py` — PASS
- `py_compile scripts/atm_auto_approver.py` — PASS

## Lifecycle Inspector Validation

### Expired proposal (BLBD #10)
- status_raw=expired, normalized=EXPIRED
- signal_decision=GO (was the bug — hygiene panel used this instead of status, now fixed)
- actionable=false, next_action="None — terminal status"
- PASS

### Approved/traded proposal (SNOW #138)
- status=APPROVED_FOR_PAPER_TEST
- linked_trade=39 (pending), extra_trades=1 (SNOW #40)
- actionable=false, next_action="Monitor linked trade"
- PASS

### Rejected proposal (CRSR #151)
- status=REJECTED, enrichment=COMPLETE
- actionable=false, next_action="None — terminal status"
- PASS

## Hygiene Panel
- total=141, expired=65, linked=2, needs_review=0
- Consistent with P0 fix
- PASS

## ATM Expiry Code
- Compile check: PASS
- WHERE guard: `status NOT IN ('APPROVED_FOR_PAPER_TEST', 'BROKER_SUBMITTED')` prevents unsafe expiry
- Sets status='EXPIRED', lifecycle_status='EXPIRED', lifecycle_message
- No rows currently affected (0 proposals in inconsistent state)

## No Frontend Changes
No UI components added — API-only for lifecycle inspector. No build required.
