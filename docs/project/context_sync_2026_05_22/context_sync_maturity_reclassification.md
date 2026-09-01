# Maturity Reclassification — 2026-05-22

Status:      ACTIVE
as_of:       2026-05-22T16:02:12-04:00
Measured at: efcc51365 / not measured

## Updated Maturity

- **Prior practical maturity estimate:** 7.6 / 10
- **Revised provisional maturity:** 6.4 / 10
- **Reason:** Paper execution governance issue

## Rationale

ATM v1 was deployed in DISABLED mode and was supposed to be flipped to active only
after all safety gates were verified. On 2026-05-22, ATM entered active mode and
submitted paper orders. While the orders were paper-only (no live money at risk),
the execution path revealed:

1. audit_log writes failed silently (schema mismatch)
2. Quote fetch returned 404 for all symbols (wrong API URL)
3. Partial-fill race condition left 2 positions without stop-loss protection
4. Stale proposals were retried indefinitely without expiry

These are not live-money critical, but paper execution automation crossed expected
boundaries. The system executed trades with degraded observability (no audit trail,
no live quotes, no stop protection on 2 of 4 fills).

## Blockers Before Maturity Can Be Re-Assessed

| Blocker | Status | Required For |
|---|---|---|
| ATM active execution containment (ATM-SAFE-1) | **REQUIRED** | Paper trading confidence |
| audit_log schema fix | OPEN | Observability |
| Quote fetch fail-closed enforcement | MITIGATED | Price integrity |
| Broker reconciliation | FIXED | Data consistency |
| A-5 strategy proof | NOT STARTED | Live trading consideration |
| Backup/offsite/restore verification | NOT STARTED | Production readiness |

## Next Maturity Board

Must run after ATM-SAFE-1 completes. Do not re-score maturity based on
the current state — the fixes applied today improve the score but the
remaining open items must be verified first.
