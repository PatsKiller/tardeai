# AFTERHOURS-READY-1 — Full After-Hours Candidate Preparation Pipeline

**Status:** COMPLETE

## Root Cause

The 17:30 "RUN_UNDERFILLED / Scanned: 6" was intentional — the cron uses `--allow-underfilled` for a narrow incremental cleanup pass. The real after-hours coverage comes from the 14:00 (827 symbols) and 16:00/18:00 screener runs.

## What Was Delivered

1. **After-hours readiness runner** (`run_afterhours_candidate_preparation.py`):
   - Loads full active catalog (1,311 symbols)
   - Uses existing ARCH-4 strategy-fit audit data
   - Classifies each symbol: ready_for_review (39), watchpool_candidate (186), needs_data (619), blocked (331), no_fit (136)
   - All candidates human_review_only, executable_now=FALSE

2. **After-hours snapshot** (2 tables): afterhours_candidate_snapshot + afterhours_readiness_run

3. **API**: GET /api/v2/afterhours-readiness/summary — shows readiness breakdown

4. **Digest**: Clean after-hours readiness digest with top 3 candidates

5. **Cron**: `30 17 * * 1-5` — runs daily after close

6. **Runtime verification**: PASS — 5/5 checks

## Tests

17/17 pass.
