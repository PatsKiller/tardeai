# ATM Re-enable Burn-in Plan

Status:      HISTORICAL
as_of:       2026-05-26T11:21:21-04:00
Measured at: efcc51365 / not measured

## Phase A — Dry-run Observation (1 full trading day)
- ATM mode: dry_run
- No orders submitted
- Compare ATM would-approvals against operator judgement
- Verify stop reconciliation each cycle
- Check enrichment pipeline freshness
- **Exit criteria:** 0 false approvals, 0 critical findings, all cycles clean

## Phase B — Extended Dry-run (3 trading days)
- ATM mode: dry_run
- Track would-approve quality distribution
- Monitor false approval/rejection rate
- Check strategy distribution (no single strategy dominance)
- **Exit criteria:** <5% false approval rate, 0 critical findings, enrichment 100%

## Phase C — Shadow Approval (2 trading days)
- ATM recommends, operator manually approves
- No automatic broker orders
- Operator reviews each recommendation before acting
- **Exit criteria:** Operator agrees with 90%+ of ATM recommendations

## Phase D — Limited Paper Active (3-5 trading days)
- 1 approved strategy family
- 1 paper account
- 1/day max entries
- Broker-native stops required
- Immediate freeze on any critical issue
- **Exit criteria:** 3+ clean trades, 0 stop reconciliation failures, 0 safety events

## Metrics (Primary = Safety)
- Decision count per day
- Would-approve / approved count
- Rejected / deferred count
- Quote failure count
- Stop reconciliation failures
- Audit logging failures
- Strategy mismatch count
- **Safety events (primary metric):** must be 0
- PnL (secondary during burn-in)
