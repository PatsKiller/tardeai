# 03 — Momentum-scalp lanes under n8n: inventory, root cause, dispatch design, monitoring

**Status:** B4 deliverable, n8n maturity program, 2026-10-09 (T0 + ~1 h). Owner: Agent B (workstream B4). Agent A reviews and merges.
**Operator directive:** "make sure momentum_scalp are developed and monitored correctly in N8N".
**Policy:** AGENTS.md **4.0.0** (on main since train #1583). trade-ai-scalp-live may run live from n8n under the cron line's argv, lock, 295 s timeout and market gate. That needs a relay live-lane listing and a workflow-id grant, and cron stays the fallback until **3 clean market days**. Active Trader is a notifier only. Scalps here are signals and alerts; no broker, order or stop code is in scope.
**Companion docs:**
- `docs/implementation/n8n-parallel/lanes/scalp-lane-20261009.md` (#1573 and 4.0.0 lane packet);
- `docs/ops/SCALP_CATALYST_BULK_2026-10-09.md`;
- `02-six-workflow-architecture.md` (A-design; not yet on main when this was written, so §3 follows the approved plan).

---

## 1. Inventory (evidence from 2026-10-09, about 16:10 ET)

Notes:
- "inv/compl" is the count of `journalctl -t CRON` invocations against completions found in logs, receipts or the DB.
- Line numbers are crontab lines.
- "baseline-only" means the line is in `undeclared_baseline` and has no lane row (§5 adds the rows).
- **Forbidden tokens:** a grep of each script and its direct local imports for `place_order`, `submit_order`, `cancel_order`, `replace_order`, `order_router`, `broker_exec`, `stop_order`, `execute_trade`, `--submit` and `submit_sandbox`.

| lane_id (registry) | schedule | gate | lock | timeout | output | last ok | inv/compl today | forbidden hits | class |
|---|---|---|---|---|---|---|---|---|---|
| **trade-ai-scalp-live** l.1050 | `*/5 9-15` | market_day_gate.sh + in-script RTH | /tmp/tradeai_scalp_live.lock | 295 | data/trade_ai/scalp_universe_latest.json, trade_ai_scans `run_label=scalp`, receipt (main only) | 15:59 | **42 / 7 (17%)** | 0 | **DISPATCHER_ELIGIBLE** (sender; the 4.0.0 §23.3 named exception) |
| social-scalp-scanner (baseline-only) l.246 | `0,30 6-9` | none | /tmp/social_scalp.lock | none | social_scalp_scanner.log | 09:31 | 8/8 | 0 | DISPATCHER_ELIGIBLE (Telegram sender: needs a §23.3 sender exception first) |
| momentum-scalp-advisory-alerts l.324 | `*/10 6-11` | none | /tmp/auto_proposal_momentum_scalp.lock | 5m | auto_proposal_momentum_scalp.log | 11:50 | 36/36 | imports `broker_config` and a sandbox `submit_paper` path | KEEP_ON_CRON_WATCHED |
| auto-proposal-general l.323 | `*/30 9-16` | in-script | /tmp/auto_proposal_general.lock | 5m | auto_proposal.log | 16:00 | 15/15 | same, plus `MOMENTUM_SCALP_VALIDATION_SUBMIT=1` env | KEEP_ON_CRON_WATCHED |
| catalyst-momentum premarket_scalp (baseline-only) l.379 | `*/30 4-9` | none | safe_flock /tmp/catalyst_premarket.lock | none | data/cio/catalyst_momentum_last_run.json | 09:30 | 12/12 | `--generate-proposals` spawns the paper proposal generator | KEEP_ON_CRON_WATCHED |
| catalyst-momentum market_swing (baseline-only) l.380 | `30 9-15` | none | safe_flock /tmp/catalyst_swing.lock | none | same | 15:30 | 7/7 | same | KEEP_ON_CRON_WATCHED |
| reclassify-momentum (baseline-only) l.609 | `*/30 9-16` | none | /tmp/reclassify_momentum.lock | none | reclassify_momentum.log | 16:00 | 15/15 | 0 | DISPATCHER_ELIGIBLE (DB relabel only) |
| momentum-scalp-validation-fast-path (baseline-only) l.633 | `*/2 6-11` | none | /tmp/momentum_scalp_validation_fp.lock | none | momentum_scalp_validation_fast_path.log | 11:58 | 180/180 | `--submit-sandbox` code path (run with `--dry-run`) | KEEP_ON_CRON_WATCHED |
| finviz-momentum-scalp-early-lane l.636 | `*/5 6-11` | in-script trading day + window | /tmp/tradeai_finviz_momentum_scalp.lock | 280 (inner 260) | data/runtime/momentum_scalp_refresh_receipt.json | 11:55 | 72/73 | `--submit-validation` → sandbox submit path | KEEP_ON_CRON_WATCHED |
| sec-form4-momentum-context (baseline-only) l.640 | `45 5` | none | /tmp/tradeai_sec_form4_ctx.lock | none | sec_form4_momentum_context.log | 09:48 (unknown second invoker) | 1/1 | 0 | DISPATCHER_ELIGIBLE |
| hermes-momentum-catalyst-scalp l.708 | `25 6-15` | none | /tmp/hermes_scalp_catalyst.lock | 5m | hermes_scalp_catalyst.log | 15:26 | 10/10 | 0 | DISPATCHER_ELIGIBLE (research only) |
| scalp-volume-profile (baseline-only) l.802 | `30 20` | in-script holiday | safe_flock | none | scalp_volume_profile.log | 10-08 20:30 | 0/0 (20:30) | 0 | DISPATCHER_ELIGIBLE once its wrapper stops hard-coding the dev tree |
| scalp-shadow-logger (baseline-only) l.804 | `*/5 6-11` | in-script RTH | safe_flock /tmp/scalp_shadow_logger.lock | none | DB scalp_ignition_events (720 rows 09:35-11:55) | 11:55 | 72 / about 29 RTH cycles | 0 | DISPATCHER_ELIGIBLE (AT alert sender: needs a §23.3 sender exception; the wrapper hard-codes the dev tree) |
| screener-go-alerts l.961 | `*/15 9-16` | none | /tmp/screener_go_alerts.lock | none | data/runtime/screener_go_alerts_last_run.json | 16:00 | 29/28 | 0 | DISPATCHER_ELIGIBLE (sender: needs an exception) |
| active-trader-premarket-watch l.1004 | `*/5 6-9` | in-script 06:00-09:29 | /tmp/at_premarket.lock | 240 | data/active_trader/momentum_alerts_premarket_heartbeat.json | 09:25 | 48/48 | 0 | DISPATCHER_ELIGIBLE (moomoo quote reads plus sender) |
| active-trader-micro-recorder(-premarket) l.1007-1008 | `0 6` / `28 9` | in-script | /tmp/at_micro_recorder(_pm).lock | none (runs about 2.5 h) | data/active_trader/micro/live_symbols.json | 11:58 | 2/2 **degraded** (963 errors in 1816 polls) | 0 | KEEP_ON_CRON_WATCHED (long-running moomoo session) |
| active-trader-session-review(-close) l.1010-1011 | `5 12` / `10 16` | none | /tmp/at_session_review.lock | 300 | data/active_trader/reviews/<day>.json | 16:10 | 2/2 | 0 | DISPATCHER_ELIGIBLE |
| active-trader-signal-calibration l.1013 | `10 12` | none | **none** | **none** | data/active_trader/learning/calibration_report.json | 12:10 | 1/1 | 0 | DISPATCHER_ELIGIBLE after it gets a lock and timeout |
| **tradeai-active-trader-motion** (systemd; **no registry row**) | daemon, 30 s cycle | in-code session check | data/active_trader/motion_runtime.lock (dev tree) | n/a | heartbeat and motion_journal.jsonl (dev tree), healthy at 16:10 | 16:10 | n/a | 0 (authority flags all false) | KEEP_ON_CRON_WATCHED (watched only) |

**Motion daemon (audit D 2.3).**
- A drop-in pins `WorkingDirectory`/`PYTHONPATH` to release a032116e7 (10-06). PID 1673747 has run since 10-06 16:11 with 0 restarts.
- `git diff a032116e7 origin/main -- scripts/active_trader/` touches only `microstructure_recorder.py`, `momentum_alert_pass.py` and `momentum_alerts.py` (#1551). None of the three is in the motion import graph, so the 10-06 code is functionally current.
- **Risk:** pruning release a032116e7 breaks the daemon. Its log (`logs/active_trader_motion.log`, dev tree) has not been written since 10-06, so the heartbeat file is its only health signal.

### 1.1 Recent PRs

| PR | sha | scalp change | in live 210875338? |
|---|---|---|---|
| #1551 | bf80b375d | AT ARMED floor, real setup levels; the AT pass reads trade_ai_scans; recorder reconnect | yes (not in the motion daemon, which does not import it) |
| #1553 | 767297c5a | the 5-min lane, scalp projection, shared feeds for the shadow logger | yes |
| #1564 | 66693c21e | catalyst cache write-through per symbol | yes (from 15:46 ET) |
| #1572 | 210875338 | `enrich_budget_s: 150` | yes (from 15:46 ET) |
| #1573 | open, 672ff9aa2 | n8n lane, receipt, stall watch | **no**: equivalent commits 7c0837449, 13802b2f5 (4.0.0) and af9199ff4 (bulk catalysts) are on main 079e8ff42 but **not live** |

### 1.2 The operator's 10-09 rule: "one feed for Trade-AI and Active Trader, scans every 5 min" (#1553)

**Verdict: true in code, not true at runtime today.**
- **In code:**
  - Trade-AI writes `data/trade_ai/scalp_universe_latest.json`.
  - The AT shadow logger (`scalp_shadow_logger.scalp_projection_rows` / `shared_feed_rows`, `config/scalp_signal_engine.yaml shared_feeds.enabled: true`, 15-min max age) reads it, together with today's `trade_ai_scans`.
  - The AT alert pass (#1551) and the read_api fires panel also read `trade_ai_scans`.
- **Not at runtime today:**
  - The AT engine runs only `*/5 6-11`, and its wrapper runs the **dev tree**, which did not contain #1553 or #1551 during the 09:35-11:55 window. The scalp lane started at 12:30.
  - From Monday, the two overlap only from 09:30 to 11:55. **The afternoon 5-min Trade-AI scan has no Active Trader consumer.**
  - The motion daemon reads `scalp_ignition_events` and a static symbol list, so it gets the shared feed only indirectly.
- **Decision for the operator:** either extend the AT engine window to the close (a crontab change under a grant), or accept that the AT feed is morning-only. Either way, `run_scalp_shadow_logger.sh` should run `$PROJ`, not the dev tree.
- **Every 5 min:** that is the cadence, but only 7 of 42 cycles completed today (§2).

---

## 2. Root cause: why the 5-min lane produced little output today

The per-slot reconstruction uses syslog CRON, release switch times, catalyst-cache entry timestamps, `trade_ai_scans` run_ids and other sessions' transcripts. Of 42 slots from 12:30 to 15:55:
- 7 completed;
- **25 were killed by `timeout 295`**;
- 9 were skipped by `flock -n` while a manual warm-up run held the lock;
- 1 failed because the script was missing.

| Slots (ET) | n | Outcome |
|---|---|---|
| 12:30 | 1 | Script missing. The crontab was replaced at 12:25:43 (PR #1553 lane add), and CURRENT was 3b5c24856, which has no script until about 12:31. |
| 12:35-12:50 | 4 | Killed: cold cache, no budget. |
| 12:55-13:10 | 4 | Skipped by flock: a manual `flock -w 400` run with no timeout wrote run_id 1254 at 13:11. |
| 13:15 / 13:20 / 13:25 | 3 | Completed in 260 / 158 / 136 s (warm cache from the manual run). |
| 13:30-15:00 | 19 | **Killed: death spiral.** The cache TTL (20 min) expired, and every cycle was killed before its single end-of-enrichment cache write, so nothing was ever cached. |
| 15:05-15:25 | 5 | Skipped by flock: a manual no-timeout run took 1263 s and wrote run_id 1504 at 15:26. |
| 15:30 / 15:35 / 15:40 | 3 | Completed in 267 / 133 / 194 s. |
| 15:45, 15:50 | 2 | Killed **after the #1572 promote**. Enrichment began 2:40 to 3:25 after process start. |
| 15:55 | 1 | Completed in 272 s (8 fresh lookups, 32 deferred on the 150 s budget). |

### Root causes, ranked (confidence high for all)
1. **The catalyst cache was written once, at the end of enrichment.** A killed cycle saved nothing, so the next one started just as cold. Fixed by #1564 (write-through, live 15:46).
2. **Per-ticker enrichment cost far exceeds the timeout.** Lookups took 16-24 s per name at load average about 10, and a cold cycle needs 1000 s or more. The fix is af9199ff4 (bulk catalysts, about 18 s for 64 of 76 names); it is **on main but not live**.
3. **The #1572 budget is not a deadline.** It counts from the start of enrichment. Ingest took 1-3.4 min under load, and scoring plus persist took 60-75 s, so the worst case is about 425 s against 295 s. Two of the three post-promote cycles were killed. **Fixed in this PR** with a wall-clock deadline.
4. **Manual warm-ups held the lock with no timeout (9 slots).** Runbook fix in §4.4.
5. **Rollout order.** The cron line went in before the release that carried the script.

**Why audit D could not see this.**
- A killed cycle wrote nothing: stdout is block-buffered (a cycle is about 5.2 KB, under 8 KB), there was no start line and no receipt, and the rc 124 was never recorded.
- `flock -n` skips are silent.
- `trade_ai_scans` is not a cycle ledger: `ON CONFLICT (symbol, run_date)` overwrites `run_id` across labels.
- **No lock leak:** `run_live_cycle` has no subprocesses, `market_day_gate.sh` `exec`s, and SIGTERM reaches Python directly.

### Before and after the 19:46Z promote (#1564 + #1572)

| | 12:30-15:40 (39 slots) | 15:45-15:55 (3 slots) |
|---|---|---|
| completed | 6 (15%) | 1 (33%) |
| killed by timeout | 23 | 2 |
| skipped (flock, manual runs) | 9 | 0 |
| script missing | 1 | 0 |
| success among cron runs that started Python | 6/29 (21%) | 1/3 |
| seconds, completed | median 176, max 267 | 272 (92% of the deadline) |

The post-promote sample is 3 slots, because the market closed 14 minutes after the promote. Monday's first RTH session, with this PR plus af9199ff4 deployed, is the real measurement. `check_scalp_cycles.py --date <day>` now produces it from receipts.

### Fixes in this PR (branch `n8nmat/b4-scalp-cycle-receipt`)

| Defect | Fix |
|---|---|
| Budget counted from enrichment start | `run_live_cycle(deadline_monotonic=, post_enrich_reserve_s=)`. Lookups, and the bulk read, stop once fewer than `post_enrich_reserve_s` (100) remain before `cycle_deadline_s` (295), counted from process start. Deferred names score on the stale cache. Config: `config/trade_ai_scalp_lane.yaml`. |
| Killed cycles invisible | `ScalpCycleReceipt@v1` ledger: `started` before any work, then `ok`/`error`/`killed`. A SIGTERM handler writes `killed` with the phase reached, then exits 143. A `started` with no final record means SIGKILL or a crash. |
| Block-buffered, untimestamped log | stdout/stderr line-buffered. Timestamped `cycle start slot=… pid=… release=…` line. The heartbeat line carries `budget_pct`, `at=` and `slot=`, keeping the `[scalp-live] heartbeat ok` prefix. |
| Dedupe hole on a kill | `CycleState` (the "already alerted" memory) is saved through `state_saver` **before** the Telegram send, not only after the cycle. |
| Two cycles in one slot (cron then n8n) | Slot guard: if the day's ledger already has an `ok` for this slot, the run exits 0 ("slot done"). The shared flock already stops concurrent runs. |
| Early-close days | `in_rth` uses `market_session.current_market_session` (holidays and 13:00 closes), with the fixed window as the fallback. |
| Ingestion/scoring failure read as ok | `run_live_cycle` fills `cycle_stats` (phase, symbols, signals, triggers, alert outcome, errors). An early return with errors is an `error` cycle (exit 1). |

### Not fixed here; follow-ups
- **Deploy af9199ff4.** It is on main; the next promote carries it, together with this PR.
- **Catalyst cache location.** `catalyst_cache_<date>.json` lives in each release's `data/`, so every promote starts from a copy, and a run that resolved CURRENT just before the flip writes to the old release. Moving it to the state root touches the full runner too, so it needs its own PR.
- **`trade_ai_scans` conflict key** clobbers run_id and run_label across labels (`symbol, run_date`). Its own PR: schema owners.
- **Unknown deleter of `/tmp/tradeai_scalp_live.lock`.** Missing at 16:12; `cleanup_stale_locks.sh` is report-only since b9bb8348e. Watch it.

---

## 3. n8n design for scalps (fits the 6-workflow plan)

**What exists** (origin/main 079e8ff42):
- **Allowlist** `config/n8n_run_allowlist.json:348-364`: `trade-ai-scalp-live` with the same lock (`flock -n`), `timeout_s 295`, `market_gate true`, `dry_run_arg ["--dry-run"]`, `live_arg []`, no `retry`.
- **Executor wrapper** `scripts/n8n_run_executor.py:177-192`: `flock -n -E 75 <lock> timeout -k 30 295 [market_day_gate.sh] <cmd>`. A lock collision maps to `RUN_SKIPPED_LOCK`.
- **Executor loop:** a single serial `drain()` (`:358-401`); inline retry sleeps (`:216-245`); FIFO `claim_next` (`scripts/lib/n8n_coordination_ledger.py:547-565`); no expiry, no dead-letter state.

### 3.1 Minute-dispatcher entry and gate
- **Registry fields** (rows in §5):
  - `scheduler.cron "*/5 9-15 * * 1-5"`, `scheduler.tz "America/New_York"`;
  - `dispatch {gate: "rth_regular", class: "realtime", slot_s: 300, deadline_s: 295, start_deadline_s: 60, fire_offset_s: 0}`.
- **`coordination/due`:**
  - computes slots with `scripts/lib/cron_schedule.next_run`;
  - emits only when `market_session.current_market_session(now) == "regular"`, which covers weekends, holidays and early closes (78 slots on a full day, 42 on an early close);
  - the 09:00-09:25 cron fires are not dispatched;
  - if the session check errors, it does **not** dispatch and records `DISPATCH_GATE_ERROR`. Cron is the fallback while it exists.
- **Defence in depth, kept:**
  - `market_day_gate.sh`, which fails open;
  - the runner's `in_rth`, now calendar-aware.

### 3.2 Latency budget and deadline

| Item | Value |
|---|---|
| slot | every 5 min, 09:30-15:55 ET |
| dispatch SLO | request written ≤ 10 s after the slot |
| start SLO | spawned ≤ 15 s after the slot; the realtime worker wakes on the request, not on the 5 s poll |
| soft budget | catalysts stop at deadline − `post_enrich_reserve_s` (100 s) |
| hard deadline | 295 s (`timeout_s`), with SIGKILL at 325 s (`-k 30`) |
| expiry | a request not started by slot + 60 s is never run: `RUN_EXPIRED` (counted MISSED) |

**Executor concurrency request (to B3 and Agent 2):**
- **Allowlist:** `class: "realtime"` and `start_deadline_s: 60`.
- **Executor config:** `workers {realtime: 1, default: N, global_max: N+1}`.
  - The realtime slot is **dedicated**: only `class: realtime` rows may use it, and no other class can borrow it, so a 5-min lane never queues behind a long job.
  - The executor also refuses a second `RUNNING` row for the same `lane_id`.
- **Ledger:**
  - `claim_next(class=…)`;
  - a nullable `not_after` (= requested_at + start_deadline_s);
  - a new finished state `RUN_EXPIRED`.
- **Dead-letter queue:** rows past `retry.max`, and `RUN_REFUSED` rows, go to the dead-letter queue. A scalp `RUN_EXPIRED` is **not** dead-lettered, because the next slot replaces it.
- **Retry backoff** must leave the claim loop: re-enqueue with `not_before` instead of `sleeper()` inline.

### 3.3 Retry policy (this lane)
- `retry` stays absent (`max 0`), and the lane never retries `RUN_TIMEOUT` or `RUN_FAILED`. The send happens inside the cycle, so a killed or failed cycle may already have alerted.
- The only retry is a **dispatch-level re-request**, and only when all of these hold:
  - the relay never acknowledged the request (transport error);
  - remaining window (slot + 60 s − now) ≥ 45 s;
  - the request reuses the **same idempotency key**, so the ledger dedupes it.
- Otherwise the slot is MISSED.
- `RUN_SKIPPED_LOCK` (exit 75) means a cycle is already running. It is `SKIPPED_LOCKED`, never a failure, never retried.

### 3.4 Alert dedupe (preserve all of it)
- **Trade-AI GO dedupe:**
  - `CycleState` (`continuous_runner.py`) alerts on `go_now − prev_go`, plus first-seen HALT, RVOL 5x and RVOL 8x;
  - the state persists per ET day in `state/trade_ai_scalp_live_state.json`;
  - after this PR it is saved **before** the send.
- **Active Trader:** its own `Throttle` (`scripts/active_trader/momentum_alerts.py`), keyed on symbol + kind + level with a 900 s cooldown and an hourly cap.
- **The n8n path must keep:**
  1. **One writer** of the state file: the runner, under the shared flock. Cron and n8n can never run a cycle at the same time.
  2. **The host chokepoint** `send_telegram`. n8n never sends (§23.3).
  3. **Idempotency key** `slot:trade-ai-scalp-live:<YYYY-MM-DD>T<HH:MM>`, set by the dispatcher. The generated per-lane workflow sends no key, which is a gap. The relay honours `idempotency_key`.
  4. **The slot guard** from this PR, so a cron cycle and an n8n cycle never both complete one slot.
- Receipts record `alerts_sent` and `alerts_deduped`: GO names this cycle that had already alerted today.

---

## 4. Monitoring (implemented in this PR)

### 4.1 `ScalpCycleReceipt@v1` (`scripts/lib/scalp_cycle_receipt.py`)
- **Where:** one JSONL per ET day, `<state root>/data/runtime/scalp_cycle_receipts/<day>.jsonl`. Each record is appended and fsynced.
- **Fields:** `schema`, `lane_id`, `cycle_id` (`lane:day:HHMM`), `date`, `slot`, `status` (`started|ok|error|killed`), `phase`, `started_at`, `finished_at`, `seconds`, `symbols_scanned`, `signals` (GO count), `triggers`, `alerts_sent`, `alerts_deduped`, `budget {deadline_s, enrich_budget_s, used_s, used_pct}`, `errors[]`, `scheduler` (`cron|n8n`; n8n when `TRADEAI_RUN_ID` is set), `run_id`, `release`, `pid`.
- **Folding:** the monitor folds records per slot. An `ok` is never hidden by a later failed retry. A `started` with no final record reads as `lost`.
- The legacy `TradeAIScalpLiveReceipt@v1` (the last-run file, read by fan-in 3g and the registry output_signal) is unchanged. It now also records `error` cycles.

### 4.2 Heartbeat and incident rules (`scripts/lib/scalp_cycle_monitor.py`)
- **Expected slots:** every 5-min slot whose start is in the **regular session**. None on weekends or holidays; 42 on early closes.
- A slot is **due** at slot start + 295 s. It is OK only with a final `ok` inside the deadline. `missing`, `lost`, `killed`, `error` and `late` are MISSED.
- **Stale:** only during RTH, when the last OK finished more than **2× cadence (10 min)** ago. There is a grace period after the open. It is never stale outside RTH.
- **P2 `trade-ai-scalp-live:MISSED_CYCLES`:** the latest due slots end in ≥ 2 consecutive misses.
- **P1 `trade-ai-scalp-live:NO_CYCLES_30M`:** ≥ 30 min of RTH without an OK cycle.
- **Incident shape:** each incident uses the fan-in shape with `detected_at` = the day, so the incident router dedupes it to one event per day.
- **Wiring:** `scripts/n8n_incident_fanin.py` gains **source 3h**, which runs these rules on today's ledger. It stays silent until the ledger exists, so a release without B4 never pages. Source 3g (`STALLED`, last_ok > 12 min) stays as the coarse backstop.
- **The 6-workflow heartbeat watcher** should call the same `evaluate()`, or `check_scalp_cycles.py --exit-code`, rather than a generic 2×cadence mtime rule. The generic rule pages every night for an RTH-only lane.

### 4.3 Command Center and digest line
- Command: `scripts/check_scalp_cycles.py [--date D] [--json] [--write] [--exit-code]`.
- `--write` writes `data/runtime/scalp_cycle_monitor_last.json` (`ScalpCycleMonitor@v1`).
- `summary_line` is the one-liner for the 10/15/17 ET digests and the CC ops strip, for example:

  `Scalp lane 2026-10-12: 76/78 RTH cycles ok (97%), median 142s, max 231s/295s, 1 GO signals, alerts 1 sent/3 deduped; last ok 2.1 min ago; CLEAN day`

- **Exit codes:** 2 on P1, 1 on P2, else 0.

### 4.4 Runbook: manual warm-up or test runs
**Never hold the lane lock without a timeout.** Use one of:
- `flock -n /tmp/tradeai_scalp_live.lock timeout 295 …`
- `--dry-run`
- a scratch `TRADEAI_STATE_ROOT`

Today, two manual no-timeout runs cost 9 slots.

---

## 5. Registry rows for Agent A's registry train

B1 holds the registry lock, so B4 does not edit `config/lane_registry.json`.

**(a) Amend `trade-ai-scalp-live`.** Add these fields and keep everything else as on main:

```json
{
  "lane_id": "trade-ai-scalp-live",
  "scheduler": {"kind": "cron", "cron": "*/5 9-15 * * 1-5", "tz": "America/New_York"},
  "dispatch": {"gate": "rth_regular", "class": "realtime", "slot_s": 300, "deadline_s": 295,
               "start_deadline_s": 60, "fire_offset_s": 0, "retry": {"max": 0}},
  "cycle_monitor": {"kind": "scalp_cycle_ledger", "path": "data/runtime/scalp_cycle_receipts",
                    "schema": "ScalpCycleReceipt@v1", "stale_after_min_rth": 10,
                    "p2_consecutive_missed": 2, "p1_rth_gap_min": 30,
                    "clean_day": {"ok_rate_min": 0.95, "max_p2_episodes": 1, "max_rth_gap_min": 30}}
}
```

**(b) New rows for lines that today are only in `undeclared_baseline`.** All have `owner: "scalp"` and `state: "ACTIVE"`; the `expression` is the exact crontab text.

| lane_id | expression (crontab) | match | cadence h | output_signal (state-root relative) | n8n class |
|---|---|---|---|---|---|
| social-scalp-scanner | `0,30 6-9 * * 1-5 cd $PROJ && flock -n /tmp/social_scalp.lock $PY scripts/social_scalp_scanner.py >> logs/social_scalp_scanner.log 2>&1` | scripts/social_scalp_scanner.py | 0.5 | file_mtime `logs/social_scalp_scanner.log` | DISPATCHER_ELIGIBLE after a sender exception |
| catalyst-momentum-premarket-scalp | `*/30 4-9 * * 1-5 cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/catalyst_premarket.lock $PY scripts/catalyst_momentum_engine.py --band premarket_scalp --apply --generate-proposals >> logs/catalyst_momentum_engine.log 2>&1` | `catalyst_momentum_engine.py --band premarket_scalp` | 0.5 | file_mtime `data/cio/catalyst_momentum_last_run.json` | KEEP_ON_CRON_WATCHED |
| catalyst-momentum-market-swing | `30 9-15 * * 1-5 cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/catalyst_swing.lock $PY scripts/catalyst_momentum_engine.py --band market_swing --apply --generate-proposals >> logs/catalyst_momentum_engine.log 2>&1` | `catalyst_momentum_engine.py --band market_swing` | 1 | same | KEEP_ON_CRON_WATCHED |
| reclassify-momentum-proposals | `*/30 9-16 * * 1-5 cd $PROJ && flock -n /tmp/reclassify_momentum.lock $PY scripts/reclassify_momentum_proposals.py --apply >> logs/reclassify_momentum.log 2>&1` | scripts/reclassify_momentum_proposals.py | 0.5 | file_mtime `logs/reclassify_momentum.log` | DISPATCHER_ELIGIBLE |
| momentum-scalp-validation-fast-path | `*/2 6-11 * * 1-5 cd $PROJ && flock -n /tmp/momentum_scalp_validation_fp.lock $PY scripts/momentum_scalp_validation_fast_path.py --dry-run >> logs/momentum_scalp_validation_fast_path.log 2>&1` | scripts/momentum_scalp_validation_fast_path.py | 0.034 | file_mtime `logs/momentum_scalp_validation_fast_path.log` | KEEP_ON_CRON_WATCHED |
| sec-form4-momentum-context | `45 5 * * 1-5 cd $PROJ && flock -n /tmp/tradeai_sec_form4_ctx.lock $PY scripts/run_sec_form4_momentum_context.py --apply >> logs/sec_form4_momentum_context.log 2>&1` | scripts/run_sec_form4_momentum_context.py | 24 | file_mtime `logs/sec_form4_momentum_context.log` | DISPATCHER_ELIGIBLE |
| scalp-volume-profile-refresh | `30 20 * * 1-5 cd $PROJ && bash $PROJ/scripts/run_scalp_volume_profile_refresh.sh >> logs/scalp_volume_profile.log 2>&1` | scripts/run_scalp_volume_profile_refresh.sh | 24 | file_mtime `logs/scalp_volume_profile.log` | DISPATCHER_ELIGIBLE (after the wrapper uses `$PROJ`) |
| scalp-shadow-logger | `*/5 6-11 * * 1-5 cd $PROJ && bash $PROJ/scripts/run_scalp_shadow_logger.sh >> logs/scalp_shadow_logger.log 2>&1` | scripts/run_scalp_shadow_logger.sh | 0.084 | file_mtime `logs/scalp_shadow_logger.log` (RTH-only, `active_days [0..4]`) | KEEP_ON_CRON_WATCHED until a sender exception |

All of these keep `kind: cron`. The two stale baseline entries (sec-form4 `15 9`, social `0 10-16`) no longer match the crontab and should be dropped from the baseline.

**(c) Daemon watch row (no registry row exists today):**

```json
{"lane_id": "tradeai-active-trader-motion", "owner": "scalp",
 "scheduler": {"kind": "systemd_service", "expression": "tradeai-active-trader-motion.service",
               "match": "active_trader.motion_runtime"},
 "expected_cadence_hours": 0.0167, "active_days": [0, 1, 2, 3, 4], "state": "ACTIVE",
 "output_signal": {"kind": "file_mtime", "path": "data/active_trader/motion_heartbeat.json",
                   "root": "dev_tree", "note": "journal/heartbeat live in the dev tree, not the state root"},
 "n8n": "WATCH_ONLY",
 "note": "Release-pinned to a032116e7 by drop-in 10-user-exact-sha.conf; do not prune that release dir. Notifier only; authority flags all false."}
```

B1 must confirm the exact heartbeat filename against the dev tree's `data/active_trader/` before committing this row.

---

## 6. Cutover wave placement

- **The gate is 3 clean market days.** The program's generic bar is **2 clean RTH days in shadow**. AGENTS.md 4.0.0 §23.3 requires **3 market days** of n8n `RUN_DONE` with no `STALLED` before the cron line retires. **The stricter rule governs.**
- **Wave:** scalps go in the **first (early) wave**, alone, under `class: realtime`, and only after both of these:
  - (a) **2 clean RTH days in shadow**, with the dispatcher firing `--dry-run`;
  - (b) **3 clean live market days**, with the n8n canary and cron still present.
- **Clean RTH day** (`check_scalp_cycles.py` `clean_day: true`, plus the ledger):
  - ≥ 95% of regular-session slots have a `ScalpCycleReceipt@v1` `ok` within 295 s;
  - no 30-min RTH gap (no P1);
  - ≤ 1 P2 episode;
  - 0 duplicate GO alerts for one symbol in a day;
  - 0 slots with two `ok` cycles;
  - dispatcher starts ≤ 15 s after the slot.
- **Steps:**
  1. Promote a release carrying this PR and af9199ff4.
  2. Measure Monday with cron alone (baseline clean-day verdict).
  3. Shadow for 2 days.
  4. Canary: relay `TRADEAI_N8N_RELAY_LIVE_LANES` plus a workflow-id grant (config-write).
  5. Wait for 3 clean days.
  6. Cut over with `_cutover.py --lane trade-ai-scalp-live` under a cron grant. The line is commented `# RETIRED <date> n8n-cutover`, never deleted, and the registry kind becomes `n8n`.
  7. Update `tests/test_agents_policy_4_0_0_scalp_lane.py`, which asserts `kind == "cron"`.
- **Rollback, per line:**
  1. Uncomment the line (cron grant).
  2. Remove the lane from the relay live list and the dispatcher (`dispatch.enabled: false`).
  3. Set the registry back to `kind: cron`, with a cutover receipt.
- **Rollback triggers:** any P1, a P2 `MISSED_CYCLES`/`STALLED`, more than 4 MISSED in a day, or a duplicate GO alert.

**Open decisions for Agent A and the operator:**
1. **Workflow-id grant vs the generic dispatcher.** 4.0.0 names a per-lane workflow id. Either keep the dedicated generated `trade-ai-scalp-live` workflow for this one lane, or have 3.1.0 say that a registry-row PR plus the relay live listing satisfies it.
2. **"3 days of RUN_DONE" is mostly unreachable while cron is live.** Cron fires at the same minute and usually wins the flock, so n8n records `RUN_SKIPPED_LOCK`. The options:
   - a temporary cron offset `2-57/5` (cron grant), so n8n leads and cron is the true fallback; the slot guard makes cron's late run a no-op;
   - define the canary as "every slot done by exactly one runner", which the ledger's `scheduler` field proves.
3. **Executor readiness.** The serial executor, inline retry sleep, FIFO claim and missing expiry conflict with "a realtime lane never queues". B3 and Agent 2 must land the class and worker change before the scalp canary.
4. **Active Trader afternoon coverage** (§1.2).
