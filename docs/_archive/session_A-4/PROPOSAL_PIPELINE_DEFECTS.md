# Proposal Pipeline Defect Investigation — Session A-4

**Date:** 2026-05-15
**Investigator:** Session A-4

## Root Cause — Systemic Defect S1

### scan_run_label mismatch blocks cross-run signal visibility

**File:** `scripts/auto_proposal_generator.py:208-210`
**Defect code:** S1 (systemic — affects ALL strategies)

**What happened:**
Pre-market signal generation (0400 run) produces signals with `scan_run_label = '0400'`.
Daytime proposal generator runs pass `run_label = '1730'` (or 1200/1400/1600).
The query filter `AND (scan_run_label = %s OR scan_run_label IS NULL)` EXCLUDES
all pre-market signals from daytime proposal runs.

**Evidence:**
- `strategy_signals` has 24 signals today, all with `scan_run_label = '0400'`
- `auto_proposal_runs` last 5 runs: ALL show `signals_checked = 0`
- Direct test: `get_eligible_signals(run_label='1730')` returns 0
- Direct test: `get_eligible_signals(run_label=None)` returns 24

**Impact:**
Every strategy — including the 7 already producing trades — was getting
proposals ONLY when the proposal generator happened to run at the same
time as signal generation. This is why trade velocity has been low
(~3 trades per day instead of the expected 5-8).

**Fix applied:**
Removed the `run_label` filter from `get_eligible_signals()`. The existing
`fired_at::date = CURRENT_DATE` filter already scopes to today's signals.
Now all same-day signals are visible to every proposal generator run.

**Verification:**
- Before fix: `get_eligible_signals(run_label='1730')` = 0 signals
- After fix: `get_eligible_signals(run_label='1730')` = 24 signals
- Strategies now visible: speculative_growth, recovery_watch, sector_rotation,
  fib_retracement_bounce, earnings_post_momentum, plus 13 others

**Risk:** LOW — the run_label was an over-constraint. Removing it makes
the proposal generator see ALL same-day signals, which is the intended behavior.
The dedup logic (`check_duplicate`, `check_open_paper_trade`, `check_recently_closed`)
prevents duplicate proposals.

## Secondary Finding — Approval Bandwidth

Proposals that DO get created sit at `PENDING` for 3 days, then auto-expire.
The incubator_proposal_promoter creates proposals but they require operator
approval via dashboard. With 17+ strategies generating proposals, operator
cannot review them all.

This is NOT a code defect — it's an operational constraint. Possible mitigations:
- Auto-approve paper proposals that pass all risk gates (Phase C consideration)
- Extend expiry window from 3 days to 5 days
- Batch-approval in morning brief

Deferred to Phase C (auto-tuning + approval flow).
