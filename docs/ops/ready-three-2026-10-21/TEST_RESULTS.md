# Test results — 2026-10-21

**Status:** PR #1887 required/non-skipped checks passed. PR #1889 run 39540242917 has an integrity-rails failure and isolated PG pass; other jobs remain in progress. PR-event skips are listed separately.
**Updated:** 2026-10-21 03:48 UTC
**Candidate SHA:** 641e3a23c7eb1fea6df2615450657af02415949a (pushed PR #1887 head).

## Completed checks

| Lane | Command / result | Scope |
|---|---|---|
| Communications backend focused tests | /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python -m pytest -q tests/test_comms_delivery_health_truth_20261020.py tests/test_comms_stuck_deliveries_20261020.py — **31 passed** (1.68s). | Exact local candidate; focused delivery health and stuck-delivery behavior. |
| Frontend projection tests | /home/johnclaw/.nvm/versions/node/v22.23.2/bin/node --experimental-strip-types apps/command-center-v3/src/lib/commsDeliveryHealth.test.ts — **21 passed, 0 failed**. | Exact local candidate; projection logic only. |
| Frontend build and guards | npm run build in apps/command-center-v3 — passed. Design/UI guard, contrast **141/141**, frontend suite, TypeScript check, Vite build (1,475 modules) completed. | Candidate build. Warnings: /v3/cc-boot.js not bundled without type=module; main JS chunk about 4.94 MB exceeds 500 KB advisory. |
| Existing Communications Hub suite | tests/test_comms_hub_20261007.py — **32/32 passed** in the project-native profile. | Candidate environment; broader Communications Hub contract suite. |
| Diff whitespace | git diff --check HEAD^1..HEAD — passed. | Candidate change set. |
| Independent reconciliation review | Approved static review; artifact /tmp/n8n-campaign-20261018/ready-three-reconcile-641e3a23c-independent-review-20261021.json. | Static review only; not hosted or runtime production evidence. |

## Hosted CI for pushed exact head

PR #1887 status was directly observed by the coordinating agent at approximately 03:42 UTC: OPEN, exact head 641e3a23, mergeState CLEAN/mergeable; all required/non-skipped checks passed. At approximately 03:45 UTC, PR #1889 was OPEN at exact head 0b5ff406 and hosted checks, including the isolated PG shard, were running. This documentation worker could not query the GitHub API; these are timestamped coordinator observations, not live polling.

| Workflow / checks | Status | Run |
|---|---|---|
| Options lifecycle (backend/frontend) | Passed | [Run 39539021817](https://github.com/PatsKiller/tardeai/actions/runs/39539021817) |
| Agent governance | Passed | [Run 39539021818](https://github.com/PatsKiller/tardeai/actions/runs/39539021818) |
| Release readiness | Passed | [Run 39539021829](https://github.com/PatsKiller/tardeai/actions/runs/39539021829) |
| Provider cost | Passed | [Run 39539021809](https://github.com/PatsKiller/tardeai/actions/runs/39539021809) |
| Integrity rails; all 8 parallel shards, PG shard, serial shard | Passed | [Run 39539021759](https://github.com/PatsKiller/tardeai/actions/runs/39539021759) |
| Focused Playwright | Passed (2m 1s) | [Run 39539021826](https://github.com/PatsKiller/tardeai/actions/runs/39539021826) |
| AIF integration | Passed | [Run 39539021823](https://github.com/PatsKiller/tardeai/actions/runs/39539021823) |
| Aggregate ci-gate | Passed | [Run 39539021759](https://github.com/PatsKiller/tardeai/actions/runs/39539021759) |
| cio-hardening | Passed (10m56s) | [Run 39539021822](https://github.com/PatsKiller/tardeai/actions/runs/39539021822) |
| cio-hardening-full | Skipped by PR-event condition | [Run 39539021822](https://github.com/PatsKiller/tardeai/actions/runs/39539021822) |
| main-red-alert | Skipped by PR-event rules | PR #1887 checks (no separate run URL supplied) |

All required and all non-skipped hosted checks passed for exact SHA 641, including cio-hardening (10m56s); the aggregate ci-gate passed. PR #1887 is OPEN / CLEAN (mergeable). cio-hardening-full and main-red-alert were skipped by PR-event rules and are not reported as passes. No merge or deployment has occurred. These CI results apply only to pushed SHA 641, not this local documentation update or PR #1889.

## Separate indicator JSON remediation branch

This is a distinct workstream on a separate PR and is not part of ready-three PR #1887. As of 03:45 UTC, PR #1889 is OPEN at exact head 0b5ff40692b739bd6135c4776eae11e8dcab2ae0; hosted exact-head checks are running, including an isolated PostgreSQL shard (pending). The coordinating agent reports branch fix/indicator-json-nonfinite-20261021 at latest commit 0b5ff40692b739bd6135c4776eae11e8dcab2ae0 (parent 3828695f). Both indicator database JSON writers now strict-normalize non-finite values to null.

- 45 related tests passed in 11.31 seconds. Coverage includes the new regression, lane repair, data plausibility, finite Fraction, NumPy int64/longdouble, high-precision Decimal legacy serialization, and non-finite values normalized to strict JSON null.
- Ruff, formatting, py_compile, diff check, and secret scan passed.
- Independent review approved the latest commit with 9/9 checks, including preserving np.longdouble('1e4000'), normalizing longdouble NaN/Infinity to null, and Fraction/NumPy legacy serialization.
- No local PostgreSQL integration was run because no isolated database was available; no host DB or production runtime was accessed. Hosted exact-head CI now includes an isolated PG shard, which is running with results pending.
- PR #1889 is open and pushed; hosted CI is in progress. No merge or deployment has occurred.

These are coordinator-reported local test/review results; exact logs/commands were not supplied in this documentation task. The commit is pushed at PR #1889, with hosted checks pending. Treat it as locally validated, not production-qualified.

## Incomplete or not run

- **Full native hardening:** scripts/run_cio_hardening_ci.py --profile full on candidate 641e3a23 was interrupted with exit 130 after environment/toolchain failures, unresolved assertions, and a stalled DB-backed lane. Do not classify as pass or a clean fail. Failure details and limitations are summarized in the dated readiness dossier.
- **Exact-head hosted CI:** all required and non-skipped checks passed as listed above. Checks on old PR head ee7bd4f do not qualify this merge commit.
- **Integration against the deployed release:** not run for ready-three. Production still identifies as ef085ce76be4512da71a58e65ef4feb25d156206.
- **Authenticated browser UAT:** the focused Playwright workflow passed (run 39539021826), but full-page authenticated UAT was not performed. This result does not establish broader authenticated user behavior.
- **Performance, soak, failover, and recovery:** not run for the candidate.
- **Security validation:** source/config review and listener observation only. Firewall/external exposure validation and a complete exact-candidate security suite remain unverified.
- **Post-deployment regression:** not applicable until an authorized release exists.

## Required validation before calling the candidate qualified

1. If candidate source changes, run exact-SHA hosted CI for the new pushed SHA through the canonical guard.
2. Root-cause each independent hardening assertion and rerun the DB-backed lane in the supported environment.
3. Perform integration/regression testing, targeted performance/soak and failover checks against a controlled release candidate.
4. After any authorized deployment, capture release identity, services/process working directories, complete response schema and counters, clocks/as-of values, health deltas, and appropriately scoped browser/UAT evidence.


## Follow-up: PR #1889 coverage integrity-rails failure (2026-10-21 03:47 UTC)

- Hosted run [39540242917](https://github.com/PatsKiller/tardeai/actions/runs/39540242917) is still in progress as reported by the coordinating agent. On prior PR head `0b5ff40692b739bd6135c4776eae11e8dcab2ae0`, the integrity-rails job failed; the isolated PostgreSQL shard passed. Other run jobs remain unsettled unless their status is separately reported.
- Root cause confirmed: a newly added test was absent from `GATES`, causing coverage integrity validation to fail. The inherited unlisted baseline 921 is unchanged.
- At this first follow-up observation, local remediation commit `8d14cb07f1b161ad2509a34e7d7d8e98ce6b49bf` added coverage guard `NEW=0`; focused verification reported 7 passed, 2 skipped. It was not yet pushed and awaited exact guard validation; this status was superseded at 03:47:45 UTC below.
- The hosted result belongs to SHA `0b5ff406…`; it does not validate local commit `8d14cb07…`. No new push, merge, deployment, or production change is evidenced. No host DB was accessed.
- The production snapshot remains the 03:42:26 UTC observation recorded in [live validation](LIVE_VALIDATION.md), pending fresh agent audit; do not describe it as freshly re-polled.


### Superseding hosted status — 2026-10-21 03:47:45 UTC

The exact push grant was activated/consumed; commit `8d14cb07f1b161ad2509a34e7d7d8e98ce6b49bf` is now pushed as PR #1889 exact head. Hosted CI restarted for that SHA at 03:47:45 UTC; results are pending. The earlier run 39540242917 applies to prior SHA `0b5ff406…` and its integrity-rails coverage failure / PG-shard pass are retained as RCA evidence. Local focused tests for the correction were 7 passed, 2 skipped; hosted CI has not yet validated this commit. PR #1889 remains unmerged/undeployed. PR #1887 remains green at its recorded exact head; this dossier is local and not part of PR #1887.
