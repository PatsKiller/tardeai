# SCREENER-ARCH-3D — Operator-Approved Falloff Lifecycle Apply

**Status:** COMPLETE (13/15 done, 2 operator-gated)

## What Was Delivered

1. **Baseline report** (`scripts/report_screener_arch3d_baseline.py`):
   - 1,129 active candidates, 976 source-missing, 136 expire candidates
   - 15 protected by active watchpool

2. **Upgraded lifecycle script** (`scripts/report_and_apply_incubator_falloff_lifecycle.py`):
   - `--operator-approved-expire` flag required for expire
   - `--operator-approved-archive` flag required for archive
   - `--max-apply N` cap
   - Protection checks: open trade, pending proposal, active watchpool
   - 8 lifecycle states: active, source_missing, retained_by_ttl, expired_pending_operator_review, archived_human_review_only, reentered, needs_refresh, needs_strategy_fit_recheck

3. **Safe apply results**:
   - 993 candidates updated (non-destructive lifecycle_state only)
   - 885 source_missing, 153 active, 89 needs_refresh
   - 136 expire candidates blocked (no operator flag)
   - 0 deletions, 0 status changes to EXPIRED

4. **Cron wrapper fix verification**: 3 jobs confirmed working by actual cron (watchpool, telegram, quote refresh)

## What Is Operator-Gated

- Expire: 136 candidates ready, requires `--operator-approved-expire`
- Archive: not requested, requires `--operator-approved-archive`

## Tests

21/21 ARCH-3D + 23/23 ARCH-3C regression.
