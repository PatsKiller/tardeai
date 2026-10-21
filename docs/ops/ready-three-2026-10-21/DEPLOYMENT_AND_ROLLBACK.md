# Deployment and rollback gates — 2026-10-21

**Status:** Exact-head required/non-skipped CI passed, but deployment has not occurred; separate exact-SHA release authority/lease and operational risk disposition remain required.
**Updated:** 2026-10-21 03:45 UTC

This document records release criteria; it does not authorize a release.

## Preconditions

- Candidate SHA and tree are exact and reviewed; local focused tests pass.
- Exact-head hosted CI passed for pushed SHA 641 (all required/non-skipped checks); cio-hardening-full and main-red-alert were skipped by PR-event rules. A green check on parent/old PR head is insufficient. If source SHA changes, repeat checks for that exact SHA.
- The separate local full hardening profile has unresolved assertions and an incomplete DB-backed lane; hosted cio-hardening passed. Resolve or explicitly disposition the local-profile gaps under established criteria before release.
- Production health, SPCX containment, screener underfill, and indicator JSON failure have an owner and a safe disposition. Indicator fix PR #1889 hosted checks are still pending; do not treat this as production-qualified. Do not clear the SPCX switch or lower the screener floor to make a check green.
- PR #1887 is OPEN / CLEAN (mergeable), not merged or deployed. Obtain canonical exact-SHA release authority and deployment/production lease before any promotion. A push grant, green CI, PR merge, or broad development authorization does not imply deployment authority; authority is exact-SHA-only.
- Run the repository's canonical release procedure for the approved SHA and record its output.

## Promotion

Use the canonical guarded release workflow and exact release script selected by the operator/release process. Verify the staged release identity before promotion. Do not substitute a manual symlink switch or deploy from an unqualified worktree.

After promotion, complete every evidence item in [live validation](LIVE_VALIDATION.md), including build identity, unit/process working directories, endpoint schema/counters, health deltas, clocks, and UAT scope. If a check fails, stop promotion/traffic according to the canonical procedure and preserve evidence for root-cause analysis.

## Rollback

Rollback target must be the previously recorded exact release directory, not a guessed branch head. Use only the canonical rollback procedure under its required authority and lease. Verify the restored build metadata, service states/process directories, communications summary, health deltas, and operator-facing behavior. Record the actual target and results in the release log.

Current known production identity at 03:42:26 UTC is ef085ce76be4512da71a58e65ef4feb25d156206; aggregate counters are 0 unsettled / 0 failed / 6 reaped / 2024 total, health score 78 with 2 critical / 23 warning / 15 info, and the indicator incident remains unrecovered. This is an observation, not an automatically approved rollback decision.
