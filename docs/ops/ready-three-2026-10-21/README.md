# Ready-three evidence and readiness — 2026-10-21

**Current status (2026-10-21 04:35 UTC):** See [CURRENT_STATUS.md](CURRENT_STATUS.md) for the latest exact-head CI matrix and direct production evidence. PR #1889 `7c187363…` has passed its integration shards, serial, PostgreSQL, aggregate gate, and other named checks; `cio-hardening` remains pending. PR #1887 docs head `a015331a…` has checks in progress. Production remains on `ef085ce76be4512da71a58e65ef4feb25d156206`, degraded and not production-ready. Neither candidate is live.
**Updated:** 2026-10-21 04:35 UTC
**Scope:** Communications ready-three candidate, currently deployed #1888 baseline, and related C3 readiness.
Historical 03:45 status superseded by the 04:23 addendum below: PR #1887 now has active checks passed with event skips; PR #1889 is at pushed SHA 7c187363191ade3c574c7a77bde8e0b3885ff370 with exact-head CI pending. Neither PR is merged or deployed; current production remains degraded on ef085ce76be4512da71a58e65ef4feb25d156206.

## Historical state that was proven — 03:45 UTC (superseded by current update below)

| Item | Verified state | Evidence boundary |
|---|---|---|
| Current production identity | #1888/main ef085ce76be4512da71a58e65ef4feb25d156206, label main-exact-phase2; build metadata reported built at 2026-10-21T03:21:22.888Z. | Safe GET /v3/build-meta.json; this is not ready-three. |
| Live communications summary | /api/v2/communications/deliveries/summary returned OK, unsettled=0, failed=0, reaped_unclaimed=6, total=2024 in the live recheck at 03:42:26 UTC. | Aggregate endpoint only. It does not expose ready-three schema, coverage/window, or clock fields. |
| Candidate | Integration merge 641e3a23c7eb1fea6df2615450657af02415949a, parents ee7bd4f7a717007b377e95fcfe511a1353bb37ef and ef085ce76be4512da71a58e65ef4feb25d156206; pushed as PR #1887 head. | Focused local tests/build, static review, and exact-head hosted CI. See the CI table. |
| Indicator JSON NaN remediation | Separate branch fix/indicator-json-nonfinite-20261021 at latest commit 0b5ff40692b739bd6135c4776eae11e8dcab2ae0 (parent 3828695f), pushed as PR #1889. | Author suite 45/45 in 11.31s; independent review 9/9, including np.longdouble('1e4000') preservation and NaN/Infinity to null; Ruff, format, py_compile, diff, and secret scan passed. No database/runtime integration has run locally; exact-head hosted CI is running, including an isolated PostgreSQL shard (pending). No host DB was accessed. Not part of PR #1887 and not deployed. |
| Production health | Degraded, score 78, 2 critical / 23 warning / 15 info (health snapshot at 03:42:26 UTC). | Not a ready-three regression determination. Keep open incidents visible. |
| C3 | v4 snapshot at 51bc97595582aa8ea0d6dcfd44fba6a848595e0e; C3 v5 runtime wiring is incomplete. Rows remain PAUSED/off; no live args. | Separate workstream and snapshot; no readiness claim for C3 activation. |

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

## Latest status and remaining gaps — 2026-10-21 04:23 UTC

- PR #1887 is at `e5ebdc656b9d26d9b58bb77c14d22611d7584b2b`; active hosted checks passed, with `cio-hardening-full` and `main-red-alert` skipped.
- PR #1889 is at pushed SHA `7c187363191ade3c574c7a77bde8e0b3885ff370` (around 04:22 UTC). Exact-head CI restarted; no results yet. Local validation: 82 passed / 3 skipped, coverage `NEW=0`, `py_compile`, diff checks, full-tree secret scan passed. These are local checks, not hosted CI.
- Scope now includes strict normalization across all four known cache writers, cached/fresh/batch API responses, and signal-history values/details on the covered API path. A distinct raw `indicator_signal_history.details` writer remains unverified for schema and current use; inspect before deciding on further remediation.
- Production was directly audited at 04:21:28 UTC: `CURRENT` remains `ef085ce76be4512da71a58e65ef4feb25d156206`; health 78/degraded with 3 criticals including the global SPCX kill switch, stale SETUPS session, and six underfilled 0700 runs. `indicator_engine` remains unrecovered and orchestrator false. Historic NaN traceback is not evidence of the current root cause.
- The weekday 08:00 ET indicator cron had not fired at the 04:10 UTC check; await the natural scheduled run and inspect receipt/log/output. Do not invoke the live writer manually for qualification. Production is not ready and no candidate is live.
