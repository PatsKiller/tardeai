# STOP-V2.1 Reconciliation Summary

**Date:** 2026-05-22

## Results

- Open positions checked: **5**
- Broker stops found: **5**
- Reconciled: **5/5**
- Critical findings: **0**
- Warning findings: **0**
- Missing broker stops: **0**
- Price mismatches: **0**
- Qty mismatches: **0**
- Stale stop_order_id: **0**
- Orphaned broker stops: **0**
- **All positions protected: YES**

## Per-Trade Detail

| Trade | Symbol | DB Stop | Broker Stop | Qty Match | TIF | Status |
|-------|--------|---------|-------------|-----------|-----|--------|
| #27 | ASPN | $5.15 | $5.15 | 553/553 | GTC | RECONCILED |
| #28 | NWG | $15.05 | $15.05 | 189/189 | GTC | RECONCILED |
| #29 | NVDA | $210.58 | $210.58 | 13/13 | GTC | RECONCILED |
| #31 | AGNC | $9.71 | $9.71 | 293/293 | GTC | RECONCILED |
| #33 | CMCSA | $23.61 | $23.61 | 120/120 | GTC | RECONCILED |

## Conclusion

All 5 open positions have matching broker-level GTC stop orders. Stop prices and
quantities match between DB and Alpaca broker. No critical or warning findings.

**ATM re-enable impact:** Reconciliation confirms broker stop protection is intact.
This is NOT a blocker for ATM re-enable. The remaining blockers are:
- Strategy proof (need 3+ closed trades per strategy)
- John's 7 ATM decisions
- min_classifier_health restoration
