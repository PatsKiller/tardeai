# Premarket Scheduler Runbook (RENDER ONLY — nothing scheduled here)

Module: `scripts/active_trader/premarket_observation_schedule.py`

## What this build transaction does
- Computes the schedule plan (disposition + next qualifying session).
- RENDERS a one-shot user-level transient timer (unit properties, argv, env NAME allowlist, cleanup
  plan, dry-run shell text). **It never calls systemd-run/systemctl/at/cron and starts nothing.**
- `--execute-schedule` returns `NOT_AUTHORIZED_BY_BUILD_TRANSACTION`.

## Later live scheduling (requires a separate owner observation prompt)
The rendered transient unit is designed to be, when a later prompt authorizes it:
user-level only · transient · one-shot · no linger change · no boot persistence · credentials loaded by
the existing wrapper at runtime (never in unit text or argv) · WorkingDirectory pinned to the worktree
· absolute launcher path · bounded TimeoutStartSec · KillMode=mixed/SIGTERM · logs in the approved lab
state path · no production path.

## Live authorization marker (controller §18)
The live executable refuses to run without an `ObservationAuthorizationMarker`
(run_id, session_number, expected_git_sha, target_market_date, target_window, symbols_policy,
created_at, expires_at, owner_authorization_version — **no secret**). Without it the launcher returns
`BLOCKED_OWNER_AUTHORIZATION_REQUIRED`. The marker is verified against: current git SHA, clean worktree,
session number, calendar date + qualification, non-expiry, Stage 5 smoke PASS evidence, credential
readiness GREEN, and trade-API scan PASS. **This build transaction does not create the marker.**

## Dry run
`python scripts/run_active_trader_premarket_observation.py --mode dry-run`
prints the plan + redacted transient-unit render with `scheduler_executed: false`.
