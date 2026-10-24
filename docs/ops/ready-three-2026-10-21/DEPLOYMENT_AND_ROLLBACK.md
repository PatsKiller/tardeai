# Deployment and rollback gates — 2026-10-21

## Current release hold — 2026-10-22 20:08 UTC

Integrated candidate SHA `88fbafcc27b58b4ea1c78f5e78fcfa9059a5d170` includes latest main `b9804fa577e6d2793f4539c7458452707a350f61` and the ready-three security fixes. Focused validation passed 104 self-heal, 80 security/reaper/flock/pipeline, and 49 workflow tests. One incoming gate test fails because the new desk-truth monitor reads `positions_current` outside the only approved Watch reader scope. Do not promote or add a grant/exemption to clear it. This exact candidate has not passed the full profile or hosted CI, and no deployment was made. The last supplied production health snapshot at 15:45Z was 78/degraded with 3 criticals; obtain a fresh read before any release decision. Proposed sudoers/systemd artifacts remain unapplied. Keep C3 disabled.

## Superseding release hold — 2026-10-22 13:45 UTC

Current local candidate is clean SHA `4fc9928a5a38f3167d9f164a46e1aacf9bca997d`, integrated with current `origin/main` df3e and containing the exception-safe symbol-lock cleanup fix. Focused tests and docs checks pass. Its predecessor `bc729ac1…` passed the full local profile, but current HEAD has not. Production serves c81 and remains unhealthy (78, 3 critical, 24 warnings). GitHub confirms no PR, remote candidate branch, or hosted run. The active `release-write` grant names PR #1915 and does not authorize this candidate.

Do not promote. Run a new full profile on the final exact HEAD, complete hosted checks and database-backed validation, resolve production health risks, and obtain exact candidate scopes through the canonical guard. Confirm rollback target and persistent-state mappings; after any authorized deployment, verify served SHA, semantic endpoints, health, and natural scheduled-run evidence, with rollback on acceptance failure. C3 remains disabled.

---

## Superseding release hold — 2026-10-22 12:45 UTC

Production serves `c81eb463c4a039046a5d4e1d1ad81ed998eaee98` (build time 12:43:07Z). Health at 12:44:14Z is 78/degraded/unhealthy with 3 criticals and 23 warnings. The current local candidate is merged SHA `1b05fa7bd4f412ec4d3ca65c09ce2a762f15c180`; its focused tests pass, but its exact full profile has not passed. GitHub lookup failed due DNS, so PR and hosted-check state are unverified. The sole active release grant is tied to merged PR #1913 / c81 and does not authorize this candidate.

Do not promote. Before deployment, integrate the candidate with a refreshed current main, obtain a terminal exact-SHA full-profile pass and hosted CI for the exact PR/merge SHAs, resolve the production health criticals under their owners, verify rollback target and persistent-state mappings, and obtain the exact canonical scopes required for push and release. After any authorized deployment, verify served SHA, semantic endpoints, health recovery, and scheduled natural-run evidence; automatically roll back if required acceptance fails. C3 stays disabled.

---

## Current live hold — 2026-10-22 07:37 UTC

Production SHA `4104effb…` remains degraded at 78/unhealthy based on health capture `2026-10-22T07:33:53.604977Z`, with 6 critical, 24 warnings, and 30 actionable findings. Criticals include pipeline failures, global SPCX kill switch, stale SETUPS date, six underfilled 0700 runs, backup count above one, and backup storage above cap. Do not run backup cleanup without reviewed retention disposition. Candidate code SHA `1cba3e8…` passed the full local profile with exit 0 in 2,628 seconds, including docs-index and manifest checks. GitHub PR and Actions queries returned empty; candidate remote branch presence is unverified and it is not deployed. At 07:37, `bin/guard show` reported no active grants. Keep production unchanged until health criteria, hosted checks, and canonical guard requirements are met.

## Candidate qualification boundary — 2026-10-22 07:37 UTC

Exact committed code SHA `1cba3e8db005a3ad6cd3085e93189f53c4742473` passed `scripts/run_cio_hardening_ci.py --profile full --jobs 4` (exit 0, 2,628 seconds). Candidate manifest hash: `3bb9acba69331ee03a4d98acefa9ba5420141faba71c0d9cd9b0a47b2cedcbd3`. Intentional test skips/xfails and hermetic live-DB refusals remain; hosted CI, isolated PostgreSQL integration, performance, failover, UAT, and production verification remain outstanding. Docs-only reconciliation passed its inventory/index, docs-index, coverage, and diff checks. No deployment was attempted.

Production SHA `4104effb…` remains degraded at 78, unhealthy, with 4 critical, 24 warnings, and 28 actionable findings: 92 `EFFECT_NOT_OBSERVED` pipeline run failures, active SPCX kill switch, stale SETUPS session (`run_date=2026-10-21` for 10/22 ET; RCA pending), and six underfilled 0700 runs. There are no active grants in the production checkout. Final candidate `619e1d4d…` is in profile session 92256, still nonterminal; no push, PR, hosted CI, or deployment is evidenced. Keep production unchanged.

## Latest qualification disposition — 2026-10-22 04:28 UTC

Combined SHA `1a1825ba41fe2a7ee9f01f43f3e21088b0072063` failed its full profile at 2,638s with one `N8N_RUN_ROUTE` PIDFILE-only stale assertion; every other gate and manifest/index check passed. Isolated test correction `0534a85b…` reports 21/21 targeted tests, but corrected final SHA still requires full-profile qualification. The prior `ca8b3658…` pass does not qualify the corrected candidate. Keep deployment held; production/guard evidence remains time-scoped in [current status](CURRENT_STATUS.md).

## Combined candidate remains unqualified — 2026-10-22 03:44 UTC

The pre-combination candidate `ca8b3658…` now has a terminal ALL GATES PASS and successful docs/manifest checks; duration is approximate only. Final combined SHA `1a1825ba41fe2a7ee9f01f43f3e21088b0072063` (candidate fixes plus origin/main `63d37108`) is in a fresh full profile, still running. Targeted blocker-fix suite reports 24 passed, with exact invocation not supplied. No push, PR, hosted checks, deployment, or candidate-specific release authorization is established. Do not promote until the combined exact-SHA run and remaining production gates are resolved.

## Current release hold — 2026-10-22 03:20 UTC

Production is still SHA `4104effb…`, health 78/degraded/unhealthy with 3 critical and 23 warnings. Candidate `ca8b3658…` is local-only, has no PR/hosted checks, and is five commits behind `origin/main` despite sharing the live SHA as its base. Full profile 42646 is still active; overnight maturity passed 2,143/2 skipped and `maturity_score_stale` is next. Guard `de5824f7` is Release 2 / PR #1910 only. No candidate release authority or terminal qualification is verified; keep production unchanged.

## Fresh production guard and candidate hold — 2026-10-22 03:04 UTC

Production currently reports main `4104effb99f3ced9e13ed63afc53c5e5fc7aa8c5` (built 02:09:41Z); health at 03:04:59Z is 78/degraded/unhealthy with 3 critical and 24 warnings. Guard `de5824f7` (one use, 31 minutes remaining) is scoped to Release 2 / PR #1910 at that main SHA; it does not authorize candidate `ca8b3658`. The new candidate full profile is active, not terminal. Keep candidate promotion held pending its exact-SHA result and separate release authority/production readiness evidence.

## Current post-merge candidate hold — 2026-10-22 02:59 UTC

The candidate now points to `ca8b3658e4dcde8334932296f647b9da42b66587` after a clean merge of current `origin/main` (0 behind / 16 ahead, no conflicts). Its full-profile result is pending. The previous 556/556 pass was on pre-merge `252072a7…` and cannot qualify this new head. Keep production unchanged while exact-SHA requalification, hosted CI, database validation, and release authorization remain unresolved.

## Latest qualification and deployment decision — 2026-10-22 02:58 UTC

The second exact-SHA full profile for candidate `252072a7b942ab03994912b7a82f503457724a31` passed 556/556 gates at exit 0 in 3,075s. This closes the local full-profile gate only. Hosted CI, isolated PostgreSQL/production-schema behavior, live production validation, candidate-specific release authority, and operational recovery remain separate and unverified. Candidate manifest `5ca8f9…` is marked `release_candidate` and differs from production pin `aa037b…`; no deployment occurred. Preserve production hold until all remaining release criteria are evidenced. See [test results](TEST_RESULTS.md) and [current status](CURRENT_STATUS.md).

## Current execution hold — 2026-10-22 01:04 UTC

Keep production unchanged. It serves d55 and remains degraded (score 78, latest health capture 00:46Z); new read-only evidence shows 239 raw failure rows across eight keys at 00:49:55Z and an unauthenticated communications-health response returning CANARY ledger metadata. Candidate `2e23ffb9f84b95ef3f76d567d4467a9d78f96dc5` is local only. Its exact focused gates pass (alarm 6/6, pipeline/verifier 10/10, reaper identity 7/7, zombie runs 8/8) and coverage audit is clean, but the exact-SHA full profile and hosted CI remain pending. The c2 predecessor run was at 410/556 with two failed gates. Guard `7dca80d0` authorizes only d55 Release 1/PR #1909; it does not authorize this candidate. No push, deployment, or auth change is justified.

## Prior execution hold — 2026-10-22 00:44 UTC

Do not promote the integrated candidate yet. c2's current full-profile run is still active with one known failed `ci_self_guards` gate; the integrated branch `0090b035ea8b483a1e37001920832221f77be5a6` fixes registration and combines diagnostics, real locking and reaper identity hardening. It passes focused suites (31 and 277 tests) and has not run the full profile or hosted CI. Production health remains degraded, auth is report-only, reaper cadence is unverified, 0700 runs are genuinely underfilled but report artifacts show no execution errors, and health-row/DB status is absent. The existing guard grant is scoped to d55 Release 1, not this candidate. Preserve production and do not tune reaper policy or enable C3 until exact-SHA full qualification, hosted checks and operational readiness are complete.

## Current deployment decision — 2026-10-22 00:24 UTC

**Hold candidate promotion and global auth changes.** Production serves exact main `d55da84d004be304c9f10b0c643aae451784be7d`, built `2026-10-22T00:08:15.726Z`; deployment actor and complete runtime provenance remain unknown. The latest health snapshot (00:21:35Z) remains 78/degraded and unhealthy: 60 pipeline failures, while verifier detail reports 61 unrecovered; the 00:21:10Z remediation exited 0 but is unverified. Communications health returns HTTP 200 without credentials because deployed `report_only:true`; caller coverage and external exposure are not established. Candidate `c2c01404` remains local and its full profile was interrupted (exit 130), with no aggregate result. Guard `7dca80d0` is scoped to Release 1 / PR #1909 at d55 and does not authorize candidate c2. Reassess only after health criticals have owner disposition, auth callers and rollback are covered, production-schema/natural-writer behavior is proven, candidate exact-SHA validation and hosted checks pass, and current candidate-specific release authority exists. See [execution review](EXECUTION_REVIEW_2026-10-21.md).

## Superseding readiness status — 2026-10-21 19:03 UTC

The approved full-profile run reported 517/517 gates, but its exact source SHA was not retained and it does not qualify local candidates. Production serves `a6ac0eb`; health at 19:07:50Z is 78/degraded and unhealthy (4 critical, 25 warning, 14 info, 43 total, 29 actionable). At 19:12:21Z an unauthenticated local-listener GET to the communications summary returned HTTP 200 with real aggregate data. This is a **High priority confirmed local-listener exposure**; external access is unverified. Hold production auth flip due caller compatibility and operator lockout risk; no credentials were read. Remote main remains `1fc525a`; PRs #1887/#1889 remain open/dirty at old heads, and GitHub API is currently unreachable. Final candidates remain local without hosted exact-SHA CI. Critical findings include pipeline failures, revoked Schwab token requiring manual reauth, SPCX kill switch, and six 0700 failures. Schwab-only guard grants do not authorize these candidates or deployment. Production-schema and alert integrations remain unverified. Watchdog candidate `ebe997d3` passes 51 tests and static checks but remains bounded/unhosted; descendant termination and the orchestrator cap remain unresolved. No deployment was performed. Do not promote until exact-SHA hosted qualification, safe auth disposition, production risk closure, post-deploy scheduled run, C3 verification, and canonical release authority are satisfied.

The refreshed watchdog candidate `ebe997d37572dd9ddca0776b836c46f2b027d982` is local/unhosted and not release-qualified: 51/51 focused suites plus static checks pass, but forked-descendant termination and durable work supervision remain unresolved. It does not address the external 20-minute process-reaper cap. No push, deployment, or retry occurred.

**Historical status at 15:40 UTC (superseded above):** See the readiness update above. This timestamped snapshot is retained for history only.
**Updated:** 2026-10-21 18:46 UTC

This document records release criteria; it does not authorize a release.

## Preconditions

- Candidate SHA and tree must be exact and reviewed; local focused tests alone do not qualify release.
- Historical exact-head check result: PR #1887 at `1707d3c074774a7d7b7379cb717db421fa979c45` had 20 active checks pass / 2 skipped; PR #1889 at `7c187363191ade3c574c7a77bde8e0b3885ff370` had 18 pass / 2 skipped. At the 15:40 UTC refresh both PRs were OPEN/CONFLICTING. Local docs and indicator follow-ups remain outside hosted checks; resolving conflicts and obtaining exact-head CI are prerequisites before release consideration.
- The separate local full hardening profile has unresolved assertions and an incomplete DB-backed lane; hosted cio-hardening passed. Resolve or explicitly disposition the local-profile gaps under established criteria before release.
- Production health, SPCX containment, screener underfill, and indicator incident have an owner and a safe disposition. Production remains unhealthy/degraded and `indicator_engine` is unrecovered; do not treat PR #1889 as a live fix. Do not clear the SPCX switch or lower the screener floor to make a check green.
- The Oct 21 natural weekday 08:00 ET `scripts/indicator_engine.py --universe` run failed at 12:00:14 UTC; logs confirm PostgreSQL rejected NaN in `pivots_weekly.pp` on the old release. The failure confirms root cause but does not qualify the fix. After any separately authorized release, inspect a later natural run's receipt, output and logs. Do not trigger the production writer manually for qualification.
- PR #1887 is OPEN / CLEAN (mergeable), not merged or deployed. Obtain canonical exact-SHA release authority and deployment/production lease before any promotion. A push grant, green CI, PR merge, or broad development authorization does not imply deployment authority; authority is exact-SHA-only.
- Run the repository's canonical release procedure for the approved SHA and record its output.

## Promotion

Use the canonical guarded release workflow and exact release script selected by the operator/release process. Verify the staged release identity before promotion. Do not substitute a manual symlink switch or deploy from an unqualified worktree.

After promotion, complete every evidence item in [live validation](LIVE_VALIDATION.md), including build identity, unit/process working directories, endpoint schema/counters, health deltas, clocks, and UAT scope. If a check fails, stop promotion/traffic according to the canonical procedure and preserve evidence for root-cause analysis.

## Rollback

Rollback target must be the previously recorded exact release directory, not a guessed branch head. Use only the canonical rollback procedure under its required authority and lease. Verify the restored build metadata, service states/process directories, communications summary, health deltas, and operator-facing behavior. Record the actual target and results in the release log.

Current known production identity at 03:42:26 UTC is ef085ce76be4512da71a58e65ef4feb25d156206; aggregate counters are 0 unsettled / 0 failed / 6 reaped / 2024 total, health score 78 with 2 critical / 23 warning / 15 info, and the indicator incident remains unrecovered. This is an observation, not an automatically approved rollback decision.

## Latest readiness evidence — 2026-10-21 04:23 UTC

The direct production audit at 04:21:28 UTC reported build `ef085ce76be4512da71a58e65ef4feb25d156206`; health 78/degraded with 3 criticals including global SPCX kill switch, stale SETUPS session, and six underfilled 0700 runs; `indicator_engine` unrecovered and orchestrator false. This is a historical snapshot superseded by the 12:49 audit in [CURRENT_STATUS.md](CURRENT_STATUS.md), which confirms the same build and two remaining criticals. The Oct 21 log now directly confirms NaN at `pivots_weekly.pp`; the fix remains undeployed.

PR #1889 SHA `7c187363191ade3c574c7a77bde8e0b3885ff370` is pushed. Local validation was 82 passed / 3 skipped, coverage `NEW=0`, `py_compile`, diff checks, and full-tree secret scan passed. Exact-head hosted CI restarted with no results yet. This is insufficient for release. Await exact CI, confirm isolated PostgreSQL coverage, and observe the next scheduled production cron result without manually launching the live writer. No production readiness claim is made.
# Release hold update — 2026-10-22 14:37 UTC

Do not promote the current candidate. The last full profile ended with one stale policy-digest gate failure on its tested SHA; current main fixes the expected pin, and the integrated candidate at `4f50ae9b` still needs a full profile after documentation is committed. Production metadata timed out on the latest check, while the previous successful health snapshot was unhealthy. The active canonical grant names PR #1915, not this branch. Require a fresh live-health snapshot, exact-SHA full profile and hosted checks, matching guard scope, documented rollback target, and database-backed lock validation before considering deployment. Keep C3 disabled.
