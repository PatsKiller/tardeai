# Test results — 2026-10-21

**Current status (2026-10-21 04:35 UTC):** Local 7c regression remains 82 passed / 3 skipped; coverage `NEW=0`, `py_compile`, diff checks, and full-tree secret scan passed. Docs index test passed 7/7. See [CURRENT_STATUS.md](CURRENT_STATUS.md) for exact hosted states: PR #1889 only `cio-hardening` remains pending; PR #1887 docs CI is still running. No deployment evidence.
**Updated:** 2026-10-21 04:35 UTC
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


## Exact-head hosted CI refresh — 2026-10-21 03:52 UTC

The following matrices are partial observations, not full passes. Results are coordinator-reported for the stated exact SHA; pending jobs remain pending. Full hardening was skipped for both PRs.

| PR / exact head | Passed at 03:52 UTC | Pending at 03:52 UTC | Skipped |
|---|---|---|---|
| PR #1887 / `e5ebdc6` | Governance, focused Playwright, options backend, provider cost, shard 6, PG shard, integrity rails | AIF integration, cio-hardening, release readiness, shards 0–5 and 7, serial shard | Full hardening |
| PR #1889 / `8d14cb0` | Governance, AIF integration, provider cost, release readiness, shards 3, 4, and 6, PG shard, integrity rails | cio-hardening, shards 0–2, 5, and 7, serial shard | Full hardening |

Neither matrix is complete; passing selected jobs does not mean the PR passed hosted CI. No merge or deployment is evidenced.

## Production audit boundary

The fresh 03:52 UTC audit confirms production build `ef085ce76be4512da71a58e65ef4feb25d156206`, degraded health 78/100 with the same SPCX kill-switch critical and six underfilled screener runs, and the indicator incident still unrecovered. The communications endpoint reports database reachable, `CANARY`, `delivery_owned` operations, phase 7, but does not expose ready-three, coverage/window, or clock fields. Aggregate counters 0/0/6/2024 are from 03:42 only; this refresh does not reuse them as current.

## Exact-head status refresh — 2026-10-21 04:09 UTC

| Workstream | Evidence | Qualification |
|---|---|---|
| PR #1887 `e5ebdc6` | Active hosted checks passed, including `cio-hardening`; `cio-hardening-full` and `main-red-alert` were skipped. | Hosted CI pass for this exact head, subject to the listed skips. Not a deployment or live test. |
| PR #1889 remote `8d14cb0` | Hosted checks passed. | Does not validate the later local candidate. |
| PR #1889 `acbb9944ce65d6edf00c7f8c80f8c47987819d35` | Pushed ~04:10 UTC; exact-head checks started. Integrity rails and provider-cost passed; other active jobs pending; `cio-hardening-full` skipped. | Validation is in progress; earlier `8d14cb0` checks do not qualify this SHA. |
| Production | Last evidence at 03:56 UTC: build `ef085ce76be4512da71a58e65ef4feb25d156206`, degraded health 78/100, indicator incident unrecovered. | Historical snapshot, not freshly probed at 04:09 UTC. No production verification of either PR. |

Earlier sections and addenda retain their original timestamps and describe the state at those times. They are not current where superseded above.

## PR #1889 exact-head CI update — 2026-10-21 04:11 UTC

The local candidate `acbb9944ce65d6edf00c7f8c80f8c47987819d35` was pushed to PR #1889 around 04:10 UTC. Exact-head checks have started; integrity rails and provider-cost passed, remaining active jobs are pending, and `cio-hardening-full` was skipped. The prior remote `8d14cb0` hosted pass does not validate this newer SHA. No merge/deployment is evidenced.

## Production verification refresh — 2026-10-21 04:10 UTC

The fresh probe confirms production remains on build `ef085ce76be4512da71a58e65ef4feb25d156206` (`main`). Health captured at 04:09 UTC is 78/degraded, `healthy=false`, with 3 criticals and 23 warnings; SPCX kill switch is active. The 04:08:34 UTC remediation probe was ineffective and `indicator_engine` remains unrecovered. Its last run (Oct 19 12:00 UTC) attempted 26, upserted 1, and skipped 25 for `no_ohlcv`; the weekday 08:00 ET cron for Oct 21 had not yet fired. Historic NaN log evidence is not proof of current causality. Communications health at ~04:10 reports DB reachable, `CANARY`, owned operations, phase 7. This does not validate either candidate or indicate production recovery.

## Local remediation and latest hosted status — 2026-10-21 04:18 UTC

| SHA / lane | Result | Qualification |
|---|---|---|
| #1889 remote `acbb9944ce65d6edf00c7f8c80f8c47987819d35` | At direct poll ~04:18 UTC: agent-governance, both AIF checks, ci-gate, integrity rails, provider-cost, release-readiness, shards 0–7, serial, and PG passed; `cio-hardening` pending; `cio-hardening-full` skipped. | Hosted state applies to remote acbb only. |
| Local `9a88c665fa314e79117fd8c6bf9d8716708138fc` | Broader regression: 81 passed, 3 skipped; custom coverage gate `NEW=0`; `py_compile` and diff checks clean; reviewed. | Local evidence only. Not pushed or hosted-validated because no active exact-SHA `git-push` grant is present in the repository guard. |

Follow-up: a separate raw `indicator_signal_history.details` JSON writer remains unqualified. Its column type, active usage, and need for strict normalization are unknown; inspect schema and writer activity before deciding whether to change it. Do not claim 9a88 CI or validation of that history writer.

## PR #1889 pushed head verification — 2026-10-21 04:19 UTC


## PR #1889 final code head — 2026-10-21 04:23 UTC

Commit `7c187363191ade3c574c7a77bde8e0b3885ff370` was pushed around 04:22 UTC. Exact-head hosted CI restarted and no result was available at this update. Local broader regression: 82 passed / 3 skipped; custom coverage `NEW=0`; `py_compile`, diff checks, and full-tree secret scan passed. These are local results, not hosted CI. The fix scope adds normalization for cached, fresh, and batch API responses and signal-history values/JSON alongside the four cache writers. No merge or deployment occurred.

Production audit refreshed at 04:21:28 UTC: `CURRENT` remains `ef085ce76be4512da71a58e65ef4feb25d156206`; health is 78/degraded with three criticals including global SPCX kill switch, stale SETUPS session, and six underfilled 0700 runs; indicator unrecovered and orchestrator false. Historic NaN traceback is not proof of the current incident's root cause.
