# portfolio-server memory spikes after release 7 (2026-10-23)

```
Status:      ACTIVE (code on branch fix/server-memory-spikes-20261023; not deployed by this PR)
as_of:       2026-10-23T10:30:00-04:00
Measured at: served builds 0f5bf2453 / 53aa1b619 (read-only); per-route numbers from a forked
             child per route against the live data, writes neutralised, <=1 call/s
```

## What happened

Release 7 (0f5bf2453, live 08:53 ET) bounded `/api/v2/health/remediation` and cached the Finviz
credential verdict ([HEALTH_REMEDIATION_MEMORY_2026-10-22.md](HEALTH_REMEDIATION_MEMORY_2026-10-22.md)).
The cron watchdog still SIGKILLed portfolio-server four more times during market hours:

| Kill (ET) | memory.current | PSI some avg10 | What was running |
|---|---|---|---|
| 09:14:53 | 1.70 GB | 36.6 % | site-validation crawl on live :7777 (`/v3/agents`, `/v3/intelligence`, `/v3/hermes`) |
| 09:30:52 | 1.71 GB | 58.2 % | same crawl: `/v3/advisory` (3 concurrent `/api/v3/advisory`, 21–38 s) then `/v3/cio` |
| 09:56:52 | 1.6 GB peak | — | 7 concurrent `/api/v2/watchlist/items` (39–69 s), then +665 MB in 3 s |
| 10:12:52 | 1.72 GB | 49.7 % | 10:02–10:11 pile-up: 130 threads; paper-proposals 231 s, AT alerts 170 s, watch-prospects 464 s |

Memory was sampled every 3 s from the service cgroup (`memory.current`, `memory.stat`, thread
count). Between spikes the process sat at 500–600 MB. Each kill followed a step of several hundred
MB within seconds, and then memory.high throttling: once the cgroup is held at 1.5 GB, every
request slows, threads pile up, and the next probe of `/api/health` times out.

## Causes, measured per route

Each route ran once in a forked child of a process that had already imported `api_v2`.
"Peak" is VmHWM minus RSS at fork.

| Route | Before | After this PR | Cause |
|---|---|---|---|
| `GET /api/v3/maturity/memory` | **+1,192 MB**, 2.6 s, 7.2 MB body | +26 MB, 0.1–0.3 s, 0.1–0.5 MB | `tail_jsonl` read `aif_memory_retrievals.jsonl` (574 MB, 1,066,782 lines, never rotated) with `read_text().splitlines()` to keep 20 rows; all ~3,100 records returned to a panel that shows 40 |
| `GET /api/v3/cio/brain` | **+1,207 MB**, 9.1 s | +265 MB, 8.7 s | CIO memory summary counted the same 574 MB log with `read_text()`; data inventory `_row_count` read every JSONL store whole (largest 157 MB) |
| `GET /api/v3/cio/observability` | **+1,274 MB**, 10.8 s | +257 MB, 9.9 s | builds brain |
| `GET /api/v3/advisory` | +314 MB, 27–45 s, 3.8 MB | +229 MB, 6.4 s | `security_research_spine.load_latest` streamed and parsed the whole 26.5 MB spine once per row (146×, 267k `json.loads`, 26 s); the page fires 5 concurrent calls |
| `GET /api/v2/watchlist/items?sort=hermes` | +192–211 MB, 41–49 s | +139 MB, 15.5 s | `technical_freshness_state` read the full daily bar history 3× per row through `upper(symbol)=%s`, which cannot use the `(symbol, timeframe, bar_time)` index (1.67M-row seq scan, ~0.1 s each), only to read the last bar's age |
| identical concurrent GETs | 7 × watchlist/items, 3 × paper-proposals per poll, 12 × analyst/links | 1 computation each | no request coalescing; every tab, headless browser and retry recomputed |

The CIO numbers keep the `/api/v3/cio/home` composition (~206–268 MB), which this PR does not change.
Other heavy reads seen but not changed here: `/api/v2/ui/prefs/get?key=portfolio.shared-symbol-context.v1`
(9.4 MB body, about 2 polls/min), `/api/v2/backtesting/missed-opportunities` (14 MB body), and `/api/v2/symbol-cards` (3.3 MB).

### Who generated the load

* **Agent validation traffic on the live server during market hours.** Site-validation crawls
  (`tools/crawl.mjs --base=http://127.0.0.1:7777`) ran 08:55–09:14 and 09:16–09:32. Both ended at a
  kill. From 09:52 another agent's `vite preview --port 4391` (proxy `/api` → `127.0.0.1:7777`)
  and its playwright run held 19 TCP connections to :7777. Operator tabs come in through the cc-auth
  serve proxy (unix socket), not TCP :7777, so at 10:15 all of the TCP load was agent traffic.
* **Agents → Memory retry loop.** This is no longer reaching the server. The crawler's heavy-guard
  blocks the route. The only live hit in the retained log is 02:15:41Z, 72 s before the 02:16:53Z
  kill. The client-side amplifier is fixed by open PR #1984.

### Watchdog "escalate" lines

Every `still not responding after restart attempt — escalate` line today was a false alarm. The
script probed once, 6 s after SIGKILL. systemd waits `RestartSec=5` and the server needs about 2 s
to bind. For example: kill 09:30:57, verify 09:31:03, systemd `Started` 09:31:04, first `/api/health`
200 at 09:31:05. The restarts worked. `SIGTERM` was ignored for 5 s because the process was stalled
in memory.high reclaim.

## Fix (this PR)

- `scripts/lib/jsonl_bounded.py` (new, stdlib):
  - `tail_jsonl_lines` reads backwards in doubling windows, capped at 16 MB. It returns the same
    lines as the full read.
  - `count_jsonl_lines` streams 4 MB chunks. Its count is cached per (device, inode, size): a file
    that grew is counted over the appended bytes only, and a file that shrank or was replaced is
    counted again from the start. One lock, so callers share a scan.
- `agent_durable_memory.tail_jsonl` → bounded tail. `api_v3_cio.get_memory_summary_v1` and
  `data_store_inventory._row_count` → streamed cached count.
- `GET /api/v3/maturity/memory`:
  - Records are newest first, capped by `?limit=` (default 200, max 1000), with `records_total`,
    `records_truncated` and `contradictions_total`. Counts still cover the whole store.
  - One composition is shared for 30 s (`TRADEAI_MATURITY_MEMORY_TTL_S`) and built single-flight.
    It is rebuilt as soon as `aif_memory.jsonl` changes, so dispute, retract and expire show at once.
  - The Memory panel asks for `?limit=40` every 120 s (was the full store every 30 s).
- `security_research_spine.load_latest` keeps a per-file offset index `{SYMBOL: (offset, length)}`
  of the latest parseable line, extended over appended bytes. It is rebuilt if the file is
  replaced, shrinks, its head changes, or the indexed boundary no longer ends a line. A lookup
  reads one line. If the indexed row disagrees, it falls back to the full scan.
- `api_v3_advisory.get_advisory_desk`:
  - The composed desk is shared per `row_class` for 30 s (`TRADEAI_ADVISORY_DESK_TTL_S`) and built
    single-flight.
  - It is invalidated when the desk or opinion cache file changes. `force=1` always rebuilds.
  - Failures are not cached.
- `technical_intelligence.technical_freshness_state` reads only the last closed bar
  (`symbol = %s … ORDER BY bar_time DESC LIMIT 1`, about 0.4 ms by index). A resampled timeframe
  inherits the daily state, as `load_bars` does. If no row matches the exact symbol, it falls back
  to the old path. Live check: `market_ohlcv_bars` has 0 rows with lower-case symbols.
- `scripts/lib/request_coalesce.py` + `portfolio_server._coalesce_get`:
  - Identical concurrent GETs on an allowlist of read routes share one computation. The key is
    principal + path + query, with `_` cache-busters ignored.
  - The result is reused for 2 s. Errors go to every waiter and are never cached.
  - Each caller gets its own top-level and `data` dict, because `json_response` stamps `_serving`
    and pops `__etag__`.
  - Env: `TRADEAI_COALESCE_GET=0` turns it off; `TRADEAI_COALESCE_GET_PATHS` replaces the allowlist.
- `portfolio_server_watchdog.sh`: after a kill, polls `/api/health` every 3 s for up to 45 s
  (`VERIFY_SEC`) and logs how many seconds the restart took. The worst-case run stays inside the
  2-minute cron period.

## Not done here (operator decisions)

- **Rotating the never-rotated logs.** These include `aif_memory_retrievals.jsonl` (574 MB),
  `research_call_accounting.jsonl` (1.7 GB) and `cio_workflow_lineage.jsonl` (157 MB). Rotation
  changes durable state and is operator-only (AGENTS.md §0 rules 6 and 7;
  `scripts/rotate_append_only_store.py` already lists the retrievals log).
- **Agent validation against live :7777 during market hours.** Crawlers and `vite preview` +
  playwright runs should use a replay/mock backend, or wait until the market is closed. This is a
  policy or AGENTS.md matter.
- `/api/v3/cio/home` (~206–268 MB per build, cached 60 s) and the 9.4 MB
  `portfolio.shared-symbol-context.v1` pref are the next candidates.
- Nothing on the live host was touched: no restart, no unit drop-in, no crontab change. The
  watchdog script change ships with the release, and its cron line is unchanged.

## Tests

`tests/test_server_memory_spikes_20261023.py` (CI gate `server_memory_spikes_20261023`):
- **Bounded tail.** The tail equals the full read across fixtures, window sizes, trailing and
  missing newlines, and blank or invalid lines. A 20 MB / 200,000-line log is tailed in ≤ 512 KB
  read. The byte cap returns a short result, never the whole file.
- **Streamed count.** The count equals the full read. It is incremental: the appended bytes only,
  and no read at all when the file is unchanged. It is recounted after replace or truncate, and it
  is correct across chunk boundaries. The CIO memory summary and data inventory never `read_text`
  a JSONL store.
- **Memory view.** Bounded, newest first, counts whole. 8 threads produce 1 build. A store change
  invalidates the view, and callers get independent copies.
- **Spine index.** Equals the full scan through appends, a partial final line, an in-place rewrite
  that grows, and `os.replace`. A lookup reads ≤ head + one line. Concurrent readers agree.
- **Advisory.** 8 threads produce 1 build. Separate per class. `force`, a file change and the TTL
  each rebuild. Failures are not cached.
- **Freshness.** Equals the old full-history result for CURRENT / STALE / none / lower-case-only /
  forming-only, both in and out of RTH, with one indexed query.
- **Coalescing.** 8 threads produce 1 computation. Per-caller copies survive `_serving` / `__etag__`
  mutation. TTL reuse, different queries kept apart, errors shared but not cached, only allowlisted
  routes, keyed by principal.
- **Watchdog.** Bash syntax, a verify loop, and a worst case under 120 s. The client asks for a
  bounded page.
