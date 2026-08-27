# Stop Management V2.1 — Reconciliation Engine

**Phase:** STOP-V2.1
**Date:** 2026-05-22
**Purpose:** Continuously verify broker-level GTC stops exist and match DB

## What Was Built

1. `reconcile_stop_v21_broker_stops.py` — reads open trades + broker orders,
   matches by stop_order_id (exact) or symbol/qty (fallback), reports findings
2. Detects: MISSING_BROKER_STOP, STOP_PRICE_MISMATCH, STOP_QTY_MISMATCH,
   STOP_ORDER_ID_STALE, BROKER_STOP_CANCELED, ORPHANED_BROKER_STOP, REVIEW_REQUIRED
3. Severity levels: CRITICAL (position at risk), WARN (needs attention), INFO (healthy)
4. Audit trail via audit_log table with fallback to file

## What Was NOT Done

- No stop orders created, canceled, moved, or replaced
- No trades created or approved
- No ATM mode changes
- Reconciliation tables exist but this phase writes to audit_log + file reports only

## Results

5/5 RECONCILED. 0 critical. 0 warnings. All positions protected by GTC stops.
