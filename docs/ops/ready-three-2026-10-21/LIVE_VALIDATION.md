# Live validation — 2026-10-21

**Status:** Production was rechecked at 2026-10-21 03:42:26 UTC; candidate remains undeployed.
**Updated:** 2026-10-21 03:45 UTC

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
