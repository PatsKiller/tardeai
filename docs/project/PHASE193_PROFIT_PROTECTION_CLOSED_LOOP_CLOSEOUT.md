# PHASE 193 — Profit-Protection Advisory Close-Loop — CLOSEOUT

Status:      HISTORICAL
as_of:       2026-06-02T12:45:21-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~12:15–12:30 ET · Alpaca **paper** only · learning telemetry, no execution

---

## What shipped
- **193A** design + schema `protection_advisory_outcomes` (migration
  `2026_06_02_phase193_advisory_outcomes.sql`).
- **193B** reconciler `scripts/reconcile_protection_advisory_outcomes.py` — joins advisory +
  adjustment + trade outcome per trade; upsert; idempotent. Ran: 31 reconciled.
- **193C** read-only learning endpoint `GET /api/v2/atm/protection-advisory-outcomes`
  (frontend-neutral; serves v2 + v3). Live.

## Headline
**41.7% of legacy closed trades (10/24) gave back profit with no advisory** — the quantified
baseline justifying Phases 191–192. **ANY** is the first full round-trip
(advisory → approve → applied → tracked: stop 3.07→3.56, locked $201, **giveback avoided $300**).

## Required closeout fields
- **Phase 193 complete:** ✅ YES
- **Reconciler implemented + run:** ✅ YES (31 trades)
- **Outcomes table created:** ✅ `protection_advisory_outcomes`
- **Learning endpoint live:** ✅ `/api/v2/atm/protection-advisory-outcomes`
- **Operator accepted / ignored:** 1 / 0 (ANY accepted)
- **Baseline give-back rate:** 41.7% (10/24)
- **Advisory accuracy (closed-with-advisory):** 0 yet (forward-looking; ANY in_flight)
- **MFE units integrity:** **FLAGGED** (22 rows `mfe_units_validated=false`) — honest, not fabricated
- **No execution / no stop changes / no orders:** ✅ YES (read-only on broker)
- **Live trading:** ZERO · **Live endpoint:** blocked · **GO/WAIT mutation:** ZERO ·
  **Strategy mutation:** ZERO · **Level 7:** PROHIBITED
- **Next recommended gate:** **Phase 194 —** (a) schedule the reconciler (post-close + nightly cron);
  (b) **fix MFE units** in the trade pipeline so profit-left-on-table is dollar-accurate;
  (c) surface outcomes in the v3 Journal/Learning hub (handoff-style, like 192H); (d) threshold
  tuning from accumulated accuracy once advised trades close.

## How the loop now runs end to end
proposal/advisory → operator approval (192) → applied paper adjustment → **reconciler captures the
outcome (193)** → journal/backtest/threshold tuning. ANY will produce the first scored accuracy on
close.

## Guardrail attestation
No live account/endpoint/broker mode, no live trades, no holdings mutated, no stops moved/cancelled,
no strategy configs changed, no GO/WAIT logic changed, Level 7 not enabled, Claude Code auto-update
not run. DB writes limited to the new outcomes table.
