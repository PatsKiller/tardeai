# ATM Dry-run Burn-in — Next Phase Prompt

Status:      HISTORICAL
as_of:       2026-05-26T11:21:21-04:00
Measured at: efcc51365 / not measured

**Prerequisite:** John approves decision package
**Mode:** dry_run ONLY — no active execution

## Hard Rules
- Do not enable ATM active mode
- Do not submit orders
- Do not create trades
- Do not approve proposals
- Do not move stops
- Do not modify .env

## Tasks

1. Verify ATM in dry_run mode
2. Run unified stop supervisor dry-run — confirm 5/5 reconciled
3. Run ATM auto-approver — review dry_run_approved/rejected decisions
4. Compare ATM would-approvals against operator judgement
5. Check enrichment pipeline freshness
6. Check strategy distribution of would-approvals
7. Create daily burn-in report:
   - decisions: approved/rejected/deferred counts
   - stop reconciliation: all reconciled?
   - enrichment: all complete?
   - quote failures: count
   - strategy distribution
   - safety events: must be 0
8. Telegram summary to both IDs

## Exit Criteria for Phase A
- 0 false approvals
- 0 critical stop findings
- 0 safety events
- All cycles clean for 1 full trading day

## After Phase A
Proceed to Phase B (3-day extended dry-run) per burn-in plan.
