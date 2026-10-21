# Deployment and rollback gates — 2026-10-21

**Current status (2026-10-21 04:23 UTC):** No deployment. PR #1887 active checks passed at `e5ebdc6` subject to event skips. PR #1889 `7c187363191ade3c574c7a77bde8e0b3885ff370` is pushed; exact-head hosted CI restarted with no results yet. Local validation (82 passed / 3 skipped, coverage `NEW=0`, `py_compile`, diff checks) is not release qualification. Production remains degraded and indicator unrecovered. Do not promote either candidate.
**Updated:** 2026-10-21 04:23 UTC

This document records release criteria; it does not authorize a release.

## Preconditions

- Candidate SHA and tree must be exact and reviewed; local focused tests alone do not qualify release.
- Historical exact-head hosted CI passed for ready-three SHA 641; current #1887 head `e5ebdc6` has active checks passed, with cio-hardening-full/main-red-alert skipped. Indicator remediation PR #1889 is at `7c187363191ade3c574c7a77bde8e0b3885ff370`; exact-head hosted CI restarted with no results yet. Checks on prior SHAs do not qualify 7c. Require exact-current-head results before release consideration.
- The separate local full hardening profile has unresolved assertions and an incomplete DB-backed lane; hosted cio-hardening passed. Resolve or explicitly disposition the local-profile gaps under established criteria before release.
- Production health, SPCX containment, screener underfill, and indicator incident have an owner and a safe disposition. Production remains unhealthy/degraded and `indicator_engine` is unrecovered; do not treat PR #1889 as a live fix. Do not clear the SPCX switch or lower the screener floor to make a check green.
- Validate the indicator remediation against the natural weekday 08:00 ET `scripts/indicator_engine.py --universe` scheduled run. At the 04:10 UTC probe it had not yet fired that day; last run was Oct 19 12:00 UTC (26 attempted, 1 upserted, 25 skipped for `no_ohlcv`). Inspect the next run's receipt, output and logs after it occurs. Do not trigger the production writer manually for qualification. Historic NaN logs prove an earlier failure mode, not today's root cause.
- PR #1887 is OPEN / CLEAN (mergeable), not merged or deployed. Obtain canonical exact-SHA release authority and deployment/production lease before any promotion. A push grant, green CI, PR merge, or broad development authorization does not imply deployment authority; authority is exact-SHA-only.
- Run the repository's canonical release procedure for the approved SHA and record its output.

## Promotion

Use the canonical guarded release workflow and exact release script selected by the operator/release process. Verify the staged release identity before promotion. Do not substitute a manual symlink switch or deploy from an unqualified worktree.

After promotion, complete every evidence item in [live validation](LIVE_VALIDATION.md), including build identity, unit/process working directories, endpoint schema/counters, health deltas, clocks, and UAT scope. If a check fails, stop promotion/traffic according to the canonical procedure and preserve evidence for root-cause analysis.

## Rollback

Rollback target must be the previously recorded exact release directory, not a guessed branch head. Use only the canonical rollback procedure under its required authority and lease. Verify the restored build metadata, service states/process directories, communications summary, health deltas, and operator-facing behavior. Record the actual target and results in the release log.

Current known production identity at 03:42:26 UTC is ef085ce76be4512da71a58e65ef4feb25d156206; aggregate counters are 0 unsettled / 0 failed / 6 reaped / 2024 total, health score 78 with 2 critical / 23 warning / 15 info, and the indicator incident remains unrecovered. This is an observation, not an automatically approved rollback decision.

## Latest readiness evidence — 2026-10-21 04:23 UTC

The direct production audit at 04:21:28 UTC reports build `ef085ce76be4512da71a58e65ef4feb25d156206`; health 78/degraded with 3 criticals including global SPCX kill switch, stale SETUPS session, and six underfilled 0700 runs; `indicator_engine` unrecovered and orchestrator false. This evidence does not show ready-three or indicator remediation deployed. Historic NaN traceback does not establish the current root cause.

PR #1889 SHA `7c187363191ade3c574c7a77bde8e0b3885ff370` is pushed. Local validation was 82 passed / 3 skipped, coverage `NEW=0`, `py_compile`, diff checks, and full-tree secret scan passed. Exact-head hosted CI restarted with no results yet. This is insufficient for release. Await exact CI, confirm isolated PostgreSQL coverage, and observe the next scheduled production cron result without manually launching the live writer. No production readiness claim is made.
