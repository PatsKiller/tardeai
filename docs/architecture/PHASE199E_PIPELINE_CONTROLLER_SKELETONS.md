# Phase 199E — Pipeline Controller Skeletons (DRY-RUN, no schedules wired)

Status:      HISTORICAL
as_of:       2026-06-04T22:43:09-04:00
Measured at: efcc51365 / not measured

Seven controller skeletons under `scripts/pipelines/`, one per target pipeline (199C). **No active
cron/timer is replaced or scheduled.** Each is `DRY_RUN=1` by default and, even with `--apply`, does
NOT execute child steps in this design phase — wiring happens only after the approved migration (199D).

## Files
- `scripts/pipelines/_pipeline_common.sh` — shared harness: safe env load, UTC start/end timestamps,
  per-pipeline log (`logs/pipelines/<name>.log`), `flock` lock handling (clean skip if held),
  `run_step` (dry-run describe), and **two hard safety assertions that return nonzero on failure**:
  - `assert_no_live_trading` — requires `ALPACA_MODE=paper` and `LIVE_TRADING_ENABLED`/`LIVE_TRADING` ≠ true
  - `assert_no_level7` — fails if `LEVEL7`/`LEVEL_7`/`ENABLE_LEVEL7` = true
- `run_tradeai_market_pipeline.sh` · `run_tradeai_after_close_pipeline.sh` ·
  `run_hermes_advisory_pipeline.sh` · `run_hermes_research_pipeline.sh` ·
  `run_llm_control_pipeline.sh` · `run_governance_pipeline.sh` ·
  `run_portfolio_maintenance_pipeline.sh`

## Each controller
- sets strict bash mode (`set -euo pipefail` via the lib), loads env safely
- echoes START/END with UTC timestamps + `DRY_RUN` value
- runs the two safety assertions and **aborts (nonzero) on failure**
- acquires a per-pipeline `flock`; if already held, skips cleanly (exit 0, not a failure)
- logs to `logs/pipelines/<pipeline>.log`
- lists its intended child steps as `run_step` calls (dry-run echo only)

## Smoke test (this phase)
- `bash -n scripts/pipelines/*.sh` → all OK.
- `DRY_RUN=1 run_tradeai_market_pipeline.sh` → safety ✓✓, lock acquired, 7 steps echoed, exit 0.
- `DRY_RUN=1 run_hermes_advisory_pipeline.sh` → safety ✓✓, 4 steps echoed, exit 0.

## Explicitly NOT done
- No schedules wired (no new timers/crons; no existing ones touched).
- No child step executed (skeleton only).
- No live trading, no Level 7, no GO/WAIT or strategy mutation.

## Next (later, approval-gated)
Per 199D: move one pipeline's scripts into its controller at the SAME cadences, run controller +
old cron in parallel for one cycle, diff, then retire the commented cron lines. P0 group first.

---
*Skeletons only. DRY_RUN default; safety-assert on every run; no schedules wired.*
