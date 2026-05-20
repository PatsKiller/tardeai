# PIPE-OBS-1 — Pipeline Run Telemetry

**Status:** COMPLETE

## Root Cause

pipeline_runs table had 17 rows (from May 9-11) but the Pipeline Operations API queried `script_name` column which doesn't exist — the table uses `pipeline_key`. The API query silently returned empty, making all 31 stages appear as never-run.

## Fixes

1. **API query fixed**: `pipeline-health` and `pipeline-health-master` now query `pipeline_key` instead of `script_name`, and use correct column names (`finished_at`, `duration_seconds`, `summary->>'rows_produced'`).

2. **Telemetry writer** (`pipeline_run_telemetry.py`): `record_stage_run()` writes to pipeline_runs using `pipeline_key` as the stage identifier matching the UI.

3. **Telemetry wrapper** (`run_with_pipeline_telemetry.sh`): Wraps any command to record start/finish/status.

4. **Smoke test**: Inserted 1 dry_run row (`PIPE_OBS1_SMOKE_TEST`), clearly marked non-production.

## State

- pipeline_runs: 18 rows (17 original + 1 smoke)
- Original rows used `pipeline_key='daily'` — future per-stage records will use individual stage names
- API now reads the table correctly

## Tests

9/9 pass.
