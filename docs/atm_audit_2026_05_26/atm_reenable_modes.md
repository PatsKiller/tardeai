# ATM Re-enable Modes

Status:      HISTORICAL
as_of:       2026-05-26T11:21:21-04:00
Measured at: efcc51365 / not measured

## Mode 0 — Frozen (CURRENT)
ATM active execution disabled. Proposal generation continues.
Stop supervisor running. No ATM approval cycles fire.

## Mode 1 — Dry-run Only (RECOMMENDED FIRST)
ATM evaluates proposals, logs decisions as dry_run_approved/rejected.
No orders submitted. Dashboard shows what ATM would do.
**Required burn-in phase before any active execution.**

## Mode 2 — Shadow Approval
ATM marks recommendations. Operator manually approves via dashboard
or /ptapprove. No automatic broker order submission.

## Mode 3 — Paper Active Limited
Paper only. Strict caps (1/day, 2 concurrent, 0.10% risk).
Broker-native stops required. One account, limited strategy scope.
Stop reconciliation runs every cycle.

## Mode 4 — Paper Active Expanded
After 3-5 clean days at Mode 3. Caps relaxed (2/day, 0.25% risk).
Broader strategy list. Still paper only.

## Mode 5 — Live Readiness
**BLOCKED.** Requires: strategy proof ≥ 6.0, maturity ≥ 7.5,
A-5 complete, backup/recovery proven, live risk review, John's approval.

## Recommended Path
Frozen → Mode 1 (3-5 days) → Mode 3 (3-5 days) → Mode 4 → re-evaluate
