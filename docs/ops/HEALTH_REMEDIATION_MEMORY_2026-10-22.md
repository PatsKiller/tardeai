# Health remediation route memory bound (2026-10-22)

```
Status:      ACTIVE (code on branch fix/health-remediation-memory-20261022; not deployed by this PR)
as_of:       2026-10-22T19:30:00-04:00
Measured at: served build ee38621b1 (read-only); before/after against a read-only copy of the live logs
```

## What happened

On 2026-10-22 the cron watchdog SIGKILLed portfolio-server 69 times after its cgroup memory went over
`MemoryHigh` 1.5G. The cause was `GET /api/v2/health/remediation`
(`scripts/api_v2.py` `_health_remediation`). On every call it ran `read_text().splitlines()` and
`json.loads` on every line of two append-only logs that are never rotated:

| File | Size | Lines |
|---|---|---|
| `persistent-state/data/runtime/health_inspector_fixes.jsonl` | 119 MB | 240,691 |
| `persistent-state/logs/health_agent_remediation.jsonl` | 55 MB | 63,108 |

It then built a dict for every line and sorted all of them, only to return the newest 50 rows and the
24-hour stats. Each call added 300–770 MB RSS and took 2–34 s. The HealthHub "log" tab
(`RemediationDashboard.tsx`) polled it every 60 s, and `_health_ops_autonomy` also calls it.

There was a second cost. `GET /api/v2/data-sources/finviz/credential-health` ran a live Finviz
export probe on every poll. Each probe could wait up to 30 s on the global throttle, take up to
15 s of HTTP, and then run a second token probe; 3,387 requests on 10-22 took more than 10 s. The site-wide
`FinvizCookieBanner` polls it every 60 s from every tab. The route also called
`sys.path.insert(0, ...)` unconditionally on every request.

## Fix

- **Tail read.** Each file is read backwards in windows of `_HEALTH_REMEDIATION_TAIL_BYTES`
  (8 MB; env `TRADEAI_HEALTH_REMEDIATION_TAIL_BYTES`), and a partial first line is carried into the
  next window. Reading stops once at least 50 rows are held and the window has crossed the 24 h
  boundary. If 24 h of rows go past `_HEALTH_REMEDIATION_MAX_BYTES` (64 MB), reading stops there
  and the response adds `stats.stats_truncated: true`, so a short count is flagged instead of
  silently low. Otherwise the response shape is unchanged.
- **Cache.** `_HEALTH_REMEDIATION_CACHE` is keyed on every candidate file's `(path, size, mtime_ns)`
  with a 60 s TTL, behind a lock, so concurrent polls share one computation (single-flight).
  Callers get deep copies. Candidate discovery (RuntimeAwareness, release-dir scan) is refreshed
  once per TTL. Duplicate candidate paths are still dropped, exactly as before.
- **Finviz credential-health.** Polls get a cached verdict (`_FINVIZ_CRED_HEALTH_TTL_S`, 300 s).
  The live probe (`_finviz_credential_health_live`) runs at most once per TTL, single-flight.
  While a probe is in flight, other requests get the previous verdict and do not wait. The
  `sys.path` insert now only happens if the path is missing. There is no scheduled job that stores
  a Finviz verdict (`credential_monitor.check_finviz` returns its result but does not persist it),
  so the route caches the verdict itself.
- **Frontend.** `RemediationDashboard` polls every 5 min instead of every 60 s, and only while
  the tab is visible (`src/lib/pageVisibility.ts`, through useApi's existing `enabled` option).
  Coming back to the tab triggers one fetch. `FinvizCookieBanner` skips interval polls while
  the tab is hidden.

## Measurements (read-only copy under `~/.cache/rtc/remediation-measure`, 303,832 lines, 174 MB)

| Implementation | Time | Peak RSS delta | Output |
|---|---|---|---|
| Old full parse | 1.92 s | +459 MB | 6,751 rows in 24 h, newest-50 sha `83f76e47e8530a9f` |
| New tail read | 0.18 s | +58 MB | identical stats, identical newest-50 sha |

The 24 h slice is about 2.7 MB of the inspector log and 1.1 MB of the agent log, so one 8 MB
window per file covers it.

## Not done here (operator decisions)

- The logs are still not rotated. Rotating or archiving them changes durable state and is
  operator-only (AGENTS.md §0 rules 6 and 7). With the tail read, file size no longer drives
  memory use, so rotation can wait.
- Nothing on the live host was touched: no restart, no unit drop-in, no file rotation.

## Tests

`tests/test_health_remediation_memory_20261022.py` (CI gate `health_remediation_memory_20261022`):
- On several fixtures, at three window sizes, the new handler's output equals the old full parse.
- With a 200,000-line file, the handler reads a bounded number of bytes (counted through a
  patched `open`).
- Hitting the cap sets `stats_truncated`.
- Single-flight: 8 concurrent threads produce one computation; the cache is invalidated when a
  file changes or the TTL expires.
- A cached Finviz verdict never triggers the probe, a stale verdict is served while a probe is in
  flight, and `sys.path` does not grow.

Frontend: `apps/command-center-v3/src/lib/pageVisibility.test.ts` runs in `npm run build`.
