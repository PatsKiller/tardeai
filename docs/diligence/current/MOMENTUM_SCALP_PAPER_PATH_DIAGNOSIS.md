# Momentum Scalp Paper-Path Diagnosis

**Status: PASS** | window: 365d  
_Generated: 2026-06-28T04:24:44.907751+00:00_  
_Source: `python3 scripts/diagnose_momentum_scalp_paper_path.py --days N --json`_  

## First bottleneck: `approval_fails_on_stale_quote`

> Proposals reach ATM but approval fails 148× (gate=approve_proposal_failed); dominant cause: approve_proposal_failed: Not a good trade under current conditions: CNVS is now $3.20, 3.6. The freshness gate is working correctly — the gap is generating a momentum_scalp proposal with a FRESH in-window quote AND approving it before the 30-min TTL. Not a code bug; do NOT weaken freshness.

## Stage counts

| Stage | Value |
|-------|-------|
| strategy_signals | 133 |
| proposals_created | 104 |
| proposals_by_status | EXPIRED=53, REJECTED=51 |
| proposals_by_lifecycle | ACTIVE=45, ENTRY_ZONE_VALID=38, EXPIRED=19, ENTRY_MISSED=2 |
| proposals_approved_for_paper | 0 |
| proposals_expired | 53 |
| proposals_pending | 0 |
| auto_proposal_decisions | SKIPPED_STRATEGY_CRITERIA=413, SKIPPED_RECENTLY_REJECTED=364, SKIPPED_OUTSIDE_RTH=283, CREATED=257, SKIPPED_NOT_GO=175, SKIPPED_LIQUIDITY=156, SKIPPED_DUPLICATE=82, SKIPPED_RECENTLY_CLOSED=37, SKIPPED_OPEN_TRADE=17, SKIPPED_NO_ANALYST=14, SKIPPED_LOW_SCORE=5, SKIPPED_STALE_QUOTE=5, SKIPPED_PREPROMOTION=1 |
| atm_decisions | rejected=190, deferred=35, approved=13 |
| atm_rejection_gates | approve_proposal_failed=148, atm_expired=37, not_yet_enriched=20, same_day_strategy_atm_cadence_too_slow=13, account_resolution_missing=5, broker_submit_failed=2 |
| approval_failure_sample | approve_proposal_failed: Not a good trade under current conditions: CNVS is now $3.20, 3.6% above proposed entry $3.09. Trade parameters are stale — resubmit with fresh analys |
| paper_trades_by_status | cancelled=18, closed=3, dedup_removed=1 |
| confirmed_paper_trades | 2 |
| non_executed_rows | 19 |

> Read-only diagnosis. No broker writes. Paper-only. Operator/2FA path unchanged.

