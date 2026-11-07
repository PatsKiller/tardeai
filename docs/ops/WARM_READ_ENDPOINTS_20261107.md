# Warm the read-only endpoints after a release restart (LQ-20261107-266)

**Decision:** a restart empties every in-process cache in the API, and the first operator page load after a
release pays for all of them at once. A new n8n lane, `warm-read-endpoints`, pays that cost itself, within two
minutes of the boot, instead of the first human who opens the app. It is **not** a poll: it reads the server's own
boot stamp, warms once per process, keeps the 60 s caches hot for ten minutes, and outside that window a fire does
no HTTP work at all and still writes a receipt.

The lane code is `scripts/warm_read_endpoints.py`; the n8n wiring is a three-file bundle
(registry row, run-allowlist entry, health contract) delivered to the lead, who is the single writer for shared
n8n config. Until it is applied, the lane is inert.

---

## 1. The measurement

`scripts/portfolio_server.py::_log_slow_request` appends one `[slow-request] <UTC> <elapsed>s <path>` line for every
request at or above `TRADEAI_API_SLOW_REQUEST_SEC` (default 10 s). Those lines, from
`logs/portfolio_server.log`, are the evidence — not a manual curl.

Three restarts on 2026-11-07 (each one a release deploy), and the first calls after each:

| restart (UTC) | pin | first calls after boot |
| --- | --- | --- |
| 20:47:57 | `256af0d18` | 20:48:40 `risk` 13.6 s · 20:48:41 `cio/pages` 28.7 s · 20:48:41 `jobs-catalog` 29.3 s · 20:48:42 `jobs-catalog` 30.4 s · 20:48:43 `jobs-history` 31.0 s · 20:49:29 `control-plane-surface-authority` 16.3 s |
| 20:59:59 | `dd383add6` | 21:00:29 `cio/pages` 16.8 s · 21:01:04 `jobs-catalog` 19.1 s · 21:01:04 `jobs-catalog` 52.0 s · 21:01:04 `jobs-catalog` 52.4 s · 21:01:04 `jobs-history` 52.5 s |
| 21:05:06 | `eeafec38` | 21:05:35 `cio/pages` 14.0 s · 21:05:44 `jobs-catalog` 32.4 s · 21:05:44 `jobs-catalog` 32.6 s · 21:05:45 `jobs-history` 32.9 s |

Two things fall out of the table:

* **The cost is per process, not per page.** The same routes cost 13–31 s on an empty cache and nothing (a cache
  hit) a minute later. Every restart reproduces it, and a merge deploys in about twelve minutes.
* **Concurrent first calls multiply it.** `scripts/lib/jobs_history.py::snapshot` builds outside its lock when the
  cache is empty, so three callers that arrive together each run the whole `_load` on one core: 52 s each at
  21:01:04 where a solo build is 31 s. The lane's single warm avoids that pile-up by being first.

## 2. Why a restart-scoped lane, not a prewarm poll

`config/lane_registry.json` already carries two blind prewarm curls — `prewarm-trade-ai` (`*/5`) and
`prewarm-finviz-strip-map` (`*/8`) — both with `output_signal.kind: none`, `value_class: "Technical Debt"` and
`recommendation: "R0_ELIMINATE"`: *cache refresh on data arrival*, with no durable output to prove they ran. A third
one would inherit the same verdict.

It would also not work. The caches are 60 s (`_shared_get_cached` for `cio/pages` and `risk`, `CACHE_SECONDS` in
`jobs_history`), so a poll every five minutes warms nothing between its own fires. The useful work exists only in
the minutes after a restart, which is exactly what the boot stamp names.

## 3. The mechanism

`scripts/portfolio_server.py` writes `PortfolioServerBoot@v1` at startup to
`~/.local/state/tradeai/portfolio_server_boot.json` (override: `PORTFOLIO_SERVER_BOOT_STAMP_PATH`) carrying
`pid`, `process_started_at`, `loaded_pin_sha`, `current_pin_sha`. The lane reads that file — a local file read, not
an HTTP call — and derives an identity `"<pid>:<process_started_at>"`.

`decide(identity, started_at, state, now)` returns the reason, and only two values warm:

| decision | warms | when |
| --- | --- | --- |
| `restart` | yes | the identity differs from the one last warmed (or the stamp is unreadable and nothing was warmed yet) |
| `still_in_window` | yes | same process, inside the 10 min window, under the cycle cap, and at least 95 s since the last warm |
| `too_soon` | no | inside the 95 s interval: the 60 s caches are still fresh, a warm would warm nothing |
| `window_closed` | no | more than 600 s since the process started |
| `cycle_cap` | no | 6 warm cycles already done for this process |
| `boot_stamp_unreadable` | no | no stamp and something was already warmed |

The rails are deliberate. `WARM_WINDOW_SEC = 600` bounds the CPU the lane spends; `WARM_MIN_INTERVAL_SEC = 95`
is longer than every cache TTL in the target list, so consecutive warms cannot become a busy loop;
`WARM_MAX_CYCLES = 6` bounds it even if the clock is wrong (a future `process_started_at` makes the window never
close — the test suite pins that case). An unreadable stamp warms exactly once and then stops, because a lane that
cannot see which process is serving must not fall back to polling.

A warm run is five GETs against `127.0.0.1` in the shipped order, with a 60 s per-endpoint timeout. Each row records
the HTTP status, the byte count and milliseconds; a transport failure records the exception **type** only (the URL
carries no secret, the message can). One failing endpoint does not stop the others, and the run then:

* leaves the state file untouched, so the next fire retries a full warm instead of declaring a warm it never
  finished;
* exits 1 and writes a `failed` receipt with `skipped_reasons: {<path>: 1}` and `produced_count` = the endpoints
  that did answer 200.

A complete warm writes, under the durable runtime root (`data/runtime`) next to the release's own state:

* `warm_read_endpoints_state.json` (`WarmReadEndpointsState@v1`) — boot identity, cycle count, `last_warm_at`,
  the endpoints the last warm covered;
* `warm-read-endpoints_last.json` — `LaneRunReceipt@v2` from `lib.lane_last_receipt`, with
  `produced_count` = endpoints answered 200, `skipped_reasons`, `empty_reason`, and the per-endpoint rows under
  `summary.endpoints`. With `TRADEAI_RUN_ID` set (the executor sets it), the same receipt is also written to the
  immutable per-attempt copy under `data/runtime/lane_attempts/warm-read-endpoints/`.

A no-op fire also writes a receipt: `status: "ok"`, `produced_count: 0`, `empty_reason: "already_warm"`, and the
decision in `summary`. That is what makes "it did nothing" auditable instead of indistinguishable from "it did not
run" — and what lets the health contract accept a legitimate empty run without accepting a dead lane.

## 4. The rail: what this lane may ever call

* **GET only.** `_fetch` calls `lib.cc_client.cc_urlopen(url, timeout=…)` with no `data` and no `method` override;
  the tests' fake opener asserts both on every call.
* **Loopback only.** `_is_loopback` refuses anything but `http://127.0.0.1`, `localhost` or `::1` before the first
  request, so a mistyped `--base` cannot send this lane at another host.
* **A constant target list.** `ENDPOINTS` is a module constant, never an argument. `_check_endpoint_rail` refuses a
  path that is not `/api/`, carries a query string, or contains a mutation token (`/run`, `/approve`, `/apply`,
  `/execute`, `/order`, `/place`, `/send`, `/kill`, `/restart`, `/retry`, `/delete`, `/remediate`, `/fix-now`,
  `/decision`, `/write`, `/ingest`). An edit that adds an action endpoint fails there and in
  `tests/test_warm_read_endpoints_20261107.py`, whose CI gate is `config/ci_gates/warm_read_endpoints_20261107.json`.
* **No credential read.** The loopback service token comes from the existing `config/cc_auth.yaml` inside
  `lib.cc_client`, as it does for every loopback caller; the allowlist entry declares `env_names: []` and the
  executor's `CHILD_ENV_BASE_NAMES` already carries `HOME`, so the boot stamp path resolves.
* **No response body is stored.** The receipt keeps the status, the byte count and the milliseconds.

`MBI_BEHAVIOR = 0`: nothing here sizes, orders, stops, weights or reaches a broker. Every target is a read model.

## 5. The n8n wiring (bundle for the lead)

Three insertions, no edits, no deletions, all validated in-process before delivery:

| file | row |
| --- | --- |
| `config/lane_registry.json` | `lane_id: warm-read-endpoints`, `owner: platform`, `scheduler {kind: n8n, expression: dispatcher, match: scripts/warm_read_endpoints.py, cadence: "*/2 * * * *", stage: shadow, wave: W3}`, `state: ACTIVE`, `output_signal {kind: json_key, path: data/runtime/warm-read-endpoints_last.json, key: ok_at}`, `dispatch {mode: dry_run, cron: ["*/2 * * * *"], tz: America/New_York, wave: W3, class: monitor, priority: 4, retry_policy: transient-2}` |
| `config/n8n_run_allowlist.json` | `command: ["$PY", "scripts/warm_read_endpoints.py"]`, `env_names: []`, `lock: /tmp/tradeai_warm_read_endpoints.lock`, `lock_kind: safe_flock`, `timeout_s: 420`, `dry_run_arg: ["--dry-run"]`, `live_arg: ["--apply"]`, `market_gate: false`, `output_signal: data/runtime/warm-read-endpoints_last.json` |
| `config/n8n_health_contracts.json` | `N8nHealthContract@v1`, `kind: lane`, `stage: shadow`, `expected_output {rule: min_produced, min_produced: 1, empty_allowed_reasons: ["already_warm"], fatal_skip_reasons: ["no_runner", "dependency_unavailable", "all_endpoints_failed"], on_violation {run_state: RUN_FAILED, reason: empty_output, notifier_priority: P2}}` |

`dispatch.mode: dry_run` is the shadow stage: the executor runs `--dry-run`, which prints the plan and writes
nothing, so the first dispatch proves the wiring without touching the API. The live argv is `--apply`.

Validation run against scratch copies of the three files (never the shared ones):

```
$ python scripts/warm_read_endpoints.py --dry-run          # against the live boot stamp
[warm-read-endpoints] DRY RUN — would restart: warm; boot 92751:2026-11-07T16:08:07-05:00; 5 endpoint(s)
    GET /api/v2/system/control-plane-surface-authority   # 15.0 s cold (LQ-20261107-259), 16.3 s on the first call …
    GET /api/v2/cio/pages   # 28.7 s on the first post-restart load; _shared_get_cached 60 s, single-flight
    GET /api/v2/jobs-catalog   # 29-30 s on the first post-restart load; built from the cached jobs-history projection
    GET /api/v2/jobs-history   # 31.0 s on the first post-restart load; the projection every Ops job view reads
    GET /api/v2/risk   # 13.6 s on the first post-restart load; _shared_get_cached 60 s, single-flight
    (a dry run writes no receipt and no state)

$ python -c "from lib import lane_dispatch as LD; …"
validate_entry: None
dispatch issues: []
dispatch_eligible: (True, 'eligible')
dispatch_mode: dry_run
forbidden_text_hits: every command-bearing field [] (lane_id, scheduler.*, allowlist argv)

$ python scripts/check_n8n_health_contracts.py --registry <patched> --contracts <patched>
n8n health contracts: clean {"contracts": 199, "targets": 174, "draft": 45, "reviewed": 154, …}   # base: 198/173/153
```

The bundle applies to the integration head with `git apply --check` clean and a diffstat of
`3 files changed, 282 insertions(+)`.

## 6. Verifying it in production

1. **It ran at all.** `data/runtime/warm-read-endpoints_last.json` exists and its `generated_at` advances on each
   cadence; the executor's ledger (`data/governance/n8n_coordination_ledger.sqlite`) lists the runs by `lane_id`.
   An n8n execution status proves nothing on its own — successful executions are soft-deleted.
2. **It warmed, not just ran.** After a restart, `produced_count == 5` and `summary.decision == "restart"`. Between
   restarts, `produced_count == 0` with `empty_reason == "already_warm"` is the correct answer, not a failure.
3. **It helped.** No `[slow-request]` line for the five targets in the two minutes after a restart, while the same
   line still appears for anything not on the list. Compare the three episodes in §1.

## 7. What this does not fix — report, not absorb

* **`/api/v2/ops/in-flight` costs about 11 s on every call, all day** (three lines every two minutes, thousands of
  occurrences in the log, ten minutes after a restart as well as ten hours in). It has no cache, so no warm lane
  can help it; it needs its own fix.
* **`/api/v2/data-sources/finviz/credential-health` reached 64.7 s at 21:06:16Z**, after a restart, and appears at
  ~29 s repeatedly. Not on the target list: the lane warms only what a reload of the operator pages actually reads,
  and this route is not on their load path.
* **The first cold build is still paid somewhere.** Warming moves it, it does not delete it: the lane now spends the
  13–31 s, once, immediately after a restart. Making the routes cheap is a different change.
* **`scripts/lib/jobs_history.py::snapshot` has no single-flight on the cold path.** Three concurrent first calls
  each build; the 52 s rows above are that, not a slower build. The lane avoids the pile-up by arriving first, but
  the defect remains and would reproduce on any restart that races three tabs.
* **The watchlist cold path belongs to LQ-20261107-258** (target under 3 s cold). It is deliberately not in
  `ENDPOINTS`: there is no in-process cache to keep warm until that lands.

## 8. Re-engineering?

If a future route needs the same treatment, do not add a curl: add a path to `ENDPOINTS` with its measured cold
cost and the cache it fills, and extend the rail's forbidden tokens if the route shape is new. If the boot stamp
ever disappears from the server, this lane degrades to one warm per restart-shaped event at most and then stops —
by design, it must not become the poll it replaces. The durable upgrade would be for the API to expose a
first-class "warm" signal on the health route instead of the lane reading a file the server happens to write.
