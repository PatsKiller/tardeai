# Cron consolidation — the 487 lines, what overlaps, what to merge, what to leave alone

Read-only audit of the live user crontab on `ms01-openclaw`, 2026-10-07 12:30–12:55 ET, requested by the operator ("400+ cron jobs; some must overlap"). Inputs: `crontab -l` re-parsed line by line, the lane registry at the served SHA, user systemd timers and their ExecStart, 11 days of syslog CRON CMD lines (2026-09-27 → 10-07), `logs/safe_flock_events.jsonl`, and the header of every scheduled script. Nothing was changed. Counts are exact unless marked **ESTIMATE**; causes not proven are **NOT VERIFIED**.

## 1. The shape of the file

| Metric | Value |
|---|---|
| Raw lines | 1,099 (552 comments, 53 blank, 7 env, **487 job lines**) |
| Commented-out job lines | 16 (plus 9 prose comments that start with a digit) |
| Distinct scheduled scripts | 391; 53 of them occupy 139 lines |
| Cadence | ≤5 min 23 · 6–15 min 35 · 16–59 min 34 · hourly 21 · multi-daily 66 · daily 252 · weekly/monthly 54 · one-off 1 · @reboot 1 |
| Fixed-hour clusters | 06–08h **96 lines**, 16–18h **70 lines**: two implicit pipelines expressed as minute offsets |
| Locks | 296 lines hold a lock (249 bare `flock -n`, 47 `safe_flock.sh` with receipts); **191 lines have no lock**; 158 have no wrapper at all |
| Tree | 478 lines point at CURRENT, but **25 scheduled shell wrappers inside CURRENT hardcode the dev tree** (≈36–45 lines execute dev-tree code: atp2 research cycle ×5, agent_router/agent_intelligence ×6, stale-proposal sweeper ×3, protection pipeline ×2, quote refresh ×2, Drive syncs, docs retention, …) |
| Firing volume | weekdays ≈ **10,145** CMD/day, weekends ≈ 6,650; top 20 scripts = 58 % of firings; 205 scripts fire ≤ once a day |
| Registry | 178 lanes, 87 cron rows matched; everything else is "inherited baseline" (517 strings + 113 tranche lines); the gate is clean on main after #1479 |

## 2. True duplicates and dead lines (remove first)

| Line(s) | Finding | Action |
|---|---|---|
| L347 + L348 `auto_proposal_generator.py --today --apply` | `*/30 9-16` **and** `*/10 6-11`, same args; L347 has no lock → 30 same-minute collisions a week, two writers on `paper_trade_proposals` | keep L348, delete L347 |
| L612 + L484 `portfolio_repricer.py` | `*/15 9-16` already fires 16:00 and 16:15; the 16:10 line adds nothing | delete L484 |
| L360 + L361 `atm_position_reconciler.py` | both redirect to `logs/atm_position_reconciliation/cron.log` whose **directory does not exist**, so bash fails the redirect and the command never runs: 243 firings in 11 days, 0 executions, `latest.json` never written | create the directory and keep one line, or retire the lane; today it is dead weight either way |
| L132 `paper_trade_monitor.py */2 9-16` | the comment above it says "STOP-V2.2: replaced by unified_stop_supervisor"; the supervisor's docstring says it replaces it; 240 firings a day | delete **after** confirming the supervisor owns R-multiple stop moves (its header says "does NOT create, cancel, or move stops in this phase") — NOT VERIFIED, so check first |
| L400 `morning_eval_check.sh 0 7 3 6 *` | fires once a year (June 3), log never created, wrapper hardcodes the dev tree | delete |
| L725 `hermes_maturity_gates.py --snapshot 20 7` | identical to `tradeai-maturity-feeds.timer` at 07:20:00, same args | delete the cron copy |
| L982 `db_retention.py 10 4` vs `db-retention.timer` Sun 03:00 (dev tree) | two schedulers, two code trees, one database | timer already disabled 2026-10-07 under the trim work; cron line is the owner |
| L855 `watch_decision_scheduler.py --run */15 7-16` | `tradeai-watch-decision-scheduler.timer` is the declared lane (09:35, 11:00, 13:30, 15:45 + weekends); the cron copy is the undeclared one | delete the cron copy |
| L1006 `hermes_external_feedback_loop.py 15 * * * *` vs `hermes-external-feedback.timer` 04:00 | hourly and nightly, different model and cap | pick one (registry decision) |
| L763 `hermes_momentum_catalyst_researcher.py 25 6-15` vs `hermes-momentum-catalyst-morning.timer` every 15 min 08:00–15:45 (dev tree) | 10 + 32 runs a day of the same researcher from two trees | keep the timer, repoint it to CURRENT, delete the cron copy |
| `plan_drift_revalidator.py` ×3 (10:00, 13:00, 17:25, three lock names) | time variants only | one line `0 10,13 * * 1-5` + 17:25 |
| `market_regime_collector.py` ×2, `watchlist_enrichment_sweep.py` ×2 | near-duplicates | one line each |
| L880 `hermes_cross_source_synthesizer` Mon/Thu 06:20 | 3 firings, log never created: `llm_priority_guard.sh &&` refuses every run (NOT VERIFIED beyond file absence) | fix or retire |
| L922 `run_governed_symbol_thesis_acquisition.sh 17:17` | fired 7×, log 40 days old: wrapper exits before logging (dev-tree default path) | fix the tree, then keep |
| 16 commented-out job lines + 9 digit-leading prose comments | 20 % of the file is dead text | delete from the file (registry already carries the RETIRED rows) |

Rank-1 effect: 16 lines → 4, ≈ 270 firings a day removed, two silent data races closed. Effort half a day.

## 3. Overlaps that cost money or correctness

| Overlap | Evidence | Why it matters |
|---|---|---|
| `signal_fusion.py --active */30 4-16` ⊃ `--full 0 7,13` | same minutes 10 of 10 times a week, different locks | two concurrent writers on `portfolio_intelligence_events` |
| `run_scheduled_quote_refresh.sh pending */5 9-15` vs `incubator 45 7,10,12,13,16` | same lock file; 10:45, 12:45, 13:45 collide daily; `flock -n` silently drops one | which one loses is NOT VERIFIED; the loser's work never happens |
| `hermes_subject_enhance.py` ×6 (scalp `*/30`, proposal `*/20`, position, sector, closed-trade, report) | 40 collisions a week, all on the paid grok/chatgpt lanes | one dispatcher with a due-table serialises the lane calls |
| `catalyst_momentum_engine.py` premarket `*/30 4-9` and swing `30 9-15` | both fire 09:30 | band-from-clock |
| `external_market_data_ingest.py --quotes */15` | **46 lock skips in 109 runs since 10-04**: the job overruns its own slot 42 % of the time | cadence is wrong for the runtime |
| Sixteen scheduled writers on `paper_trade_proposals` (generator, two enrichment loops both `*/10 4-19`, technicals, LLM review `*/30`, monitor, sweeper ×3, alert `*/2`, ATM approver `*/15`, …) | one lifecycle spread over ≥ 9 independent clocks | a proposal worker with ordered stages |
| Twelve writers on `watchlist_items` (sweep `*/30`, scorer `*/15`, event feeder `*/5`, …) | three clocks on one row set | fold into one tick |
| `material_change_detector */30` → `notify_material_change 7-59/15` → `due_diligence_questions */20` | a three-stage chain on three unrelated clocks, 24×7, for inputs that change in market hours | ordered tick |
| Options: `thesis_lifecycle 7,22,37,52` → `memory_projector 9,24,39,54` → `export 3 *` | dependency encoded as minute offsets ("2 min after") | one `options_tick` every 15 min, ordered |
| Telegram poller: cron launcher `*/2` + cron watchdog `*/5` | 1,008 firings a day emulating `Restart=always` | a systemd service |
| Health: 33 monitor/freshness/siem lines (`*/2` … hourly), nine of them writing `alert_events` | ≈ 1,600 firings a day; `system_health_agent */5`, `health_agent */15`, `cron_self_heal */15`, `liveness */30` all watch the same things | one health tick with a cadence table; safety nets (server watchdog, reaper, lock cleaner) stay independent |

## 4. Consolidation plan, ranked

Mechanisms that already exist and should carry this: `scripts/pipelines/run_portfolio_maintenance_pipeline.sh --cadence …` (five timers today) and `run_governance_pipeline.sh`, with `_pipeline_common.sh` providing a pipeline-level lock and `run_step`; four unscheduled skeletons already exist for the market, after-close, Hermes research and LLM-control pipelines. Every move follows the same discipline: declare the runner as a lane with an `output_signal` **before** installing it (the registry gate fails any undeclared line and treats removals as fine), remove the absorbed lines from the baseline in the same PR, give every step its own timeout and receipt (`safe_flock.sh` or `run_step` plus a summary JSON), fix the 25 dev-tree-hardcoded wrappers before folding them in, and keep per-step LLM wrappers (`run_with_deepseek_offpeak.sh`, `llm_priority_guard.sh`, per-line caps) on the step, not on the runner.

| Rank | Move | Lines → | Mechanism | Risk | Effort |
|---|---|---|---|---|---|
| 1 | Remove the true duplicates and dead lines (§2) | 16 → 4 | crontab edit | low (L132 medium) | 0.5 ed |
| 2 | Telegram poller → `tradeai-telegram-poller.service` with `Restart=always` and a cwd check | 2 → 0 | systemd | low | 0.5 ed |
| 3 | Health tick: one `*/5` timer running a cadence table (5/15/20/30/120/240 min, hourly) with one receipts file; reaper, server watchdog and lock cleaner stay outside | 16 → 2 | timer + step table | medium | 3 ed |
| 4 | Nightly and weekly platform-maintenance pipeline (log rotation, SIEM purge, universe retention, db_retention, mentions prune, config sync, conformance, integrity sweep, Drive syncs, n8n backup/drill, docs retention, instrument sweep, version check, backup verify) | 17 → 3 | `run_platform_maintenance_pipeline.sh --cadence nightly/weekly/monthly` | low–medium | 2 ed |
| 5 | Post-close pipelines: close-capture 16:05 → broker-truth 16:30 → planning 17:30 | ≈38 → 4 | extend `run_tradeai_after_close_pipeline.sh`, continue-on-error, per-step timeout | **high** (today's ordering is minute spacing; one slow step shifts all) | 5 ed |
| 6 | Premarket data pipeline 05:45–06:55 (must finish before the 07:30 brief) | ≈18 → 2 | new runner; measure step runtimes first (serial fit NOT VERIFIED) | medium | 3 ed |
| 7 | Hermes learning chain (10:50 → 17:00, 7 lines) and overnight discovery chain (8 lines) | 15 → 2 | `run_hermes_learning_pipeline.sh` with per-step off-peak wrapper | medium | 3 ed |
| 8 | Hermes discovery/intel lanes into the `hermes_coordinator.py` `*/15` tick table | 10 → 0 | extend the coordinator | medium | 2 ed |
| 9 | `hermes_subject_enhance` ×6 → one dispatcher | 6 → 1 | due-table, serialised lane calls | low | 1 ed |
| 10 | Digest scheduler: morning slot (6 lines), close slot (7), weekly (2) | 18 → 4 | table-driven sender behind the single Telegram chokepoint; keep the 07:30 brief separate | medium (comms rules) | 2 ed |
| 11 | Proposal lifecycle worker (generator, two enrichment loops, technicals, review, alert, monitor, sweeper ×3) | 11 → 2 | one worker `*/10 4-19` with ordered stages; ATM approver stays separate | medium | 3 ed |
| 12 | Scalp session worker 06:00–11:00 (fast path `*/2`, finviz scan, shadow logger, premarket watch) | 4 → 1 | timer-started process with an internal loop | medium | 2 ed |
| 13 | Options tick (lifecycle → projector → export) | 3 → 1 | one `*/15` ordered runner | low | 1 ed |
| 14 | `trade_ai_orchestrator` ×6 → 2 (hour list, label from clock) or schedule the existing market pipeline | 6 → 2 | hour list | low | 0.5 ed |
| 15 | Multi-mode scripts → one self-selecting line each (atp2 ×5, research_scheduler ×4, enrichment ×3, multi-tier ×3, gap resolver ×3, opening intelligence ×3, news ingestion ×3, taxonomy ×3, spend report ×3, inference ×3, catalyst ×3, market data ×3, sweeper ×3, agent router/intelligence ×6, …) | ≈60 → ≈24 | `--mode auto` from the clock, budgets kept in a table | low | 3 ed |
| 16 | Watchlist post-close maintenance + Sunday outcome reconcilers | 10 → 3 | step lists | low | 1 ed |
| 17 | Overnight research/LLM chain 20:00–05:15 | 14 → 2 | `run_llm_control_pipeline.sh`-style nightly | medium–high (caps, off-peak) | 3 ed |
| 18 | Hourly Drive syncs + options export | 4 → 1 | one hourly runner | low | 0.5 ed |
| 19 | CIO cron items beside the reactive timer; inline event-detector ×3 → 1 | 8 → 4 | timers | medium | 1 ed |

Projected: **487 → ≈ 300–310 job lines (−37 %)**, weekday firings **≈ 10,150 → ≈ 6,500/day**, ≈ 38 engineer-days in total. Ranks 1–4 (≈ 6 days) alone remove 25 lines and ≈ 2,700 firings a day and close the known races.

## 5. What must not be merged

- **The 23 `market_day_gate` broker, stop and execution lines** and the staggered broker syncs (Schwab positions `7,22,37,52`, positions sync `9,24,39,54`, transaction ingest `3,18,33,48`): each has its own lock and a deliberate minute offset so the brokers are not hit in the same second, and so one wedge cannot delay a stop check. Per-order 2FA stays the only live gate. Keep failure isolation.
- **Lines with their own LLM caps or wrappers**: `hermes_external_feedback_loop` (`LLM_GLOBAL_DAILY_USD_CAP=2.00`), the four research-scheduler budgets, `CIO_DUAL_CHATGPT_CAP`, the 25 off-peak-wrapped and 16 priority-guarded lines, `BLIND_REVIEW_LANES`. Consolidate the schedule, keep the wrapper per step; folding steps under one wrapper call changes the cap accounting.
- **Safety nets that watch the things being consolidated**: `portfolio_server_watchdog.sh` (hang detection that `Restart=always` cannot do), `process_reaper.py`, `cleanup_stale_locks.sh`, the Postgres and autonomy watchdog timers. Moving them into the health tick recreates the single point of failure they cover. Moving them to standalone timers is fine.
- **Other operators and trees**: the DOF jobs, OpenClaw digests, the memory-to-Drive sync, the campaign feed, the crontab snapshot line.
- **Operator-decided sends**: the 07:30 morning brief (one send, decision 09-14), the options-lifecycle lines added on request (merge as ordered steps only, cadence unchanged), the Hermes premarket send (open promise).
- **Paper vs live lanes**: never one runner, even if co-scheduled.
- **Cron copy vs systemd copy running different trees** (db_retention, momentum catalyst, portfolio cadences): retire one after choosing the tree; do not "merge".

## 6. Recommended execution

Tranche A (this week, ≈ 6 ed): ranks 1, 2, 3, 4. Each a PR with the registry change, the crontab diff as a proposal file, and a dry run; installed under cron and config-write grants with a crontab backup. Tranche B (next two weeks): ranks 5–7 after measuring step runtimes on the post-close and premarket windows. Tranche C: the rest, one family per PR. Throughout: fix the 25 dev-tree-hardcoded wrappers first, since folding them into CURRENT pipelines without that silently changes which code runs.

NOT VERIFIED and needed before Tranche B: per-step runtimes in the 06–08h and 16–18h windows; whether `_pipeline_common.sh run_step` writes receipts and continues on error; what `run_ensemble_worker.sh` drains (empty header); why L922 and L880 never log; whether the health-agent daemon already duplicates the `*/15` cron; which quote-refresh line loses the shared lock.
