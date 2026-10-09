# Cron consolidation RANK 3 — the health tick (proposal), 2026-10-07

Seventeen crontab entries (the operator's list says "16 lines"; the list itself has 17 bullets, all
absorbed) that each poll, probe or monitor something become ONE user timer, `tradeai-health-tick.timer`
(`OnCalendar=*:0/5`), running `scripts/health_tick.py --apply` from CURRENT. The tick reads
`config/health_tick_steps.json` (`HealthTickSteps@v1`), computes which steps are due on this 5-minute
boundary with cron-equivalent arithmetic, runs them sequentially under each line's own `/tmp` flock and a
per-step timeout, appends their output to the same `logs/*.log` files the cron lines appended to, and
writes `data/runtime/health_tick_last.json` (`HealthTickReceipt@v1`) plus one line in
`data/runtime/health_tick_history.jsonl`. ~~Exit 1 when a due step failed or timed out.~~ Superseded
2026-10-09 — see "Exit codes" below.

## Exit codes (2026-10-09, n8n maturity B3.1)
The unit's exit code reports the health of the **tick**, not of the system the monitors watch.

| exit | meaning | receipt |
|---|---|---|
| 0 | the tick ran its table: every due step completed or was lock-skipped. Monitors may have FOUND problems | `status: healthy` or `unhealthy`; `findings: [step…]`; rows `outcome: finding` |
| 1 | the tick is broken: a due step crashed, timed out, could not spawn, was deferred, or the receipt failed | `status: broken`; `broken: [step…]` |
| 2 | cannot run (table unreadable, bad arguments) | none |

A step declares which exit codes mean "I ran and found something" with `finding_rc` (today `[3]` for
system-health-agent, moomoo-opend-health and pipeline-liveness-report). `finding_rc` may not contain 1:
CPython exits 1 for an uncaught exception and for `sys.exit("fatal ...")`, and a crash cannot be told from
a finding by parsing the last stderr line (a psycopg2 `OperationalError` ends in a second message line, a
bare `StopIteration` has no message, a traceback can be followed by more output). So those three monitors
now exit `EXIT_FINDING = 3` (`scripts/lib/monitor_exit_codes.py`) for a finding, rc 1 from any step is a
crash, and any `Traceback (most recent call last):` header in a step's stderr is a crash whatever its rc.
No other caller depended on their rc 1 (crontab, systemd units, n8n and CI were grepped on 2026-10-09;
under cron the exit went only to a log). `ok`/`failed` keep their old meaning ("everything green") for
back-compat; `tick_ok`/`broken`/`findings`/`status` are new.

Why: from 2026-10-07 to 10-09 the unit failed ~265 times. 225 of those were system_health_agent
correctly reporting a critical component (Pipeline Watchdog) stale — and that component was stale
*because* the tick was being killed: `portfolio_live_monitor.py` is a market-hours daemon that ran into
its 300 s timeout on every firing, pushing every hourly tick past `TimeoutStartSec=330`, so systemd
killed the tick before `pipeline-watchdog` (due :00 of even hours) ran or the receipt was written. On the
even-hour ticks that did finish, `pipeline_watchdog.py`'s fire-and-forget `symbol_enrichment.py` children
outlived the tick and systemd ended the unit `Result=timeout` after a clean receipt. Fixes: the live
monitor runs `--once`; `tick_deadline_s` (300) clamps every step timeout so the tick always outlives its
steps; leftover process-group members get `orphan_wait_s` (30) and are then terminated and recorded
(`orphans`, `orphans_terminated`). Real unhealthiness still surfaces: in the receipt
(`status: unhealthy`), in each monitor's own escalation/alert path, and in the lane monitors that read
those monitors' outputs; `systemctl --failed` / health_agent's `systemd_unit_failed` now mean what they
say — the scheduler is broken.

**Nothing in this PR is installed.** The unit files carry a PROPOSAL ONLY header, the lane row is
`NEVER_SCHEDULED`, the crontab is untouched. Every action below is an operator step under a grant.

## What stays in cron (by design)
| line | why |
|---|---|
| 393 `*/2 … portfolio_server_watchdog.sh` | safety net; must not share a process with what it watches |
| 636 `*/3 … process_reaper.py` | safety net; reaps hung batch jobs, including (potentially) a wedged tick step |
| 241 `*/5 … cleanup_stale_locks.sh` | safety net; clears the very `/tmp/*.lock` files the tick depends on |
| 914 `20 * … resolve_due_checkpoints.py --apply --apply-pending-data` | declared lane with its own semantics (TRADEAI_PENDING_DATA_APPLY) |
| 843 `@reboot … systemctl --user start trade-ai-lab-moomoo-opend.service` | boot hook, not a cadence |

## Mapping table (read verbatim from `crontab -l` on 2026-10-07; `$PROJ`=CURRENT, `$PY`=dev venv python)
| crontab line | step_id | schedule (cron) | tick schedule | lock | timeout_s | gate | log |
|---|---|---|---|---|---|---|---|
| 344 | system-health-agent | `*/5 9-20 * * 1-5` `system_health_agent.py --apply --verbose` | every 5 min, hours 9-20, Mon-Fri | `/tmp/health_tick_system_health_agent.lock` (added) | 240 | — | logs/system_health_agent.log |
| 842 | moomoo-opend-health | `*/5 6-17 * * 1-5` `flock -n /tmp/moomoo_opend_health.lock` `moomoo/opend_health.py --alert` | every 5 min, hours 6-17, Mon-Fri | `/tmp/moomoo_opend_health.lock` | 120 | — | logs/moomoo_opend_health.log |
| 1007 | cio-bridge-watchdog | `*/5 * * * *` `flock -n /tmp/cio_bridge_watchdog.lock` `cio_bridge_watchdog.py --apply` | every tick | `/tmp/cio_bridge_watchdog.lock` | 120 | — | logs/cio_bridge_watchdog.log |
| 598 | health-agent | `*/15 * * * *` `/usr/bin/flock -n /tmp/health_agent.lock` `health_agent.py` | :00 :15 :30 :45 | `/tmp/health_agent.lock` | 600 | — | logs/health_agent_cron.log |
| 901 | cron-self-heal | `*/15 6-20 * * 1-5` `cron_self_heal.py --apply` | :00/15, hours 6-20, Mon-Fri | `/tmp/health_tick_cron_self_heal.lock` (added) | 300 | — | logs/cron_self_heal.log |
| 420 | siem-critical-notify | `*/15 * * * *` `siem_critical_notify.py` | :00/15 | `/tmp/health_tick_siem_critical_notify.lock` (added) | 240 | — | logs/siem_critical_notify.log |
| 419 | log-error-scraper | `*/20 * * * *` `log_error_scraper.py` | :00 :20 :40 | `/tmp/health_tick_log_error_scraper.lock` (added) | 240 | — | logs/log_error_scraper.log |
| 437 | system-freshness-monitor | `*/20 * * * *` `flock -n /tmp/system_freshness_monitor.lock` `system_freshness_monitor.py --send --auto-fix` | :00 :20 :40 | `/tmp/system_freshness_monitor.lock` | 600 | — | logs/system_freshness_monitor.log |
| 403 | portfolio-live-monitor | `*/20 9-16 * * 1-5` `flock -n /tmp/portfolio_live_monitor.lock` `portfolio_live_monitor.py` | :00/20, hours 9-16, Mon-Fri | `/tmp/portfolio_live_monitor.lock` | 300 | — | logs/portfolio_live_monitor.log |
| 439 | freshness-watchdog-heartbeat | `*/30 * * * *` `flock -n /tmp/freshness_watchdog_heartbeat.lock` `freshness_watchdog_heartbeat.py --send` | :00 :30 | `/tmp/freshness_watchdog_heartbeat.lock` | 240 | — | logs/freshness_watchdog_heartbeat.log |
| 909 | pipeline-liveness-report | `*/30 * * * *` `pipeline_liveness_report.py --fail-on-finding` | :00 :30 | `/tmp/health_tick_pipeline_liveness_report.lock` (added) | 300 | — | logs/pipeline_liveness.log |
| 277 | pipeline-watchdog | `0 */2 * * *` `pipeline_watchdog.py` | :00 of even hours | `/tmp/health_tick_pipeline_watchdog.lock` (added) | 600 | — | logs/pipeline_watchdog.log |
| 628 | pipeline-freshness-monitor | `20 */4 * * *` `flock -n /tmp/pipeline_freshness.lock` `pipeline_freshness_monitor.py --send` | :20 of hours 0,4,8,12,16,20 | `/tmp/pipeline_freshness.lock` | 300 | — | logs/pipeline_freshness.log |
| 491 | pipeline-freshness-slo | `15 7-17/2 * * 1-5` `pipeline_freshness_slo.py --telegram` | :15 of hours 7,9,11,13,15,17, Mon-Fri | `/tmp/health_tick_pipeline_freshness_slo.lock` (added) | 300 | — | logs/freshness_slo.log |
| 1024 | llm-provider-health | `20 * * * *` `check_llm_provider_health.py` | :20 every hour | `/tmp/health_tick_llm_provider_health.lock` (added) | 240 | — | logs/llm_provider_health.log |
| 1042 | symbol-news-curation-monitor | `27 * * * *` `flock -n /tmp/symbol_news_curation_monitor.lock` `symbol_news_curation_monitor.py --apply` | **:25** every hour (:27 snapped to the grid, 2 min early) | `/tmp/symbol_news_curation_monitor.lock` | 600 | — | logs/symbol_news_curation_monitor.log |
| 178 | system-health-alerts | `10 12,15 * * 1-5` `bash scripts/market_day_gate.sh $PY system_health_alerts.py` | :10 of hours 12 and 15, Mon-Fri | `/tmp/health_tick_system_health_alerts.lock` (added) | 240 | `bash scripts/market_day_gate.sh` prefixed verbatim | logs/system_health_alerts_cron.log |

Every argument is preserved; `(added)` marks a lock the cron line did not have (overlap protection the
tick adds; harmless because each script is already idempotent-by-design or dedup-guarded). `needs_env`
is `false` on every row: no absorbed line sourced anything — each script loads `CURRENT/.env` itself
(`CURRENT/.env` → the dev-tree `.env` symlink), and the crontab header variables (`PROJ`, `PY`,
`LLM_DEFER_OFFPEAK=1`, `TRADEAI_ENV=/run/user/1000/tradeai/env`, `BLIND_REVIEW_LANES`) are reproduced as
`Environment=` lines in the service.

## Expected firing reduction
Scheduler invocations per week, computed by the planner itself (`scripts/health_tick.py --week-plan
--now 2026-10-05T00:00:00`) and cross-checked by hand from the cron fields:

| | weekday/day | weekend day/day | per week |
|---|---|---|---|
| 17 cron lines today (cron forks: `sh -c`, `flock`, python) | 1,166 | 786 | **7,402** |
| one timer (`*:0/5`) | 288 | 288 | **2,016** |

Scheduler firings drop 7,402 → 2,016 per week (−72.8%). The monitor scripts themselves still run the same
7,402 times (the cadences are preserved exactly, except `:27 → :25`); what disappears is 17 independent
cron entries with no receipt, replaced by one declared lane whose receipt says per tick which step was
due, ran, skipped on lock, timed out, or was deferred. Per-step counts: cio-bridge-watchdog 2,016;
system-health-agent 720; moomoo-opend-health 720; health-agent 672; siem-critical-notify 672;
log-error-scraper 504; system-freshness-monitor 504; freshness-watchdog-heartbeat 336;
pipeline-liveness-report 336; cron-self-heal 300; llm-provider-health 168;
symbol-news-curation-monitor 168; portfolio-live-monitor 120; pipeline-watchdog 84;
pipeline-freshness-monitor 42; pipeline-freshness-slo 30; system-health-alerts 10.

## Behavioural differences the operator should accept or veto
1. **Sequential within a tick.** The heaviest 5-minute tick (:00 of an even hour, Mon-Fri 9-16) carries
   12 due steps (`--dry-run --now 2026-10-07T12:00:00` → `due=12`). Each has its own timeout, and `tick_budget_s=280` defers whatever has not started
   by then (recorded as `deferred`, counted as a failure so it is visible). A deferred step is simply due
   again at its next cadence. If the first live week shows deferrals, raise `max_parallel` to 2-3 in the
   table (`--max-parallel` also exists for a one-off) — no code change.
2. **Independence caveat.** `freshness_watchdog_heartbeat.py` watches `system_freshness_monitor.py`; they
   now share the tick process. The heartbeat still runs in its own subprocess under its own lock, but a
   dead *timer* silences both. The lane registry's cadence check on `health_tick_last.json` (0.083 h) is
   the watcher of the tick; `cleanup_stale_locks.sh`, `process_reaper.py` stay outside it.
3. **`:27 → :25`** for symbol-news-curation-monitor (hourly, bounded LLM calls; the 2 minutes do not
   change its SLA window).
4. **`pipeline_liveness_report.py --fail-on-finding`** exits nonzero on any finding by design: STARVED,
   NO_ELIGIBLE_INPUT and also UNKNOWN (a lane source it could not read). Under cron that exit went to a
   log. Since 2026-10-09 it exits 3 and the step declares `finding_rc: [3]`, so the finding lands in the
   receipt (`findings`, `status: unhealthy`) and the unit stays green; a crash (rc 1) still fails it.
5. **Lock skip is not a failure.** `flock -n` under cron exited 1 silently; the tick records
   `lock_skipped: true` and keeps `ok`. Three consecutive lock skips on one step mean a wedge that the
   step's own timeout did not catch (another process holds the lock) — visible in `health_tick_history.jsonl`.
6. **`pipeline_watchdog.py` hardcodes `PROJECT_ROOT` to the dev tree** (pre-existing; it retries scripts
   there). The tick runs it from CURRENT exactly as cron did; not changed here.

## Install plan (operator, under a config-write grant + a cron grant; nothing below has been run)
Pre-flight, from CURRENT after the branch is merged and promoted (the tick needs `scripts/health_tick.py`
and `config/health_tick_steps.json` in the served tree):
```
cd ~/trade-ai-releases/portfolio-server/CURRENT
$PY scripts/health_tick.py --dry-run                      # prints today's due plan for this minute
$PY scripts/health_tick.py --dry-run --now 2026-10-08T09:20:00
$PY scripts/health_tick.py --week-plan --now 2026-10-05T00:00:00   # total must read 7402
```
1. Units (config-write grant):
```
cp ~/trade-ai-releases/portfolio-server/CURRENT/config/systemd/user/tradeai-health-tick.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemd-analyze --user verify ~/.config/systemd/user/tradeai-health-tick.service
systemctl --user start tradeai-health-tick.service      # ONE manual tick first (rule 7: dry run, then one live run)
journalctl --user -u tradeai-health-tick.service -n 40 --no-pager
cat ~/trade-ai-releases/persistent-state/data/runtime/health_tick_last.json | head -40
```
   Expect `ok: true` (or a named failing step with its first stderr line), `served_sha` == `CURRENT/GIT_SHA`.
   The manual tick runs the steps due at that minute **alongside** their still-installed cron lines — the
   locks make the second runner skip, so this overlap is safe for one tick but must not be left running.
2. Crontab (cron grant) — delete the 17 lines in the SAME step as enabling the timer, with a backup:
```
crontab -l > ~/crontab.backup.$(date +%Y%m%d-%H%M%S)
crontab -l | grep -n -E "scripts/(system_health_agent|moomoo/opend_health|cio_bridge_watchdog|health_agent|cron_self_heal|siem_critical_notify|log_error_scraper|system_freshness_monitor|portfolio_live_monitor|freshness_watchdog_heartbeat|pipeline_liveness_report|pipeline_watchdog|pipeline_freshness_monitor|pipeline_freshness_slo|check_llm_provider_health|symbol_news_curation_monitor|system_health_alerts)\.py"
```
   On today's crontab those are lines **178, 277, 344, 403, 419, 420, 437, 439, 491, 598, 628, 842, 901, 909,
   1007, 1024, 1042** (17 lines; verify the numbers again at install time — the crontab changes daily).
   Do **not** delete 241, 393, 636 (safety nets), 914 (resolve_due_checkpoints) or 843 (@reboot moomoo).
   Replace each deleted line with a one-line comment `# absorbed by tradeai-health-tick.timer 2026-10-xx: <original line>`
   so `cron_self_heal.py` and the lane registry baseline can still see the provenance.
```
systemctl --user enable --now tradeai-health-tick.timer
systemctl --user list-timers tradeai-health-tick.timer --no-pager
```
3. Lane registry (same install PR): flip `health-tick` to `ACTIVE` with `state_since`; remove the 17
   absorbed strings from `undeclared_baseline`; re-point the four declared rows
   (`portfolio-live-monitor`, `cio-bridge-watchdog`, `llm-provider-health`, `symbol-news-curation-monitor`)
   to `scheduler.kind=systemd`, `expression="tradeai-health-tick.timer (step <id>)"`, keeping their own
   `output_signal`s — their artifacts are still written by their own scripts.

## Verification (first hour, then first day)
- `journalctl --user -u tradeai-health-tick.service --since "1 hour ago" --no-pager | grep '\[health_tick\]'`
  — 12 ticks, each naming due/ran/ok.
- `tail -12 ~/trade-ai-releases/persistent-state/data/runtime/health_tick_history.jsonl | jq -c '{tick,due_count,ran_count,lock_skipped,timed_out,deferred,ok}'`
  — `deferred: []` on every tick; `timed_out: []` except a named, investigated step.
- Each absorbed script's own artifact keeps moving: `data/runtime/cio_bridge_watchdog.json` (checked_at),
  `data/runtime/moomoo_opend_health.json`, `data/portfolios/state/health_agent_status.json`,
  `data/runtime/llm_provider_health.json`, `data/runtime/symbol_news_curation_sla.json`,
  `logs/.freshness_monitor.heartbeat`, `data/portfolios/state/system_health_alert.json` (12:10 / 15:10).
- `python3 scripts/check_lane_registry.py --state-drift` reads `health-tick` ACTIVE and no SILENT among the
  four re-pointed lanes after 24 h.
- `system_health_agent.py` log-freshness components stay green (the tick appends to the same log files).

## Rollback (operator)
```
systemctl --user disable --now tradeai-health-tick.timer
crontab ~/crontab.backup.<stamp>        # restores the 17 lines verbatim
```
Then revert the lane-registry flip. The receipt files can stay; nothing reads them when the lane is not ACTIVE.

## Files in this PR
- `config/health_tick_steps.json` — the table (`HealthTickSteps@v1`)
- `scripts/health_tick.py` — the runner (`--dry-run`, `--apply`, `--once --step`, `--week-plan`, `--now`)
- `config/systemd/user/tradeai-health-tick.service`, `.timer` — PROPOSAL ONLY
- `config/lane_registry.json` — `health-tick` row, `NEVER_SCHEDULED`
- `tests/test_health_tick_20261007.py` — registered in `scripts/run_cio_hardening_ci.py` (`n8n_parallel_20261007`)
