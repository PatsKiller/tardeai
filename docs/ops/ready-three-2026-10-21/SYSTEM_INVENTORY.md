# System inventory snapshot — 2026-10-21

**Status:** Coordinator-reported live recheck at 03:42:26 UTC; production remains on #1888 and candidate is not deployed.
**Updated:** 2026-10-21 03:45 UTC

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
