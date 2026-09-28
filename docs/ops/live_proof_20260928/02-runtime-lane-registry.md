---
Status: MEASURED
as_of: 2026-09-28T11:05:00-04:00
Measured at: served a328a8817 → e2dcfce1a (flipped 10:59 ET during the survey)
Campaign: LIVEPROOF-20260928
Source: read-only host survey (agent), rows in 02-runtime-lane-registry.csv
---

# 02-runtime-lane-registry: host survey, 2026-09-28, about 10:55–11:05 EDT (read-only)

I edited nothing and started or stopped nothing. I did not read any env files, and no secret values are printed below. The one DB attempt used `default_transaction_read_only=on` and was rejected (details in section 8).

## 0. Headline findings

1. **CURRENT moved during the survey.** At the start it resolved to `a328a8817-main-exact-phase2-20260928-101406`. By the end it resolved to `/home/johnclaw/trade-ai-releases/portfolio-server/e2dcfce1a-main-exact-phase2-20260928-105924`. `portfolio-server`, `cio-telegram`, `health-agent` and `cio-governed-bridge` restarted into e2dcfce1a about 10:59. The dev tree HEAD is also e2dcfce1a, and `config/lane_registry.json` is byte-identical between the dev tree and CURRENT.

2. **Bug in the lane-registry gate: it hides 5 unregistered cron lines.** `find_undeclared` (`/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/lib/lane_registry.py` about lines 579–606) adds every lane's `scheduler.expression` to the set of declared patterns, then checks each cron line with `any(d in expr for d in declared)`, a plain substring test.
   - Some lanes use a bare schedule string as their expression:
     - `approval-package-reminder`: `"5 * * * *"`
     - `platform-conformance-audit`: `"30 2 * * *"`
   - Any cron line containing that text is then treated as declared. These 5 lines are in no lane row, not in the baseline and not in the tranche:
     - `30 2 * * *` populate_performance_context.py
     - `*/5 * * * *` cleanup_stale_locks.sh
     - `5 * * * *` sync-docs-to-drive.sh
     - `*/15 * * * *` health_agent.py
     - `*/5 * * * *` inline curl prewarm (`trade_ai_prewarm.log`)
   - Matching on `match` (or `expression` only when there is no `match`) gives **73** registered cron lines, not 86.

3. **The system-level scanner is live while the registry says PAUSED.** `tradeai-continuous.timer` and `tradeai-continuous.service` run at system level (User=johnclaw, WorkingDirectory=`$DEV`, running since 04:00, PID 1029862 `continuous_runner.py`). The registry lane `tradeai-continuous` is PAUSED, which only reflects the disabled *user* timer of the same name.

4. **Long-running processes started by cron are pinned to old releases.** Their working directory is the release they started in, not CURRENT:
   - `watch_directives_service.py`, `portfolio_live_monitor.py` and `schwab_stream_daemon.py` run from `c1c531500-…-081744`, two releases back.
   - The telegram callback poller daemon and 3 `tradeai-watch-refresh-worker-*` transient units run from `a328a8817`.

5. **About half the user timers run from the dev tree, not CURRENT.** 50 of 117 timer units have WorkingDirectory or script path in `$DEV`. Examples: db-retention, tradeai-backup-enforcer, governance-pipeline, portfolio-{daily,weekly,monthly,lookthrough}-cadence, tax-lots-rebuild, sm-render, disk-pressure-guard, slo-burn-rate, the audit timers, hermes-* dry-run and health timers.
   - 4 disabled flash timers point at the worktree `~/tradeai-wt-cursor-guardrails`.
   - `at-observation-01` points at `~/worktrees/active-trader-next`.
   - Trade-ai cron lines all run on CURRENT (`$PROJ`/`$CUR`); none `cd` into `$DEV`.

6. **Registry state disagrees with the host:**
   - `contradiction-adjudicator` is NEVER_SCHEDULED, but its timer is enabled/active (it has never triggered).
   - `maturity-remeasure` is NEVER_SCHEDULED, but a cron line (`40 6 * * 1`) is active and the heartbeat shows 12:18Z today.
   - `at-observation-01` and `at-observation-01-closeout` are RETIRED, but their timers are still enabled/active (one-shot 2026-07-27, never fired).

## 1. Today's counts

The historical figures (467 jobs / 90 timers / 188 unlocked jobs) should not be used. These are today's:

| Item | Count |
|---|---|
| crontab lines, total | 1065 |
| env assignments (SHELL, PROJ, PY, LLM_DEFER_OFFPEAK, TRADEAI_ENV, BLIND_REVIEW_LANES, CIO_DUAL_CHATGPT_CAP) | 7 |
| **active cron jobs** | **469** |
| commented lines that look like schedules | about 51 |
| cron: strictly registered | 73 |
| cron: inherited tranche 2026-09-28 | 107 |
| cron: `undeclared_baseline` | 284 |
| cron: unregistered and not in any baseline (masked by the bug) | 5 |
| cron: non-trade-ai entries included above | nyc-dof-auction rescan_tickets and run_pipeline; `~/.claude/sync-memory-to-drive.sh`; openclaw ops digests |
| **user timer unit files** | **117** (93 enabled/active, 24 disabled/inactive) |
| `list-timers --all` rows | 93 |
| timers: registered | 71 |
| timers: UNREGISTERED (baseline) | 46 |
| timers: UNREGISTERED new | 0 |
| system timers related to trade-ai | 1 (`tradeai-continuous.timer`) |
| **user services** | **143 units: 27 running, 1 activating, 2 failed, 109 inactive, 4 not-found** |
| failed services | `mcporter-token-refresh.service` (exit 1), `snap.firmware-updater.firmware-notifier.service` (exit 255) |
| system services related to trade-ai | `tradeai-continuous.service` running; `postgresql@17-main` running |
| lane registry rows | 158: ACTIVE 121, NEVER_SCHEDULED 14, PAUSED 13, RETIRED 10 |
| lane registry scheduler kinds | cron 72, systemd 72, none 13, event 1 |

## 2. Running services and resident daemons

Format: unit → cwd → argv. `REL/` = `~/trade-ai-releases/portfolio-server/`.

- **portfolio-server** → `REL/e2dcfce1a…` → `$DEV/.venv/bin/python REL/e2dcfce1a…/scripts/portfolio_server.py`
- **tradeai-cio-telegram** → e2dcfce1a → `REL/CURRENT/scripts/cio_telegram_bot.py --loop`
- **tradeai-health-agent** → e2dcfce1a → `~/.config/tradeai/bin/health_agent_daemon_current.py`
- **cio-governed-bridge** → e2dcfce1a → `scripts/lib/cio_governed_model_bridge.py`
- **tradeai-ops-agent** → `~/.openclaw/skills/tradeai-health-inspect/scripts` → `ops_agent_daemon.py --apply --telegram`, up 10 days
  - it spawns `inspect_all.py`, `remediation_runner.py` and `warm_caches.py` (cwd `$DEV`)
- **tradeai-active-trader-motion** → `~/trade-ai-deployments/active-trader/306f8179…` → `python -m active_trader.motion_runtime`
- **tradeai-watch-refresh-worker-2269637-{0,1}-*** (3 transient units) → a328a8817
- **chatgpt-oauth-proxy** → cwd `~` → `/usr/bin/python3 $DEV/scripts/chatgpt_oauth_proxy.py`
- **grok-oauth-proxy** → `$DEV` → `$DEV/scripts/grok_oauth_proxy.py`
- **heartbeat-receiver** → `$DEV` → `scripts/heartbeat_receiver.py`
- **openclaw-gateway** → node `~/.local/lib/openclaw/dist/index.js gateway --port 18789`
- **trade-ai-lab-moomoo-opend**, **tradeai-lab-postgres**, **power-watch**, **dof-dashboard** (nyc-dof) — running
- **System `tradeai-continuous.service`** → `$DEV` → `flock … linux_launchers/run_continuous.sh` → `continuous_runner.py`
- **Long-running processes started by cron** (cgroup cron.service):
  - `watch_directives_service.py --apply` (up 2h) → c1c531500
  - `portfolio_live_monitor.py` (up 2h) → c1c531500
  - `schwab_stream_daemon.py` (up 1.5h) → c1c531500
  - `run_telegram_callback_poller.py --daemon` → a328a8817
  - Also seen at survey time, short-lived: `reconcile_protection_advisory_outcomes.py` with cwd `$DEV` under cron.service. No crontab line `cd`s into `$DEV`, so something else launches it.

## 3. Heartbeats

Source: `persistent-state/data/runtime/heartbeats/*.json`. Format: lane_id | last_beat (UTC) | last_success.

- edge-fanout-consumer | 14:57:23 | 14:57:23
- gir-projector | 14:02:29 | 14:02:29
- hermes-cio-worker | 13:45:26 | **null**. Its timer fires every 15 minutes, so the beat is more than 1h stale; cwd is c1c531500.
- hermes-external-chatgpt | 14:47:24 | null
- hermes-external-deepseek | 14:40:37 | null
- hermes-external-grok | 14:46:06 | null
- maturity-remeasure | 12:18:50 | 12:18:50
- persistent-wake | 14:00:42 | null
- sec-filings-feed | 12:20:17 | 12:20:17
- supervisor-breach-detector | 14:57:23 | 14:57:23 (the timer fired again at 15:01)
- symbol-thesis-acquisition | 14:27:07 | null
- watchlist-agent-maria | 14:47:34 | null
- watchlist-agent-risk_agent | 14:47:27 | null
- watchlist-agent-steph | 14:47:39 | null
- watchlist-agent-tax_agent | 14:00:32 | null

Across all 15: `release_sha` is null, `degraded_reasons` is empty, and `queue_depth` is null. The cwd field points at a mix of a328a8817 and c1c531500; none point at e2dcfce1a yet.

## 4. Breach detector

`data/runtime/supervisor_breach_detector_latest.json`, as_of 2026-09-28T14:57:23Z:
- active_lanes=121, sla_rows=153, heartbeats=15, breaches=5 (NO_OUTPUT 2, UNGOVERNED 3), new_rows=0
- ladder is "detect+record only", authority READ_ONLY_ADVISORY

`supervisor_breaches.jsonl` has only **32 rows in total**, so fewer than the 40 asked for. All rows are state OPEN, level 1.
- **NO_OUTPUT at 2026-09-28T00:12:33Z (25 rows):** cio-delivery, cio-defer-revisit, portfolio-repricer, indicator-cache-refresh, identity-sweep-stage0, material-change-notifier-stage2, watch-review-workers, material-change-digest, due-diligence-questions, document-mentions-backfill, morning-brief-0730, screener-go-alerts, llm-spend-report-monthly, governed-agent-flash-market, cio-entry-state, dormant-lane-consumers, advisory-lessons-reflect, instrument-belief-writer, options-thesis-lifecycle, alpaca-stop-manager-rth, alpaca-stop-manager-oco-repair, options-memory-projector, options-runtime-export, reconcile-alpaca-paper-options, sec-fundamentals-ingest
- **Other NO_OUTPUT rows:**
  - approval-package-reminder, 00:22:52Z
  - code-mirror-drive-sync, 00:36:54Z
  - research-scheduler-priority-hourly, 02:02:03Z
  - resolve-due-checkpoints, 02:20:14Z
- **UNGOVERNED ("no SLA row"):**
  - edge-fanout-consumer, 12:01:33Z
  - sec-filings-feed, 12:01:33Z
  - finviz-momentum-scalp-early-lane, 14:16:44Z

## 5. Duplicates (same script scheduled more than once)

**Cron and timer running the same work:**
- **hermes_maturity_gates.py --snapshot**: cron `20 7 * * *` (flock) and `tradeai-maturity-feeds.timer` at 07:20 daily (no flock). Same arguments, same minute, both on CURRENT. **Exact duplicate.**
- **watch_decision_scheduler.py --run**: cron `*/15 7-16 * * 1-5` and `tradeai-watch-decision-scheduler.timer` (Mon–Fri 09:35/11:00/13:30/15:45, Sat–Sun 09:00/14:00). **Overlapping duplicate.**
- **db_retention.py**: cron `10 4 * * *` on CURRENT and `db-retention.timer` Sun 03:00 on `$DEV`. **Duplicate, and on different trees.**
- **hermes_external_feedback_loop.py --apply**: cron `15 * * * *` (`--max-rows 2000`) and `hermes-external-feedback.timer` 04:00 (`--model deepseek-v4-flash`).
- **hermes_momentum_catalyst_researcher.py**: cron `25 6-15 * * 1-5` (`--source scalp`) and a timer every 15 minutes 08–15 (`--max-tickers 5`, on `$DEV`). Different modes but overlapping.
- **iris_taxonomy_agent.py**: 3 cron lines plus `tradeai-iris-taxonomy.timer` (the timer is disabled, so harmless).

**Cron-only duplicates:**
- **inline cio_event_detector.run_cio_event_detector_once()**: 3 lines with the same call (`0 5 * * 1-5`, `0 8 * * 0`, `0 9 1 * *`). These use system `python3`, not the venv.
- **Same script and same arguments at different times:**
  - plan_drift_revalidator.py --apply ×3 (10:00, 13:00, 17:25)
  - atm_position_reconciler.py --audit-only ×2
  - research_intelligence_queue.py --drain ×2
  - topic_ingestion ×2
  - opening_intelligence --persist ×2 (plus a `--render` variant)
  - snaptrade_sync --apply ×2
  - watchlist_enrichment_sweep --once ×2
  - hermes_research_agenda ×2
  - options_chain_snapshot ×2
  - defense_recommendations ×2
  - run_options_monitor.sh ×2
  - run_protection_pipeline.sh ×2
  - shadow_batch_generator ×2
  - market_regime_collector ×2
- **Multi-mode families** (same script, different modes, probably intentional): trade_ai_orchestrator ×6, hermes_subject_enhance ×6, run_scheduled_atp2_research_cycle ×5, research_scheduler ×4, llm_intelligence_enrichment ×4, catalyst_momentum_engine ×3, data_gap_resolver ×3, agent_router_cron ×3, agent_intelligence_cron ×3, external_market_data_ingest ×3, stale_proposal_sweeper ×3, news_ingestion ×3, run_inference_cycle ×3, llm_spend_report ×3, multi_tier_trade_reviewer ×3.
- No two cron lines are byte-identical.

**Timer duplicates:**
- run_portfolio_maintenance_pipeline.sh ×5 (the backup timer on CUR, the other 4 on DEV)
- report_organic_stance_hold.py ×2 (the 06:35 and 09:05 stance timers)
- flash_cadence_runner.py ×4 (all disabled)
- agent_runtime.run_once ×17 template instances (by design)

## 6. Lane registry rows (158)

Source: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/lane_registry.json`, schema LaneRegistry@v1.
- Fields per row: lane_id, owner, scheduler{kind, expression, match}, expected_cadence_hours, state, output_signal, note.
- There is **no consumer field**, so the consumer column is "?" throughout.
- For registered lanes, the lane_id, state, cadence source and output_signal are shown in the cron and timer lines below.
- Non-ACTIVE rows:
  - **RETIRED:** deep-overnight-llm, overnight-batch, portfolio-backup-cron, cron-freshness-watcher, at-observation-01, at-observation-01-closeout, tradeai-operator-readiness, aegis-morning-brief-delivery-0805, aegis-overnight-cron-duplicate-2000, governed-agent-flash-market
  - **PAUSED:** tradeai-continuous, hermes-autonomous-loop, tradeai-flash-llm-intelligence, tradeai-flash-watchlist-daily, tradeai-hermes-research-remediation, tradeai-intelligence-remediation, tradeai-main-desk-free-llm-weekly, alex-daily, alex-weekly, alex-monthly, alex-hygiene, alex-gov-research, cio-decision-engine
  - **NEVER_SCHEDULED:** cio-residual-web, portfolio-backup, portfolio-daily, portfolio-weekly, portfolio-monthly, portfolio-lookthrough, tradeai-governance-facts, tradeai-governance-status, tradeai-maturity-board, tradeai-flash-portfolio-risk-hourly, tradeai-flash-portfolio-risk-weekend, docs-index, contradiction-adjudicator, maturity-remeasure
- Registry cron-lane anomalies:
  - `portfolio-repricer`, `industry-momentum-groups` and `watch-review-workers` each match 2 active lines.
  - `cron-freshness-watcher` and `governed-agent-flash-market` are RETIRED; each has only a commented line left.

## 8. intelligence.sla row count

I could not get a read-only count. `~/.pgpass` has a single entry, `localhost:5432:trade_ai:trade_ai`, and its password was rejected ("password authentication failed"). Peer auth fails because role johnclaw does not exist. I did not read `.env` or `TRADEAI_ENV` to find other credentials.

Two proxies from the SLA seed and the detector:
- Breach detector latest: `sla_rows: 153` (14:57Z).
- `persistent-state/data/runtime/supervisor_sla_seed.json` (as_of 2026-09-27T23:58:54Z): rows 153, lanes 153, fail_closed 23, degraded 3, no_cadence 0.

## 9. Key paths

- Registry: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/lane_registry.json` (identical to CURRENT's copy)
- Gate logic with the substring bug: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/lib/lane_registry.py` (`find_undeclared`, about lines 572–606) and `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/check_lane_registry.py`
- Heartbeats: `/home/johnclaw/trade-ai-releases/persistent-state/data/runtime/heartbeats/`
- Breaches: `/home/johnclaw/trade-ai-releases/persistent-state/data/runtime/supervisor_breach_detector_latest.json` and `supervisor_breaches.jsonl`
- Crontab snapshot kept by the cron lane: `/home/johnclaw/trade-ai-releases/persistent-state/data/runtime/crontab_snapshot.txt`
- Served release now: `/home/johnclaw/trade-ai-releases/portfolio-server/e2dcfce1a-main-exact-phase2-20260928-105924`
- Full raw per-line cron dump from this survey (same content as §7a–7d): `/home/johnclaw/.claude/projects/-home-johnclaw/77a6de60-3513-40ce-9220-25d684930e93/tool-results/b4zgdk0fe.txt`
