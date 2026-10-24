# Ready-three evidence and readiness — 2026-10-21

## Current integration and release state — 2026-10-22 20:08 UTC

Implementation SHA `88fbafcc27b58b4ea1c78f5e78fcfa9059a5d170` integrates `origin/main` `b9804fa577e6d2793f4539c7458452707a350f61` with the ready-three hardening. The FW-P5 fix is present. Focused suites passed 104 self-heal, 80 security/reaper/flock/pipeline, and 49 workflow tests. The incoming positions-reader suite has 111 passes and one intentional release blocker: its desk-truth monitor directly reads positions-store fields beyond the only approved Watch reader grant. No reader grant or exemption was added. This SHA has no full-profile qualification, hosted CI, or deployment evidence. Latest supplied production observation is 15:45Z and remains degraded (3 criticals); refresh before any decision. Keep release on HOLD and C3 disabled. See [current status](CURRENT_STATUS.md), [test results](TEST_RESULTS.md), [live validation](LIVE_VALIDATION.md), and [the hardening packet](../packets/n8n-platform-hardening-20261022/README.md).

---

## Current live state — 2026-10-22 07:37 UTC

Production SHA `4104effb…` remains unhealthy/degraded (78; 6 critical, 24 warnings, 30 actionable). Criticals include pipeline failures, the global SPCX kill switch, stale SETUPS business date, six underfilled 0700 runs, and backup count/size limit violations. Candidate code SHA `1cba3e8…` passed the full profile with exit 0 in 2,628 seconds; CI self-guards, reaper, docs-index, and manifest gates passed. The final docs-only reconciliation is committed as `91db443…` and passed docs-index 7/7, inventory/index, coverage audit, and diff checks; it does not change the code SHA qualified by the full profile. Schedule/freshness RCA has not identified an authoritative active producer schedule. `bin/guard show` at 07:37 reports no active grant. GitHub PR and Actions queries for this branch returned empty; remote branch presence is unverified. No deployment occurred. See [current status](CURRENT_STATUS.md), [test results](TEST_RESULTS.md), and [live validation](LIVE_VALIDATION.md).

## Corrected branch status — 2026-10-22 04:29 UTC

Correction branch `4112946f` reportedly passes 42 targeted tests, but its full profile is pending. The combined `1a1825ba…` full profile failed one stale lock assertion; the earlier `ca8b3658…` pass does not qualify corrected code. No push, PR, hosted CI, or deployment. See [current status](CURRENT_STATUS.md).

## Latest full-profile result — 2026-10-22 04:28 UTC

Combined SHA `1a1825ba…` failed after 2,638s with one stale PIDFILE-only assertion in `N8N_RUN_ROUTE`; all other gates and manifest/index checks passed. Separate correction `0534a85b…` reports targeted 21/21, but corrected final SHA needs its own full profile. Earlier `ca8b3658…` pass does not qualify it. No push, PR, hosted checks, or deployment. See [test results](TEST_RESULTS.md).

## Current qualification and release-process note — 2026-10-22 03:45 UTC

Candidate `ca8b3658…` passed its full profile; final combined SHA `1a1825ba…` remains in nonterminal run 4345 with a stale PIDFILE-only lock assertion. Separate correction commit `0534a85b…` reports 21 targeted tests passing but is not in the running SHA. The feature-to-live runbook is updated for current interactive approval, separate grants, and three-workflow exact-SHA checks; a preflight parity gap is explicitly documented. See [test results](TEST_RESULTS.md) and the [runbook](../FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md).

## Qualification update — 2026-10-22 03:44 UTC

Candidate `ca8b3658…` has a terminal full-profile PASS (manifest hash `6b03deb2…`; exact duration unavailable, ~3,075s estimated). Current combined SHA is `1a1825ba…`, adding fixes plus `origin/main` `63d37108`; its new full profile is running. Prior pass does not qualify this new SHA. Targeted blocker-fix tests reportedly passed 24; no push, PR, hosted checks or deployment. See [current status](CURRENT_STATUS.md) and [test results](TEST_RESULTS.md).

## Current checkpoint — 2026-10-22 03:20 UTC

Production is `4104effb…`, health 78/degraded/unhealthy (3 critical, 23 warnings). Candidate `ca8b3658…` is local, has no PR/hosted checks, and is 5 commits behind `origin/main`; its full profile is still running (overnight maturity passed 2,143/2 skipped; `maturity_score_stale` next). Guard `de5824f7` covers Release 2 / PR #1910 only. See [current status](CURRENT_STATUS.md).

## Fresh production state — 2026-10-22 03:04 UTC

Production reports main `4104effb99f3ced9e13ed63afc53c5e5fc7aa8c5`; health remains 78/degraded/unhealthy (3 critical, 24 warnings). Guard `de5824f7` covers Release 2 / PR #1910 on main and not candidate `ca8b3658`. The merged candidate's full profile is active; the earlier pass was pre-merge only. See [current status](CURRENT_STATUS.md) and [live validation](LIVE_VALIDATION.md).

## Current candidate entry point — 2026-10-22 02:59 UTC

Current candidate is `ca8b3658e4dcde8334932296f647b9da42b66587` after a clean merge of current `origin/main`. The 556/556 local full-profile pass recorded below is only for pre-merge SHA `252072a7…`; the new candidate's full-profile result is pending. Production remains on its separate pin, with no deployment. See [current status](CURRENT_STATUS.md) and [test results](TEST_RESULTS.md).

## Pre-merge candidate entry point — 2026-10-22 02:58 UTC

Integrated exact candidate `252072a7b942ab03994912b7a82f503457724a31` passed the second full profile (556/556, exit 0, 3,075s). This does not establish hosted CI, isolated PostgreSQL/production-schema behavior, or production readiness. Candidate manifest `5ca8f9…` (`release_candidate`) differs from production pin `aa037b…`; no deployment occurred. Production hold remains pending operational recovery, live validation, and candidate-specific release authority. See [test results](TEST_RESULTS.md), [deployment gates](DEPLOYMENT_AND_ROLLBACK.md), and [current status](CURRENT_STATUS.md).

## Current entry point — 2026-10-22 00:25 UTC

Current remote main `d55da84d` includes merged #1887 and the #1909 JSON cleanup; its 556-gate full profile passed. Production serves d55, but health remains degraded/unhealthy (60 failures vs 61 unrecovered detail) and release is **not ready**. The 20-minute process-reaper cap is proven to SIGTERM many orchestrator runs; do not raise it until all-run duration and single-flight risks are measured. Unauthenticated communications health still returns HTTP 200 under report-only auth; caller coverage is incomplete. Candidate c2 full profile was interrupted and is being rerun. A separate diagnostics-root candidate passed 10 focused tests, but is not integrated/hosted/deployed. No production config was changed. See [current status](CURRENT_STATUS.md), [full execution review](EXECUTION_REVIEW_2026-10-21.md), [live validation](LIVE_VALIDATION.md), and [test results](TEST_RESULTS.md). Older candidate/PR descriptions below are historical and are superseded by these records.

**Superseding status — 2026-10-21 19:13 UTC:** Production serves `a6ac0eb`; health at 19:07:50Z is 78/degraded and unhealthy (4 critical, 25 warning, 14 info, 43 total, 29 actionable). At 19:12:21Z, an unauthenticated request to the local communications summary listener returned HTTP 200 with real aggregate data; this is a **High priority confirmed local-listener exposure**. External exposure is unverified. Hold the production auth flip pending caller/lockout review. Final candidates remain local, without hosted exact-SHA CI. See [CURRENT_STATUS.md](CURRENT_STATUS.md).

**Exact-main local candidate evidence:** Final #1887 SHA `e24193bbec8ba24df3e3d3edecef972b1cc869be` adds auth integration tests to `0926a2e`; 385 tests across 14 changed modules pass (56.16s), auth/comms subset passes 180, `npm run build` passes, and docs inventory/index tests pass 7/7. #1889 SHA `66f5b692a9010bbdbcd66f3ba640e6fb6f968a18` passes four focused suites 42/42 with isolated JSONB validation and docs test 7/7. The merges include upstream docs-index/N8N documentation changes only and had no source-code conflict. Hosted exact-SHA CI is absent. Runtime auth configuration and live endpoint behavior remain unverified.

**Pipeline reliability candidate:** Exact-main watchdog candidate `ebe997d37572dd9ddca0776b836c46f2b027d982` passes 51 focused tests plus Ruff, compile, diff, and secret checks. It corrects direct-child outcome accounting only; forked descendants, a durable worker, and the 20-minute orchestrator cap remain unresolved. It is local and unhosted.

**Historical status at 15:40 UTC (superseded above):** See [CURRENT_STATUS.md](CURRENT_STATUS.md) for latest evidence. This timestamped snapshot is retained for history only.
**Updated:** 2026-10-21 18:54 UTC
**Scope:** Communications ready-three candidate, currently deployed #1888 baseline, and related C3 readiness.
Historical 03:45 status is superseded by the current status above and [CURRENT_STATUS.md](CURRENT_STATUS.md). Neither PR is merged or deployed; production remains degraded on `ef085ce76be4512da71a58e65ef4feb25d156206`.

## Historical state that was proven — 03:45 UTC (superseded by current update below)

| Item | Verified state | Evidence boundary |
|---|---|---|
| Current production identity | #1888/main ef085ce76be4512da71a58e65ef4feb25d156206, label main-exact-phase2; build metadata reported built at 2026-10-21T03:21:22.888Z. | Safe GET /v3/build-meta.json; this is not ready-three. |
| Live communications summary | /api/v2/communications/deliveries/summary returned OK, unsettled=0, failed=0, reaped_unclaimed=6, total=2024 in the live recheck at 03:42:26 UTC. | Aggregate endpoint only. It does not expose ready-three schema, coverage/window, or clock fields. |
| Candidate | Integration merge 641e3a23c7eb1fea6df2615450657af02415949a, parents ee7bd4f7a717007b377e95fcfe511a1353bb37ef and ef085ce76be4512da71a58e65ef4feb25d156206; pushed as PR #1887 head. | Focused local tests/build, static review, and exact-head hosted CI. See the CI table. |
| Indicator JSON NaN remediation | Separate branch fix/indicator-json-nonfinite-20261021 at latest commit 0b5ff40692b739bd6135c4776eae11e8dcab2ae0 (parent 3828695f), pushed as PR #1889. | Author suite 45/45 in 11.31s; independent review 9/9, including np.longdouble('1e4000') preservation and NaN/Infinity to null; Ruff, format, py_compile, diff, and secret scan passed. No database/runtime integration has run locally; exact-head hosted CI is running, including an isolated PostgreSQL shard (pending). No host DB was accessed. Not part of PR #1887 and not deployed. |
| Production health | Degraded, score 78, 2 critical / 23 warning / 15 info (health snapshot at 03:42:26 UTC). | Not a ready-three regression determination. Keep open incidents visible. |
| C3 | Clean public v1 due remains held; separate dirty worktree can reach spawn for a qualifying requested ledger row. Child business writes still refuse and private protocol is unwired. | Not deployed; no activation by this review. Actual live workflow/DB state unverified. Do not publish pending provenance enforcement, end-to-end authority protocol and denial tests. |

PR #1887 is [OPEN](https://github.com/PatsKiller/tardeai/pull/1887), exact head 641e3a23, merge state CLEAN/mergeable (parent-observed at 03:42 UTC). All required and all non-skipped hosted checks for PR #1887 passed, including cio-hardening (10m56s), all 8 parallel shards, PG and serial shards, integrity rails, aggregate ci-gate, options lifecycle/backend/frontend, agent governance, AIF integration, focused Playwright, provider-cost, and release readiness. cio-hardening-full and main-red-alert were skipped by PR-event rules. Separately, PR #1889 is OPEN at exact SHA 0b5ff406; hosted exact-head checks including the PG shard are running, with results pending. Run links and detail are in [Test results](TEST_RESULTS.md). These checks validate pushed SHA 641 only; this local documentation amendment is not included in it. Neither PR is merged or deployed; no post-deployment verification is evidenced. Deployment authority remains exact-SHA-specific and no deployment lease/grant is present.

## Open issues recorded at 03:45 UTC (reassessed below)

1. The health critical for the SPCX kill switch is an active containment state since 2026-10-14. The incident record says contained, not resolved. Preserve the switch; resolution criteria remain outstanding.
2. The 0700 screener had six retries within the 2026-10-20 scheduled morning, each with 15–16 symbols against a configured floor of 20 and reason UNIVERSE_TOO_SMALL. Source-screen yields were not retained in the evidence reviewed. Do not lower the floor to silence the alert; inspect source yields and confirm whether the alert counts retries or distinct windows.
3. indicator_engine failed at 08:00 ET on 2026-10-20 after PostgreSQL rejected JSON containing NaN. Separate remediation commit 0b5ff406 strict-normalizes non-finite values to null in both indicator DB JSON writers and is pushed as PR #1889. Author tests 45/45, independent review 9/9, and static checks passed; hosted exact-head CI, including an isolated PostgreSQL shard, is running. No host DB was accessed, no merge/deployment occurred, and this is not part of ready-three PR #1887. No live rerun/write was performed; do not describe the production defect as resolved.
4. Listener sockets were observed on wildcard addresses (22, 18789, 18798, 9090, 11434, 3389) and tailnet-bound addresses (443, 5678, 8443, 52821). Socket binding alone does not establish external reachability; firewall inspection was unavailable, so exposure is **unverified**, not a confirmed vulnerability.
5. Full native hardening on candidate 641e3a23 was stopped incomplete. It encountered hermetic-guard denials for host environment/state paths, socket/multiprocessing EPERM, missing Ruff/ShellCheck, independent assertion failures that have not all been root-caused, and a DB-backed lane that stalled. This is not a pass; unrelated assertion causes remain unclassified.

## Read this dossier

- [Executive gap and readiness report](EXECUTIVE_REPORT.md)
- [Test results and evidence limits](TEST_RESULTS.md)
- [Current production observation](LIVE_VALIDATION.md)
- [Change and release tracking](CHANGELOG.md)
- [Deployment and rollback gates](DEPLOYMENT_AND_ROLLBACK.md)
- [System and service inventory](SYSTEM_INVENTORY.md)
- [Agent handoff and remaining work](AGENT_HANDOFF.md)

This dated dossier supplements historical material. It does not certify production readiness or replace exact-SHA hosted checks, deployment authorization, or live validation.


## Follow-up evidence — indicator coverage failure (2026-10-21 03:47 UTC)

The exact-head hosted run for PR #1889, run [39540242917](https://github.com/PatsKiller/tardeai/actions/runs/39540242917), was still in progress at the latest coordinator observation. Its integrity-rails job failed and the isolated PostgreSQL shard passed. Root-cause review confirmed the coverage failure came from a newly added test that was absent from `GATES`; inherited unlisted baseline 921 is unchanged. A local correction was committed as `8d14cb07f1b161ad2509a34e7d7d8e98ce6b49bf`, adding coverage guard `NEW=0`; targeted result: 7 passed, 2 skipped. At the time of this first follow-up observation, the correction was not yet pushed and was pending the exact guard; this status was superseded at 03:47:45 UTC below. PR #1889 then still pointed to prior SHA `0b5ff40692b739bd6135c4776eae11e8dcab2ae0`; do not attribute the local correction or tests to that prior hosted run. No merge/deployment or production change occurred. Latest known live snapshot remains the 03:42:26 UTC observation in [live validation](LIVE_VALIDATION.md); it is pending a fresh agent audit.


### Superseding update — 2026-10-21 03:47:45 UTC

The exact push grant was activated/consumed and fix `8d14cb07f1b161ad2509a34e7d7d8e98ce6b49bf` is now pushed as PR #1889 head. Hosted CI restarted against this exact SHA at 03:47:45 UTC and is pending. The preceding coverage failure RCA and local 7-pass/2-skip verification remain valid; those checks are not hosted results. PR #1889 is not merged or deployed. PR #1887 remains green at its recorded exact head; these documentation edits remain local in its worktree. No production change; latest live evidence is still the 03:42:26 snapshot pending a fresh audit.

## Historical status and remaining gaps — 2026-10-21 04:23 UTC

- PR #1887 is at `e5ebdc656b9d26d9b58bb77c14d22611d7584b2b`; active hosted checks passed, with `cio-hardening-full` and `main-red-alert` skipped.
- PR #1889 is at pushed SHA `7c187363191ade3c574c7a77bde8e0b3885ff370` (around 04:22 UTC). Exact-head CI restarted; no results yet. Local validation: 82 passed / 3 skipped, coverage `NEW=0`, `py_compile`, diff checks, full-tree secret scan passed. These are local checks, not hosted CI.
- Scope now includes strict normalization across all four known cache writers, cached/fresh/batch API responses, and signal-history values/details on the covered API path. A distinct raw `indicator_signal_history.details` writer remains unverified for schema and current use; inspect before deciding on further remediation.
- Production was directly audited at 04:21:28 UTC: `CURRENT` remains `ef085ce76be4512da71a58e65ef4feb25d156206`; health 78/degraded with 3 criticals including the global SPCX kill switch, stale SETUPS session, and six underfilled 0700 runs. `indicator_engine` remains unrecovered and orchestrator false. Historic NaN traceback is not evidence of the current root cause.
- The weekday 08:00 ET indicator cron had not fired at the 04:10 UTC check; await the natural scheduled run and inspect receipt/log/output. Do not invoke the live writer manually for qualification. Production is not ready and no candidate is live.
