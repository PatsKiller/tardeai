# System inventory snapshot — 2026-10-21

**Status:** Base service inventory below remains the 03:42:26 UTC snapshot. Direct build metadata and health GETs at 04:33 UTC confirm #1888/ef085ce remains active and degraded. Current PR heads, CI, and explicit inventory limits are in [CURRENT_STATUS.md](CURRENT_STATUS.md). Service states, process paths, listeners, and full counters were not refreshed after 03:42.
**Updated:** 2026-10-21 04:35 UTC

## Release and service state observed

- Production release identity: #1888/main ef085ce76be4512da71a58e65ef4feb25d156206, label main-exact-phase2.
- Six core services observed active/running: portfolio-server, coordination-gateway, run-relay, run-executor, governed-bridge, health-agent.
- tradeai-phone-status.service: inactive/dead, Result=success.
- Reviewed service working directories resolved to the current release or exact release path.
- Communications summary: HTTP success; unsettled=0, failed=0, reaped_unclaimed=6, total=2024 in live recheck at 03:42:26 UTC.
- Overall health: degraded, score 78, 2 critical / 23 warning / 15 info (40 findings) at 03:42:26 UTC; the same two critical incidents persist and indicator remains unrecovered.

## Boundaries and unknowns

- This is a dated observation, not a complete inventory of all host processes, containers, jobs, credentials, network policy, or integrations.
- Wildcard listeners were observed on ports 22, 18789, 18798, 9090, 11434, 3389; tailnet-bound listeners on 443, 5678, 8443, 52821. Actual external reachability was not established because firewall inspection was unavailable.
- Do not infer that a listener is exposed solely from its bind address or infer it is protected without firewall evidence.
- The ready-three candidate is not the live release; PR #1887 is OPEN / CLEAN (mergeable), not merged/deployed. All required/non-skipped hosted checks passed for exact SHA 641. Deployment requires separate exact-SHA authority and deployment/production lease.
- C3 v4 evidence at 51bc97595582aa8ea0d6dcfd44fba6a848595e0e is separate; v5 runtime wiring is incomplete, and C3 rows stay PAUSED/off.

Refresh this inventory after any release or material configuration change, preserving timestamp, source commands, and sanitized raw evidence.

## Partial latest production observation — 2026-10-21 04:10 UTC

- `CURRENT` / `BUILD_SHA`: `ef085ce76be4512da71a58e65ef4feb25d156206` on `main`; neither PR candidate is deployed.
- Health captured at 04:09 UTC: 78/degraded, `healthy=false`, 3 criticals / 23 warnings; SPCX kill switch active; `indicator_engine` unrecovered.
- Remediation probe at 04:08:34 UTC was ineffective (`EFFECT_NOT_OBSERVED`, unrecovered key `indicator_engine`). This is a symptom/status result, not proof of current root cause. Historical NaN errors establish a prior failure mode only.
- Indicator cron evidence: last run Oct 19 12:00 UTC, 26 attempted / 1 upserted / 25 skipped (`no_ohlcv`); log mtime Oct 20 08:00 ET. The Oct 21 weekday 08:00 ET run had not occurred by the observation. Wait for the natural schedule and inspect receipt/logs; do not invoke the production writer solely for a test.
- Communications health around 04:10 UTC: DB reachable, `CANARY`, owned operations, phase 7. Complete counters/schema were not refreshed in this partial probe.
- Core unit states, working directories, network listeners, firewall state, and external reachability remain represented only by the earlier 03:42 snapshot and were not reverified here.
- PR #1889 was pushed at `9a88c665fa314e79117fd8c6bf9d8716708138fc`; exact hosted CI was restarted and AIF was queued at that observation. This inventory contains no evidence that the commit is deployed or production-ready.

## Latest candidate status — 2026-10-21 04:23 UTC

PR #1889's current exact head is `7c187363191ade3c574c7a77bde8e0b3885ff370`, pushed around 04:22 UTC. Its hosted checks restarted and had no results at this update. Local broad regression was 82 passed / 3 skipped; coverage `NEW=0`; `py_compile`, diff checks, and full-tree secret scan passed. Direct production audit at 04:21:28 UTC confirms build `ef085ce76be4512da71a58e65ef4feb25d156206`, health 78/degraded with 3 criticals (global SPCX kill switch, stale SETUPS session, six underfilled 0700 runs), indicator unrecovered and orchestrator false. No deployment is evidenced. Full service and network inventory has not been refreshed since the timestamped baseline above.
