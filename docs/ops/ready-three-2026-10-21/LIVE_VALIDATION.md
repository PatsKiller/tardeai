# Live validation — 2026-10-21

**Current evidence status (2026-10-21 04:43 UTC):** Direct GET at 04:38:41 UTC confirms production remains on `ef085ce76be4512da71a58e65ef4feb25d156206` (`main`), health 78/degraded and `healthy=false`, with 3 criticals, 23 warnings, and 26 actionable findings. The indicator lane remains unrecovered; neither PR is deployed. Communications is reachable in CANARY but does not prove ready-three behavior. Full evidence and limits are in [CURRENT_STATUS.md](CURRENT_STATUS.md).
**Historical observation below:** 2026-10-21 03:42:26 UTC; see the timestamped 03:52 audit and latest-evidence addendum for later observations.

## Current observed production state

Observation time: 2026-10-21 03:42:26 UTC (coordinator-reported live recheck).

- /v3/build-meta.json identified the active served build as ef085ce76be4512da71a58e65ef4feb25d156206, label main-exact-phase2, built 2026-10-21T03:21:22.888Z.
- This identity is the #1888/main release. It is not candidate 641e3a23c7eb1fea6df2615450657af02415949a.
- GET /api/v2/communications/deliveries/summary returned OK with unsettled=0, failed=0, reaped_unclaimed=6, total=2024 in the live recheck at 03:42:26 UTC.
- The aggregate response does not contain the ready-three schema, coverage/window, or clock fields. Its successful status therefore does not prove ready-three is live.
- Six core services were observed active/running: portfolio-server, coordination-gateway, run-relay, run-executor, governed-bridge, and health-agent. tradeai-phone-status.service was inactive/dead with Result=success. Service working directories resolved to current or exact release paths in the reviewed snapshot.
- The health endpoint at 03:42:26 UTC remained degraded, score 78, 2 critical / 23 warning / 15 info (40 findings). The same two critical incidents remain; the indicator incident is still unrecovered. This remains an environment-level readiness concern, not a proven regression from ready-three.

No ready-three deployment, post-deployment endpoint check, or authenticated full-page UAT is evidenced. No success claim for ready-three production behavior is authorized by these observations.

PR #1887 is OPEN / CLEAN (mergeable) at exact candidate head 641e3a23; it has not been merged or deployed. Passing CI checks do not change the production identity above. The only applicable release authority is exact-SHA-specific; no deployment grant/lease or post-deployment proof is present.

## Required post-deployment evidence record

After a separately authorized release, append a new dated record with:

1. UTC timestamp and release CURRENT symlink target.
2. /v3/build-meta.json identity and hash of the captured response.
3. State and process working directory for all six core units and any relevant auxiliary unit.
4. Communications endpoint HTTP status, schema/version, complete counters (especially failed and reaped_unclaimed separately), as_of timestamp, and host clock comparison.
5. Health score/severity counts before and after, with incident deltas and no suppression of preexisting degraded state.
6. Browser/UAT scope, authentication boundary, and exact pages/behaviors exercised.
7. Rollback target and the actual rollback/forward verification results if invoked.

Preserve sanitized raw outputs with hashes in a durable evidence bundle. Do not treat a dashboard strip, a successful aggregate endpoint, or a service-active state alone as production acceptance.


## Fresh production audit — 2026-10-21 03:52 UTC

- Served production remains `ef085ce76be4512da71a58e65ef4feb25d156206` (#1888/main); neither candidate is deployed.
- Health remains degraded at 78/100 with the same criticals: SPCX kill-switch containment and six underfilled screener runs. The indicator incident remains unrecovered.
- Communications endpoint audit reports database reachable, `CANARY`, `delivery_owned` operations, phase 7. The endpoint still does not expose ready-three schema or coverage/window/clock fields.
- The aggregate counters 0 unsettled / 0 failed / 6 reaped / 2024 total belong only to the earlier 03:42 snapshot; no newer aggregate counts are asserted here.
- No merge or deployment occurred. This is a fresh audit of production state, not proof that either candidate is live.

## Latest available production evidence — 2026-10-21 03:56 UTC (historical at report time)

- The last verified live snapshot available for this update is timestamped 03:56 UTC. Served production remains `ef085ce76be4512da71a58e65ef4feb25d156206` (#1888/main).
- Health is degraded at 78/100; `indicator_engine` remains unrecovered. The remediation probe reported `EFFECT_NOT_OBSERVED`, `unrecovered_keys:["indicator_engine"]`, `orchestrator_process_alive:false`, and `root_cause=unknown`. These generic probe fields do not establish that the indicator cron writer failed: the active writer is the weekday 08:00 `scripts/indicator_engine.py --universe` cron lane, while n8n remains shadow/dry-run.
- This evidence is historical and was not freshly collected at the 04:09 UTC documentation update. No claim is made that either PR is deployed, that production has recovered, or that the current release is healthy.

## Fresh production probe — 2026-10-21 04:10 UTC

- `CURRENT`/`BUILD_SHA` remains `ef085ce76be4512da71a58e65ef4feb25d156206` on `main`; neither candidate is deployed.
- Health captured at 04:09 UTC is 78/degraded, `healthy=false`, with 3 criticals and 23 warnings. SPCX kill switch remains active. The 04:08:34 UTC remediation probe returned `EFFECT_NOT_OBSERVED`, with `indicator_engine` unrecovered.
- The indicator log mtime is Oct 20 08:00 ET. The last recorded run was Oct 19 12:00 UTC: 26 attempted, 1 upserted, 25 skipped for `no_ohlcv`. The current day's weekday 08:00 ET cron was not yet due at the probe time. Historic NaN errors establish an earlier failure mode only; they do not prove the present incident's root cause.
- Communications health at about 04:10 UTC reports the database reachable, `CANARY`, owned operations, phase 7. This endpoint does not establish ready-three behavior or deployment.
- This is a fresh observation at the stated times. Continue treating production as degraded and the indicator incident as open; do not infer candidate readiness or causality from the older NaN logs.

## Candidate status update — 2026-10-21 04:23 UTC

PR #1889 exact head `7c187363191ade3c574c7a77bde8e0b3885ff370` was pushed around 04:22 UTC. Hosted checks restarted and no results were available at this update. Local validation (82 passed / 3 skipped, coverage `NEW=0`, `py_compile`, diff checks, full-tree secret scan) is not production verification. The direct live evidence at 04:21:28 UTC confirms the old build remains active and degraded. Historical NaN traceback does not prove the current incident's root cause. No candidate is claimed as live or production-ready.
