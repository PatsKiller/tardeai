# Pipeline time settings — measured, pinned, and why

```
Status:      ACTIVE
as_of:       2026-10-22T17:30-04:00
Measured at: production CURRENT 82180caba (read-only: pipeline_runs, CURRENT/logs/process_reaper.jsonl,
             persistent-state/data/runtime/health_tick_history.jsonl); code at origin/main b9804fa57
```

**Rule.** Do not lower any setting on this page without new measured runtime evidence: the query, the
window, and its output, in the PR. Every number below was cut once already to a value nobody had
measured, and each cut showed up as live `pipeline_critical` SIGTERM failures. The settings are pinned
by `tests/test_pipeline_time_settings_20261022.py`. A PR that changes one must change the test, this
page, and the evidence together.

Operator direction, 2026-10-22 (verbatim): "Yes, do that. And also, update the agents.md and
documentation with the proper time settings. So another agent doesn't come behind and do that."

## The settings

| Setting | Where | Value | Was | Bound it protects |
|---|---|---|---|---|
| `max_runtime_min` for `trade_ai_orchestrator` | `config/process_reaper_policy.json`, plus the fallback `DEFAULT_RULES` in `scripts/process_reaper.py` (they must be equal) | **30** (1800 s) | 20 | Market-hours orchestrator runtime: ≥ 1377 s (censored floor) |
| `run_full_cycle` subprocess timeout | `scripts/continuous_runner.py` | **2700 s** (45 m) | unchanged | Must stay above the reaper cap |
| `ENRICHMENT_BATCH_TIMEOUT_S` | `scripts/pipeline_watchdog.py` (env `WATCHDOG_ENRICHMENT_BATCH_TIMEOUT_S`) | **240 s** | none (fire-and-forget) | Enrichment p95 241 s |
| `ENRICHMENT_RESERVE_S` / `ENRICHMENT_TERM_GRACE_S` | `scripts/pipeline_watchdog.py` | **15 s / 5 s** | new | SIGTERM grace 5 + SIGKILL reap 2 + receipts 8 |
| `HEALTH_TICK_STEP_TIMEOUT_S` | exported to every step by `scripts/health_tick.py` `run_step` | the step's clamped timeout | new | Lets a step finish its own children before the tick kills it |
| `pipeline-watchdog` step position | `config/health_tick_steps.json` | **last** | 4th | Waiting for enrichment must not spend the tick of the steps after it |
| `orphan_wait_s` | `config/health_tick_steps.json`, `DEFAULT_ORPHAN_WAIT_S` in `scripts/health_tick.py` | **30 s** | unchanged | Legacy fire-and-forget children only |
| `tick_budget_s` / `tick_deadline_s` | `config/health_tick_steps.json` | **280 / 300 s** | unchanged | Below the unit timeout |
| `TimeoutStartSec` | `tradeai-health-tick.service` (`config/systemd/user/`) | **330 s** | unchanged | 300 + `KILL_GRACE_S` 10 + receipt |

## 1. Orchestrator reaper cap: 30 minutes

**Failure.** On 2026-10-21 and 2026-10-22, every market-hours (09:00–15:59 ET) `trade_ai_orchestrator`
run failed `terminated by SIGTERM` at 1216–1377 s. The 10-21 market band had 20 failed and 1 success;
the 10-22 market band had 22 failed. The killer is `process_reaper` (`CURRENT/logs/process_reaper.jsonl`:
`1 over runtime cap 20m (…@20m–23m)`, about every 24 minutes). The reaper runs on a few-minute cadence,
which is why kills land between 20 and 23 minutes. `continuous_runner.py` relaunches the orchestrator as
soon as it dies, so each run was killed and replaced in a loop.

The short kills of about 25–50 s are a different mechanism. The reaper logged them as
`pile-up 2 > max_concurrent 1 (reaping 1 newest dup(s))`. A second launcher, for example the 17:30
`run_orchestrator_slot.sh` cron line, started a copy while the long run was alive. That rule is correct
and was not changed.

**Evidence** `[VERIFIED]` 2026-10-22. The query was run read-only with
`env -u PGPASSWORD psql -h localhost -U trade_ai -d trade_ai`:

```sql
SELECT (started_at AT TIME ZONE 'America/New_York')::date d,
       CASE WHEN extract(hour from started_at AT TIME ZONE 'America/New_York') BETWEEN 9 AND 15
            THEN 'mkt' ELSE 'off' END band, status, count(*), round(max(duration_seconds)) mx
FROM pipeline_runs WHERE pipeline_key='trade_ai_orchestrator'
  AND coalesce(run_label,'')<>'health_recovery' AND started_at > now()-interval '14 days'
GROUP BY 1,2,3 ORDER BY 1,2,3;
```

| date | band | status | n | max s |
|---|---|---|---|---|
| 2026-10-13 | mkt | success | 1 | 1264 |
| 2026-10-15 | mkt | success | 1 | 1269 |
| 2026-10-21 | mkt | failed | 20 | 1372 |
| 2026-10-21 | mkt | success | 1 | 119 |
| 2026-10-22 | mkt | failed | 22 | 1348 |
| 2026-10-22 | off | failed | 21 | 1377 |
| 2026-10-22 | off | success | 20 | 837 |

**Read it correctly: 1377 s is a floor, not p100.** Every run longer than about 20–23 minutes was
killed, so no run longer than that has ever been allowed to finish. The longest uncensored market-hours
completion is 1269 s (2026-10-15). Overnight runs finish in 180–840 s.

**Choice.** 30 min = 1800 s. That is 423 s over the censored floor and 531 s over the longest
uncensored completion. It also stays under `continuous_runner.py`'s own 2700 s hard limit, so a real
hang is still reaped about 15 minutes before the runner gives up.

**Re-measure after deploy.** The first week of uncensored runs is the first real distribution. If
market-hours runs are reaped at 30 m, raise the cap on that evidence; never go back toward 20. If they
finish well inside, a lower cap still needs that measured distribution in the PR.

Cherry-picked from `30a70e59a` ("fix: align orchestrator reaper cap with measured runtime").

## 2. Symbol enrichment children: supervised, bounded, watchdog runs last

**Failure.** `scripts/pipeline_watchdog.py` `run_ier_engine()` used `Popen` to start up to 15 detached
`scripts/symbol_enrichment.py <eid> <score>` children and exited. Since 2026-10-08 it runs as a step of
`tradeai-health-tick.service` (Type=oneshot, KillMode=control-group, TimeoutStartSec=330).
`health_tick.py` reaps whatever a step leaves in its process group after `orphan_wait_s: 30`. Over the
36 h to 2026-10-22 that gave `symbol_enrichment` **224 failed / 1 success**, with every failure at
29–33 s. Daily failures had run at about 150–180 since 2026-10-10. The rare successes, 22–27 s, are just
the children that happened to finish inside 30 s.

**The real runtime is not 25–50 s.** That figure is survivor bias from the 30 s kill. The uncensored
distribution comes from the cron era, before the health tick, when the children outlived their parent:

```sql
SELECT count(*), percentile_cont(ARRAY[.1,.25,.5,.75,.9,.95]) WITHIN GROUP (ORDER BY duration_seconds),
       max(duration_seconds)
FROM pipeline_runs WHERE pipeline_key='symbol_enrichment' AND status='success'
  AND started_at > '2026-09-20' AND started_at < '2026-10-08';
-- n=3178  p10 69  p25 101  p50 136  p75 168  p90 209  p95 241  max 419 (seconds)
-- share finishing within 120 s: 37%; 150 s: 61%; 180 s: 81%; 240 s: 95%
```

**Fix** (cherry-picked from `481d10dc1` "fix: supervise watchdog symbol enrichment children", then
fitted to the tick):

- Each child starts in its own session (`start_new_session=True`). `health_tick`'s orphan reaper works
  on the step's process group, so it no longer sees these children. The watchdog waits for them and
  records `trigger_enrichment` with the real result: `completed`, `exit=<rc>` or `batch_timeout`.
- The wait is `min(ENRICHMENT_BATCH_TIMEOUT_S = 240 s, HEALTH_TICK_STEP_TIMEOUT_S − time used − 15 s)`.
  When it runs out, the watchdog SIGTERMs the child groups, waits 5 s, SIGKILLs them and reaps them
  itself. If the tick SIGTERMs the watchdog, the handler does the same within 7 s, inside the tick's
  10 s `KILL_GRACE_S`.
- A per-symbol PostgreSQL advisory lock in `enrich_symbol()` stops two writers enriching one symbol
  together. The 4-hour claim is taken atomically before each spawn.
- **`pipeline-watchdog` is now the last step of the tick.** At 4th place, a watchdog that waits up to
  240 s would spend the 280 s start budget, and every step after it would be deferred: health-agent,
  cron-self-heal, siem-critical-notify, log-error-scraper, system-freshness-monitor,
  freshness-watchdog-heartbeat and pipeline-liveness-report. Each deferral makes that tick `broken`.

**Arithmetic.** Measured from `health_tick_history.jsonl`, 161 undeferred even-hour ticks, 2026-10-07 to
2026-10-22. The other steps of a tick took **p50 40 s, p95 90 s, max 246 s**.

- The watchdog starts at about 40 s (p50) or 90 s (p95).
- That is always under the 280 s start budget, max 246 s, so it is never deferred.
- Its clamped timeout is 300 − start − 10, which is about 250 s (p50) or 200 s (p95).
- The enrichment wait is then min(240, 250 − 15) = 235 s (p50), or min(240, 200 − 15) = 185 s (p95).
  At the measured distribution, that completes about 95% or about 81% of children.
- Worst case for the unit: tick deadline 300 + kill grace 10 + receipt < `TimeoutStartSec` 330.

**Known residue, not fixed here:**

- The 08:00 tick: the watchdog's own non-enrichment work, the daily summary and retries, already took
  270–288 s at 08:00 on 10-20, 10-21 and 10-22. That tick was `broken` before this change and stays
  tight.
- A child that hits `batch_timeout` keeps its 4-hour claim.
- The structural fix is to give enrichment its own execution context, its own unit or an n8n lane,
  outside the 5-minute tick. That is a scheduling change, so it goes to the operator.

`orphan_wait_s` stays at 30 s. It is the outer safety net for legacy fire-and-forget children. **Do not
raise it to make a slow step's children survive.** It is paid once per step against the shared 300 s
tick. Make the step supervise its children instead.

## 3. The "Error: []" alert

`remediate_pipeline_failures.py` settles a run that never closed with summary
`{"errors": [], "note": "zombie run cleared", "cleared_by": "remediate_pipeline_failures", …}`.
`alert_dispatcher_unified.check_pipeline_critical()` read `summary->>'errors'`, which is the literal
`[]`, and sent `Pipeline FAILED: trade_ai_orchestrator (…). Error: []`.

The query now uses the same precedence as `scripts/lib/pipeline_failures.py`: a non-empty `errors`,
then `error`, then `note || ' by ' || cleared_by`. The alert reads
`Error: zombie run cleared by remediate_pipeline_failures`. The run was verified read-only against the
live table for the 36 h to 2026-10-22. It produced 18 such orchestrator rows, 15 for symbol_enrichment
and 32 for finviz_screener_runner.

## How to change any of this

1. Measure first. Use the queries above, or the equivalent, over at least one full trading week. Do
   not count values censored by the cap you are about to change as runtimes.
2. Change the setting, this page's table, and `tests/test_pipeline_time_settings_20261022.py` in one
   PR, with the query output in the PR body.
3. For the health tick: re-run the arithmetic in section 2 against `health_tick_history.jsonl` and keep
   `tick_deadline_s + KILL_GRACE_S + receipt < TimeoutStartSec`.
