# Stop V2.0 — Post-Backfill Verification

**Date:** 2026-05-22

## Before vs After

| Metric | Before | After |
|--------|--------|-------|
| planned_stop missing | 3 (ASPN, AGNC, CMCSA) | **0** |
| stop_order_id missing | 5 (all) | **0** |
| Broker GTC stops confirmed | 5/5 | 5/5 |
| Price mismatches | 0 | 0 |
| Review required | 0 | 0 |
| Reconciliation status: TRACKED | 0/5 | **5/5** |

## Per-Trade Detail

| ID | Symbol | planned_stop | stop_order_id | Broker Match | Status |
|----|--------|-------------|---------------|-------------|--------|
| #27 | ASPN | 5.15 (backfilled) | set (backfilled) | YES | TRACKED |
| #28 | NWG | 15.05 (existing) | set (backfilled) | YES | TRACKED |
| #29 | NVDA | 210.58 (existing) | set (backfilled) | YES | TRACKED |
| #31 | AGNC | 9.71 (backfilled) | set (backfilled) | YES | TRACKED |
| #33 | CMCSA | 23.61 (backfilled) | set (backfilled) | YES | TRACKED |

## Confirmations

- No stops moved: YES
- No orders created: YES
- No orders canceled: YES
- No trades created: YES
- All audit events written to audit_log table: YES (8 events)
