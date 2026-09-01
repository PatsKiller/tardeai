# Phase 204D — Minimal Fix for secrets_state_backup

Status:      HISTORICAL
as_of:       2026-06-05T12:08:22-04:00
Measured at: efcc51365 / not measured

**Fix:** the cadence-aware controller's `backup` cadence calls the script correctly with BOTH legacy
arguments — `backup_secrets_state.sh env` and `backup_secrets_state.sh data` — matching the legacy
cron exactly (replacing the old single no-arg call). Implemented in
`scripts/pipelines/run_portfolio_maintenance_pipeline.sh` (`run_backup()`).

- No credential change, no Drive-destination change, no rotation, no secrets printed, no broad refactor.
- The non-cascading controller already surfaces a failed backup step in the summary JSON (visible in
  v3). Validated by the backup-cadence `--apply` pilot (204G).
- This is a local call fix; gog/auth/Drive were never the problem.
