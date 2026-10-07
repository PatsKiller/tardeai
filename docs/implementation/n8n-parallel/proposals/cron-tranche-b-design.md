# Cron tranche B — post-close, premarket and Hermes chains: measurements, fit, manifests (2026-10-07)

Status: PROPOSED 2026-10-07 — MEASURE + DESIGN + SKELETON only. Nothing installed, no crontab edit, no unit, no real run of any step (dry-run only). Operator cron grant required before any stage is scheduled.

Scope: ranks 5, 6 and 7 of `docs/implementation/n8n-parallel/13-cron-consolidation-20261007.md` (post-close pipelines, premarket data pipeline, Hermes learning/overnight chains). Rails: AGENTS.md §0 (read-only on the host; dry-run before live; exit code is not evidence; broker authority never in scope).

## 1. What was measured and how

Population: every `crontab -l` job line (ms01-openclaw, 2026-10-07 12:39 ET) with a fixed minute field whose expansion fires inside 05:30–08:00 or 16:00–18:40 — **233 lines** (102 AM-only, 86 PM-only, 45 fire in both windows because they are hourly/multi-hour lines) — plus the 18 Hermes chain lines. Window: the 7 days 2026-09-30 12:00 → 2026-10-07 12:30 ET. Ledger: `../ledgers/window_runtimes_20261007.json` (+ `.md` table).

| Source (preference order) | What it proves | Lines covered |
|---|---|---|
| `safe_flock_events.jsonl` started→completed pair | VERIFIED duration + exit code | 16 window lines wrapped in `safe_flock.sh` |
| `pipeline_runs` Postgres heartbeat (`started_at`/`finished_at`, read-only SELECT) | VERIFIED duration | the 20 `PipelineRun`/`record_stage_run` scripts and the `run_scheduled_*` wrappers |
| own log: timestamped start + explicit end marker / `duration_s` | VERIFIED duration | logs with per-line timestamps and a Finished/Complete/Done line |
| syslog `CRON CMD` + `auth.log` `pam_unix(cron:session)` close | VERIFIED when unambiguous (one johnclaw session that minute, or every other session explained by its own verified duration or its `timeout N` kill) | 4 lines exact; the rest get an UPPER BOUND (longest unexplained session in the minute group) |
| own log first..last timestamp without an end marker | LOWER BOUND only | wrapper-stamped logs (`run_scheduled_*.sh` stamps every line with the start time) |
| syslog start only | NOT VERIFIED | everything else |

Rejected: pairing a start with a log/receipt last-write mtime (the brief forbids it); syslog carries no `CMDEND` on this host; `lastcomm`/process accounting is not installed.

**Coverage: 248 lines — 45 VERIFIED on every firing, 5 partially verified, 196 bounded only (NOT VERIFIED), 2 never fired in 7 days** (L485 and L531 fire only 9-16 at minutes that fall outside the window). Honest reading: the PAM upper bounds are tight when the minute group is all short jobs (e.g. 16:33 group ≤2 s, 06:38 ≤3 s, 17:55 ≤2 s) and loose when a long unrelated job shares the minute (17:25 and :25 groups carried `backfill_document_mentions` hitting its 25 m timeout every hour — attributed by the timeout rule; the 06:00 group carries `microstructure_recorder`'s 3.5 h session on 2 of 5 days).

Findings while measuring (not acted on): `market_day_gate.sh` logs a probe error on every run because CURRENT has no `.venv` (it then falls back to the dev venv, so the lines still run); `atm_position_reconciler` (L348) never starts (`safe_flock` has no started event in 7 days — the log directory is missing, tranche A D5); `screener_pm.log` ends in `Terminated "$@"` lines (the 16:00 orchestrator is killed by something — NOT VERIFIED what); `hermes_source_curation` (L392) completed through its lock on only 2 of 7 nights.

## 2. Fit arithmetic

Rule for the arithmetic: a step contributes its verified median/p95 when verified, otherwise its PAM-group **upper** bound (conservative). A step enters a serial stage only if (verified and p95 ≤ 600 s) or (unverified and upper-bound median ≤ 300 s); everything slower or looser is named under `deferred` and stays a parallel line.

### 2a. Post-close — the study's "close-capture 16:05 → broker-truth 16:30 → planning 17:30"

**close-capture at 16:05 (deadline 16:33, the basis sync that stays its own line)** — start 16:05, deadline 16:33 (budget 1680 s), 13 steps, 8 of them NOT VERIFIED (upper bounds used).

- Σ medians = **1163 s** → ends **16:24:22** → fits.
- Σ p95 = **3730 s** → ends **17:07:10** → does NOT fit.
- Terms (s, median/p95; `≤` marks an upper bound): regime_collector_pm ≤204/≤730, atp2_research_eod 0.6/0.9, at_session_review ≤40/≤40, repricer_reconcile_lookthrough 25/56, stale_proposal_sweeper_report 0.5/0.8, finviz_industry_groups ≤15/≤16, llm_intelligence_enrichment_pm 81/88, strategy_tilt ≤0.7/≤1.6, technicals_gap_backfill ≤213/≤1054, paper_execution_quality_analyzer ≤213/≤1054, inference_cycle_pm 218/243, audit_enrichment_coverage ≤76/≤223, research_intelligence_queue_drain ≤76/≤223
- Verdict: fits at medians with 9 min to spare; p95 overflows only because 8 of 13 steps carry PAM upper bounds from crowded minutes (16:05 and 16:30 groups). The two VERIFIED slow steps are NOT in the stage: `trade_ai_orchestrator --run-label 1600` (median 1260 s = 21 min) and `--run-label 1730` (719 s) stay their own lines — a serial stage would push every later step by their runtime.

**broker-truth at 16:30 does not exist as a dependency matter.** 16:30 precedes `sync_basis_from_broker` 16:33 (L498), the intraday Schwab syncs at 16:48/16:52 (L485/L531) and `positions_sync` 17:20 (L1070, timeout 120 s). The earliest slot after the last sync is **17:25**:

**broker-truth at 17:25 (deadline 17:35)** — start 17:25, deadline 17:35 (budget 600 s), 2 steps, 2 of them NOT VERIFIED (upper bounds used).

- Σ medians = **198 s** → ends **17:28:18** → fits.
- Σ p95 = **325 s** → ends **17:30:24** → fits.
- Terms (s, median/p95; `≤` marks an upper bound): audit_position_basis ≤2.3/≤2.6, investment_costs_ledger ≤196/≤322
- Verdict: fits at medians and at p95. `positions_proof_daily` (L1072, 17:25 `--send`) stays on its own line while the operator's 10-trading-day phase-2 proof runs ("day N of 10" from 2026-10-07); `journal_review_builder` (L486, 18:30) stays because it needs the 18:15 transaction ingest.

**planning at 17:30 collides with broker-truth at 17:25**, so it is proposed at **17:35**:

**planning at 17:35 (deadline 18:40, the window end)** — start 17:35, deadline 18:40 (budget 3900 s), 14 steps, 12 of them NOT VERIFIED (upper bounds used).

- Σ medians = **1286 s** → ends **17:56:26** → fits.
- Σ p95 = **6480 s** → ends **19:22:59** → does NOT fit.
- Terms (s, median/p95; `≤` marks an upper bound): strategy_audits ≤196/≤322, paper_execution_quality_events ≤123/≤909, sector_rs_daily ≤77/≤340, sector_momentum_engine ≤184/≤343, plan_drift_revalidator_pm ≤184/≤343, afterhours_candidate_preparation 2.5/2.7, watchlist_entry_planner ≤52/≤93, watchlist_entry_planner_proposals ≤120/≤156, defense_recommendations ≤100/≤126, defense_inverse_stoplights ≤1.9/≤2.2, compute_source_weights ≤1.3/≤19, data_gap_resolver_pre_overnight ≤83/≤126, trade_backtest_engine 116/137, trade_thesis_review_engine ≤45/≤3561
- Verdict: fits at medians (ends 17:56); the p95 sum is dominated by upper bounds (12 of 14 unverified; `trade_thesis_review_engine`'s 3561 s p95 is the daily `report_agent_number_grounding` sharing the 18:40 minute, not the step). Instrument before cutover.

**Serial post-close verdict:** close-capture (16:05) fits; broker-truth cannot be 16:30 — 17:25 fits; planning moves to 17:35 and fits at medians. Too slow for serial and kept parallel: `trade_ai_orchestrator` 16:00 (1260 s VERIFIED) and 17:30 (719 s VERIFIED), `run_watch_review_workers` Maria/CIO (45 m timeouts), `finviz_sector_research` 16:15 and `run_pullback_macd_screener` 16:40 (NOT VERIFIED, loose ≥800 s bounds — instrument first).

### 2b. Premarket — 05:45 → must finish before the 07:30 brief

**premarket at 05:45 (deadline 07:25, five minutes before the brief)** — start 05:45, deadline 07:25 (budget 6000 s), 40 steps, 32 of them NOT VERIFIED (upper bounds used).

- Σ medians = **2989 s** → ends **06:34:48** → fits.
- Σ p95 = **5615 s** → ends **07:18:35** → fits.
- Terms (s, median/p95; `≤` marks an upper bound): catalyst_calibration ≤60/≤64, catalyst_calibration_monitor ≤24/≤65, register_analyst_sources ≤24/≤65, overnight_batch_outcomes 0.1/0.1, source_outcome_attribution ≤20/≤22, indicator_cache_refresh 390/397, sec_form4_momentum_context ≤20/≤22, mint_identity_registry ≤2.1/≤2.3, social_ingest 52/52, strategy_backtester 2.0/2.0, backtest_history_snapshot ≤1.0/≤1.0, fred_data_ingest 5.0/6.1, candidate_discovery_orchestrator ≤36/≤56, backtest_results_aggregator ≤1.0/≤1.0, watch_directives_monitor ≤9.9/≤117, market_regime_collector_am ≤51/≤124, classify_candidates ≤290/≤757, market_regime_classifier ≤290/≤757, earnings_enrich ≤290/≤757, research_intelligence_materialize ≤231/≤749, fund_technicals_enrich ≤3.1/≤3.1, refresh_symbol_cards ≤58/≤86, build_lesson_candidates ≤58/≤85, distributions_enrich ≤3.1/≤7.6, sync_watchlist_items_to_db ≤60/≤70, build_symbol_profiles ≤60/≤70, volatility_tier_refresh ≤60/≤70, watch_valuation_backfill 360/381, cio_draft_plan_hygiene ≤10/≤14, materialize_income_engine ≤1.0/≤3.1, agent_watchlist_engine 0.1/0.1, llm_retry_monitor ≤66/≤138, iris_taxonomy_agent ≤66/≤138, opening_intelligence ≤66/≤79, research_watchlist_discovery ≤66/≤79, sync_dividend_data ≤9.3/≤10, recommendation_intelligence_engine ≤6.8/≤11, price_db_sync ≤78/≤117, llm_intelligence_enrichment_am 78/117, iris_proposal_curator ≤76/≤117
- Verdict: fits at medians (ends 06:35) and at p95 (ends 07:19) — with 32 of 40 terms being conservative upper bounds. Too slow or wrong lane, kept parallel: `portfolio_orchestrator` 07:15 (970 s median / 2289 s p95 VERIFIED), `holdings_llm_refresh` 07:15 (356 s VERIFIED, LLM lane), `external_market_data_ingest` 07:15 and `write_state_freshness_history` 07:15 (NOT VERIFIED, share the 07:15 group with the orchestrator), `build_catalyst_graph` and `pro_analyst_fetch` 06:10 (one of them takes ~430 s, attribution ambiguous), `microstructure_recorder` 06:00 (3.5 h session recorder).

### 2c. Hermes chains

**hermes_learning / learn at 10:50 (deadline 11:50)** — start 10:50, deadline 11:50 (budget 3600 s), 6 steps, 2 of them NOT VERIFIED (upper bounds used).

- Σ medians = **466 s** → ends **10:57:46** → fits.
- Σ p95 = **568 s** → ends **10:59:27** → fits.
- Terms (s, median/p95; `≤` marks an upper bound): outcome_grader 6.0/7.0, tag_engine 245/252, outcome_feedback_agent 4.0/6.7, outcome_learning 2.0/2.0, score_history_retention ≤72/≤133, config_governor ≤138/≤167

**hermes_learning / tune at 17:00 (deadline 17:15)** — start 17:00, deadline 17:15 (budget 900 s), 1 steps, 1 of them NOT VERIFIED (upper bounds used).

- Σ medians = **123 s** → ends **17:02:03** → fits.
- Σ p95 = **824 s** → ends **17:13:43** → fits.
- Terms (s, median/p95; `≤` marks an upper bound): autonomous_self_tune ≤123/≤824

**hermes_overnight / night at 02:20 (deadline 06:15)** — start 02:20, deadline 06:15 (budget 14100 s), 7 steps, 7 of them NOT VERIFIED (upper bounds used).

- Σ medians = **212 s** → ends **02:23:31** → fits.
- Σ p95 = **526 s** → ends **02:28:45** → fits.
- Terms (s, median/p95; `≤` marks an upper bound): backlog_drain ≤94/≤371, universe_history_retention ≤0.4/≤0.4, discovery_yield_builder ≤19/≤32, tag_lift_discovery ≤1.9/≤3.1, industry_novelty_discovery ≤0.4/≤0.5, discovery_scorecard ≤60/≤64, siem_to_hermes_backlog ≤36/≤54
- `hermes_backlog_drain` carries `--max-runtime 3000`: worst case 50 min, still inside the window.

**hermes_overnight / close at 23:13 (deadline 23:59)** — start 23:13, deadline 23:59 (budget 2760 s), 2 steps, 1 of them NOT VERIFIED (upper bounds used).

- Σ medians = **274 s** → ends **23:17:33** → fits.
- Σ p95 = **282 s** → ends **23:17:42** → fits.
- Terms (s, median/p95; `≤` marks an upper bound): commit_hermes_daily 0.0/0.1, source_curation ≤274/≤282

## 3. What `_pipeline_common.sh` and the 199E skeletons actually do (Part 2)

`scripts/pipelines/_pipeline_common.sh` (102 lines): `run_step` **exists but executes nothing in either mode** — in DRY_RUN it echoes `would run`, with `--apply` it prints `[SKELETON] --apply set but child steps are NOT wired`; it writes **no receipt**, applies **no timeout**, has **no continue-on-error** (there is nothing to continue from). What it does provide and this tranche reuses: `load_env` (fails loudly on a corrupt `.env`), `assert_no_live_trading` / `assert_no_level7`, `acquire_lock` (one flock per pipeline name, already-running = clean skip), `_ts`, and the `--apply`/`--dry-run` parse. `run_governance_pipeline.sh` and `run_portfolio_maintenance_pipeline.sh` do NOT use `run_step`; each has its own `gov_step`/`pm_step` that executes, times (`EPOCHREALTIME`), never cascades, and writes a summary JSON — the pattern this tranche generalises.

The five unscheduled skeletons (`run_tradeai_market_pipeline.sh`, `run_tradeai_after_close_pipeline.sh`, `run_hermes_research_pipeline.sh`, `run_llm_control_pipeline.sh`, `run_hermes_advisory_pipeline.sh`) each call `pipeline_start` + 4–7 `run_step` lines: they name scripts (`alpaca_paper_reconciler.py --journal`, `multi_tier_trade_reviewer.py`, `trade_close_llm_analyzer.py`, `send_alert_digest.py`, `hermes_source_discovery.py`, `high_llm_execution_worker.py`, `gpu_lifecycle.py`, `hermes_second_opinion.py`, …) with **no cron line, lock, timeout, env or wrapper**, several of which are not the scripts the live crontab runs. Their DRY_RUN skeleton executes nothing, and `--apply` also executes nothing. They are left untouched; `run_tradeai_after_close_pipeline.sh` is superseded by `run_after_close_pipeline.sh` (manifest-driven) rather than extended, because its step list does not match the live lines.

## 4. The skeleton delivered (Part 3)

| File | Role |
|---|---|
| `scripts/pipelines/_manifest_runner.sh` | shared stage runner: `--dry-run` default; `--apply` executes only manifest steps and only when the stage has ≥1 step; one flock per stage; per step: own flock + `timeout -k 30`, stdout/stderr appended to the cron line's own log, `PipelineStepReceipt@v1` line, continue-on-error; `PipelineRun@v1` summary at `data/runtime/pipeline_<name>_<stage>_last.json` on every invocation (dry-run included) = the lane output_signal; `--project-root` for hermetic tests; `PIPELINE_TODAY_DOW` override; `$PY` resolved like `market_day_gate.sh` (crontab `$PY` → `CURRENT/.venv` → dev venv → python3) |
| `scripts/pipelines/pipeline_manifest.py` | validates `PipelineManifest@v1` (every command a verbatim slice of its `cron_line_verbatim`; `FORBIDDEN_COMMAND_TOKENS` = broker/stop/order/market_day_gate/staggered-sync scripts; `dow` filter), prints the plan, writes the summary. `NO_CONSUMER_REASON` declared (consumers are the bash runners). |
| `scripts/pipelines/run_after_close_pipeline.sh --stage {close-capture,broker-truth,planning}` | rank 5 |
| `scripts/pipelines/run_premarket_data_pipeline.sh` | rank 6 (single stage `premarket`) |
| `scripts/pipelines/run_hermes_pipeline.sh --manifest … --stage {learn,tune,night,close}` | rank 7 |
| `config/pipelines/after_close.json`, `premarket.json`, `hermes_learning.json`, `hermes_overnight.json` | manifests: verbatim commands, locks/timeouts/env/wrappers, `measured` block per step, `deferred` (too slow / unverified) and `excluded` (with category + reason) lists |
| `tests/test_pipeline_manifest_runner_20261007.py` | 18 hermetic tests (true/false/sleep manifests; dry-run executes nothing; empty `--apply` executes nothing; order, timeout, continue-on-error, receipts, held lock = clean skip; committed manifests verbatim + exclusions; runner never names an LLM wrapper; `bash -n`); registered in `run_cio_hardening_ci.py` gate `cron_tranche_b_20261007` |
| `config/lane_registry.json` | 8 `NEVER_SCHEDULED` rows (one per stage) with `output_signal` = the summary JSON, `state_reason`, `reason_evidence` |
| `../ledgers/window_runtimes_20261007.{json,md}` | the measurement ledger |

Timeout rule used in the manifests: a step's own `timeout N` → N + 60 s (N + 300 s when N ≥ 300); otherwise 3 × p95 (or upper-bound p95) rounded up to 5 min, clamped to [5 min, 30 min]. `dow` is copied from the cron line so daily lines keep weekend runs inside a daily stage.

## 5. Manifest mapping tables (cron line → step)

### 5a. `after_close.json`

**Stage `close-capture`** — proposed `5 16 * * 1-5`, window 16:05-16:30; must finish before 16:33 sync_basis_from_broker (own line)

| # | cron L | today | step id | script | median s | p95 s | measured | timeout | flags |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 224 | 16:05 | `regime_collector_pm` | `market_regime_collector.py` | ≤204 | ≤730 | UPPER BOUND (PAM group) — NOT VERIFIED | 30m |  |
| 2 | 225 | 16:05 | `atp2_research_eod` | `run_scheduled_atp2_research_cycle.sh` | 0.6 | 0.9 | VERIFIED (pipeline_runs, n=5) | 5m | DEV_TREE_WRAPPER |
| 3 | 1061 | 16:10 | `at_session_review` | `active_trader/session_review.py` | ≤40 | ≤40 | UPPER BOUND (PAM group) — NOT VERIFIED | 600s |  |
| 4 | 469 | 16:10 | `repricer_reconcile_lookthrough` | `safe_flock.sh` | 25 | 56 | VERIFIED (safe_flock, n=5) | 5m |  |
| 5 | 179 | 16:10 | `stale_proposal_sweeper_report` | `run_scheduled_stale_proposal_sweeper.sh` | 0.5 | 0.8 | VERIFIED (pipeline_runs, n=5) | 5m | DEV_TREE_WRAPPER |
| 6 | 793 | 16:18 | `finviz_industry_groups` | `finviz_industry_groups.py` | ≤15 | ≤16 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 7 | 194 | 16:20 | `llm_intelligence_enrichment_pm` | `llm_intelligence_enrichment.py` | 81 | 88 | VERIFIED (log_end, n=5) | 5m |  |
| 8 | 549 | 16:25 | `strategy_tilt` | `strategy_tilt.py` | ≤0.7 | ≤1.6 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 9 | 502 | 16:30 | `technicals_gap_backfill` | `technicals_gap_backfill.py` | ≤213 | ≤1054 | UPPER BOUND (PAM group) — NOT VERIFIED | 30m |  |
| 10 | 341 | 16:30 | `paper_execution_quality_analyzer` | `paper_execution_quality_analyzer.py` | ≤213 | ≤1054 | UPPER BOUND (PAM group) — NOT VERIFIED | 30m |  |
| 11 | 562 | 16:30 | `inference_cycle_pm` | `bash` | 218 | 243 | VERIFIED (log_end, n=5) | 15m |  |
| 12 | 504 | 16:45 | `audit_enrichment_coverage` | `audit_enrichment_coverage.py` | ≤76 | ≤223 | UPPER BOUND (PAM group) — NOT VERIFIED | 15m |  |
| 13 | 771 | 16:45 | `research_intelligence_queue_drain` | `research_intelligence_queue.py` | ≤76 | ≤223 | UPPER BOUND (PAM group) — NOT VERIFIED | 15m |  |

**Stage `broker-truth`** — proposed `25 17 * * 1-5`, window 17:25-17:35

The study proposed 16:30 for this stage; 16:30 precedes the 16:33 basis sync, the 16:48/16:52 intraday Schwab syncs and the 17:20 positions_sync, so it cannot be the broker-truth stage. 17:25 is the earliest slot after positions_sync (17:20 + 120 s timeout).

Depends on lines that stay their own: sync_basis_from_broker 16:33 (L498), schwab_position_sync last 16:52 (L531), positions_sync 17:20 timeout 120s (L1070) — all stay as their own lines; this stage only READS their outputs

| # | cron L | today | step id | script | median s | p95 s | measured | timeout | flags |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 499 | 16:35 | `audit_position_basis` | `audit_position_basis.py` | ≤2.3 | ≤2.6 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 2 | 805 | 17:05 | `investment_costs_ledger` | `investment_costs.py"` | ≤196 | ≤322 | UPPER BOUND (PAM group) — NOT VERIFIED | 20m |  |

**Stage `planning`** — proposed `35 17 * * 1-5`, window 17:35-18:40

| # | cron L | today | step id | script | median s | p95 s | measured | timeout | flags |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 656 | 17:05 | `strategy_audits` | `run_scheduled_strategy_audits.sh` | ≤196 | ≤322 | UPPER BOUND (PAM group) — NOT VERIFIED | 20m | DEV_TREE_WRAPPER |
| 2 | 342 | 17:00 | `paper_execution_quality_events` | `paper_execution_quality.py` | ≤123 | ≤909 | UPPER BOUND (PAM group) — NOT VERIFIED | 30m |  |
| 3 | 785 | 17:20 | `sector_rs_daily` | `sector_rs_daily.py` | ≤77 | ≤340 | UPPER BOUND (PAM group) — NOT VERIFIED | 20m |  |
| 4 | 791 | 17:25 | `sector_momentum_engine` | `sector_momentum_engine.py"` | ≤184 | ≤343 | UPPER BOUND (PAM group) — NOT VERIFIED | 20m |  |
| 5 | 708 | 17:25 | `plan_drift_revalidator_pm` | `plan_drift_revalidator.py` | ≤184 | ≤343 | UPPER BOUND (PAM group) — NOT VERIFIED | 20m |  |
| 6 | 206 | 17:30 | `afterhours_candidate_preparation` | `run_afterhours_candidate_preparation.sh` | 2.5 | 2.7 | VERIFIED (pipeline_runs, n=5) | 5m |  |
| 7 | 505 | 17:35 | `watchlist_entry_planner` | `watchlist_entry_planner.py` | ≤52 | ≤93 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 8 | 506 | 17:45 | `watchlist_entry_planner_proposals` | `watchlist_entry_planner.py` | ≤120 | ≤156 | UPPER BOUND (PAM group) — NOT VERIFIED | 10m |  |
| 9 | 795 | 17:50 | `defense_recommendations` | `defense_recommendations.py"` | ≤100 | ≤126 | UPPER BOUND (PAM group) — NOT VERIFIED | 10m |  |
| 10 | 807 | 17:55 | `defense_inverse_stoplights` | `defense_inverse_stoplights.py"` | ≤1.9 | ≤2.2 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 11 | 493 | 18:10 | `compute_source_weights` | `compute_source_weights.py` | ≤1.3 | ≤19 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 12 | 153 | 18:00 | `data_gap_resolver_pre_overnight` | `data_gap_resolver.py` | ≤83 | ≤126 | UPPER BOUND (PAM group) — NOT VERIFIED | 10m |  |
| 13 | 381 | 18:30 | `trade_backtest_engine` | `safe_flock.sh` | 116 | 137 | VERIFIED (safe_flock, n=5) | 10m |  |
| 14 | 740 | 18:40 | `trade_thesis_review_engine` | `trade_thesis_review_engine.py` | ≤45 | ≤3561 | UPPER BOUND (PAM group) — NOT VERIFIED | 30m |  |

**Deferred — too slow or not verified; stays a parallel line** (6)

| cron L | today | script | category | reason |
|---|---|---|---|---|
| 148 | 16:00 | `trade_ai_orchestrator.py` | DEFERRED_PARALLEL_LANE | VERIFIED too slow for a serial stage: trade_ai_orchestrator --run-label 1600 median 1260 s / p95 1261 s (safe_flock). Stays its own 16:00 line; a serial stage would push every later step by 21 min. |
| 205 | 17:30 | `trade_ai_orchestrator.py` | DEFERRED_PARALLEL_LANE | VERIFIED too slow for a serial stage: trade_ai_orchestrator --run-label 1730 median 719 s / p95 801 s. Stays its own 17:30 line. |
| 556 | 10:15 (15 10,16) | `finviz_sector_research.py` | DEFERRED_PARALLEL_LANE | NOT VERIFIED and the 16:15 group upper bound is loose (median 832 s, p95 1080 s); the line also fires at 10:15. Instrument with a receipt during the parallel-run week, then decide. |
| 647 | 16:40 | `run_pullback_macd_screener.sh` | DEFERRED_PARALLEL_LANE | NOT VERIFIED; 16:40 group upper bound 886 s median shared with the paid hermes_subject_enhance closed_trade line. No log on the cron line. Instrument first. |
| 864 | 16:05 | `run_watch_review_workers.py` | DEFERRED_PARALLEL_LANE | run_watch_review_workers (Maria, Mon/Wed/Fri, timeout 45m): LLM review lane, too long for a serial stage; stays parallel. |
| 866 | 16:20 | `run_watch_review_workers.py` | DEFERRED_PARALLEL_LANE | run_watch_review_workers (CIO, Mon/Wed/Fri, timeout 45m): LLM review lane; stays parallel. |

**Excluded — never a step** (40)

| cron L | today | script | category | reason |
|---|---|---|---|---|
| 149 | 16:00 | `send_alert_digest.py` | MARKET_DAY_GATE | market_day_gate line (alert digest send) — excluded by rule; also a Telegram send (rank 10 digest scheduler) |
| 243 | 16:05 | `eod_open_trade_alert.py` | MARKET_DAY_GATE | market_day_gate line (eod_open_trade_alert) — excluded by rule; NOTE: the gate falls back to the dev venv because CURRENT has no .venv (log shows the probe error on every run) |
| 339 | 07:00 (0 7,9,12,16,20) | `event_detector.py` | MARKET_DAY_GATE | market_day_gate line (event detector 7,9,12,16,20) — excluded by rule |
| 677 | 17:35 | `stop_drift_alert.py` | BROKER_STOP | market_day_gate line + stop drift alert — broker/stop |
| 512 | 17:35 | `snaptrade_sync.py` | BROKER_SYNC | market_day_gate line + snaptrade_sync — staggered broker sync stays its own line |
| 531 | 09:07 (7,22,37,52 9-16) | `schwab_position_sync.py` | BROKER_SYNC | schwab_position_sync 7,22,37,52 9-16 — staggered broker sync with its own lock and minute offset |
| 485 | 09:03 (3,18,33,48 9-16) | `schwab_transaction_ingest.py` | BROKER_SYNC | schwab_transaction_ingest 3,18,33,48 9-16 — staggered broker sync |
| 484 | 18:15 | `schwab_transaction_ingest.py` | BROKER_SYNC | schwab_transaction_ingest 18:15 — broker sync |
| 1070 | 17:20 | `positions_sync.py` | BROKER_SYNC | positions_sync 17:20 (timeout 120) — broker sync; the broker-truth stage is placed AFTER it |
| 1072 | 17:25 | `positions_proof_daily.py` | OPERATOR_PROOF_IN_FLIGHT | positions_proof_daily 17:25 --send — the operator-approved positions phase-2 proof (10 trading days, nightly "day N of 10" from 2026-10-07) is RUNNING on this line; do not move it until the proof completes, then revisit as a broker-truth step |
| 498 | 16:33 | `sync_basis_from_broker.py` | BROKER_SYNC | sync_basis_from_broker 16:33 — broker read sync (writes basis from the broker API); stays its own line |
| 348 | 16:45 | `atm_position_reconciler.py` | BROKER_ADJACENT | atm_position_reconciler (safe_flock, log directory missing — never executes; tranche A decision D5 pending) — broker-adjacent |
| 806 | 18:35 | `schwab_econfirm_reconcile.py` | BROKER_ADJACENT | schwab_econfirm_reconcile 18:35 — Schwab eConfirm (Gmail) vs broker ledger reconcile; broker-adjacent read |
| 794 | 17:35 | `options_chain_snapshot.py` | BROKER_ADJACENT | options_chain_snapshot 17:35 — Schwab option-chain API read; options family (rank 13), broker-adjacent |
| 733 | 16:05 | `run_options_monitor.sh` | OPTIONS_FAMILY | run_options_monitor.sh 16:05 — options family (rank 13), operator-requested lines merge only as ordered steps with cadence unchanged; wrapper header empty |
| 735 | 17:10 | `run_options_paper_position_monitor.sh` | OPTIONS_FAMILY | run_options_paper_position_monitor.sh 17:10 — options family (rank 13) |
| 500 | 17:05 | `holding_protection_advisor.py` | STOP_ADVISORY | holding_protection_advisor 17:05 — LLM stop / trailing-stop advisory for the REAL account: stop-adjacent, keep failure isolation |
| 503 | 17:20 | `holding_protection_advisor.py` | STOP_ADVISORY | holding_protection_advisor (grok, Mon 17:20) — stop-adjacent + paid lane |
| 774 | 17:40 | `holdings_gain_guardian.py` | STOP_ADVISORY | holdings_gain_guardian 17:40 — exit/trim intelligence on the LIVE book (SHADOW); stop-adjacent |
| 204 | 16:30 | `run_closed_trade_digest_cron.sh` | OPERATOR_SEND | closed_trade_digest 16:30 — operator send; digest scheduler is rank 10 (also a dev-tree wrapper) |
| 787 | 17:55 | `alert_daily_digest.py` | OPERATOR_SEND | alert_daily_digest 17:55 — operator send; rank 10 |
| 1028 | 16:15 | `notify_material_change.py` | OPERATOR_SEND | notify_material_change 16:15 daily — operator send; rank 10 |
| 481 | 16:40 | `hermes_subject_enhance.py` | HERMES_OWNED | hermes_subject_enhance closed_trade 16:40 (grok+chatgpt paid lanes) — rank 9 dispatcher |
| 608 | 10:20 (20 10,16) | `hermes_think_tank.py` | HERMES_OWNED | hermes_think_tank 10:20/16:20 — Hermes deep synthesis; rank 7/8 |
| 859 | 18:15 | `hermes_research_agenda.py` | HERMES_OWNED | hermes_research_agenda 18:15 — Hermes; rank 8 |
| 610 | 17:00 | `hermes_autonomous_self_tune.py` | HERMES_OWNED | hermes_autonomous_self_tune 17:00 — absorbed by config/pipelines/hermes_learning.json stage tune, not here |
| 655 | 16:30 | `proposal_monitor.py` | PROPOSAL_LIFECYCLE | proposal_monitor 16:30 — proposal lifecycle worker is rank 11 |
| 486 | 18:30 | `journal_review_builder.py` | DEPENDS_ON_LATER_BROKER_SYNC | journal_review_builder 18:30 — depends on the 18:15 schwab_transaction_ingest; no stage runs after 18:15 inside the window, so it stays its own line |
| 902 | 17:17 | `run_governed_symbol_thesis_acquisition.sh` | BROKEN_WRAPPER | run_governed_symbol_thesis_acquisition 17:17 — wrapper exits before logging (dev-tree default path; study §2); fix the tree first |
| 878 | 18:00 | `ops_daily_digest.py` | OTHER_TREE | ops_daily_digest 18:00 — OpenClaw tree, other operator surface |
| 397 | 18:00 (0 18,22) | `catalyst_momentum_engine.py` | CADENCE_MISMATCH | catalyst_momentum_engine overnight 18:00,22:00 daily — daily cadence incl. weekends and a second firing; not a weekday stage member |
| 314 | 18:30 | `topic_curator.py` | CADENCE_MISMATCH | topic_curator 18:30 daily — daily cadence incl. weekends |
| 151 | 18:00 | `rescan_tickets.py` | CADENCE_MISMATCH | rescan_tickets 18:00 daily — daily cadence; log file never created (NOT VERIFIED that it runs) |
| 1032 | 18:20 | `sweep_commitment_outcomes.py` | CADENCE_MISMATCH | sweep_commitment_outcomes 18:20 daily — CIO lane, daily cadence |
| 1052 | 18:40 | `report_agent_number_grounding.py` | CADENCE_MISMATCH | report_agent_number_grounding 18:40 daily — governance report, daily cadence |
| 797 | 18:15 | `defense_weekly_paid_review.py` | CADENCE_MISMATCH | defense_weekly_paid_review Fri 18:15 — weekly + paid lane |
| 1049 | 08:20 (20 8,12,17,21) | `sec_filings_feed.py` | PASS_THROUGH | sec_filings_feed 8,12,17,21 — multi-hour line passing through the window |
| 1011 | 07:20 (20 7,12,17) | `catalyst_symbol_impact_writer.py` | PASS_THROUGH | catalyst_symbol_impact_writer 7,12,17 — multi-hour line passing through |
| 1013 | 08:40 (40 8,12,16) | `watch_goods_consistency_check.py` | PASS_THROUGH | watch_goods_consistency_check 8,12,16 — multi-hour line passing through |
| 92 | 07:45 (45 7,10,12,13,16) | `run_scheduled_quote_refresh.sh` | PASS_THROUGH | run_scheduled_quote_refresh incubator 7,10,12,13,16 — multi-hour line (quote refresh; shares a lock with the */5 line — study §3) |

### 5b. `premarket.json`

**Stage `premarket`** — proposed `45 5 * * *`, window 05:45-07:25; must finish before 07:30 send_morning_brief (market_day_gate line L175, NOT a step)

| # | cron L | today | step id | script | median s | p95 s | measured | timeout | flags |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 429 | 05:30 | `catalyst_calibration` | `catalyst_calibration.py` | ≤60 | ≤64 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 2 | 458 | 05:40 | `catalyst_calibration_monitor` | `catalyst_calibration_monitor.py` | ≤24 | ≤65 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 3 | 622 | 05:40 | `register_analyst_sources` | `register_analyst_sources.py` | ≤24 | ≤65 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 4 | 631 | 05:40 | `overnight_batch_outcomes` | `overnight_batch.py` | 0.1 | 0.1 | VERIFIED (pipeline_runs, n=7) | 5m |  |
| 5 | 454 | 05:45 | `source_outcome_attribution` | `source_outcome_attribution.py` | ≤20 | ≤22 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 6 | 266 | 05:45 | `indicator_cache_refresh` | `indicator_cache_refresh.py` | 390 | 397 | VERIFIED (log_end, n=5) | 20m |  |
| 7 | 674 | 05:45 | `sec_form4_momentum_context` | `run_sec_form4_momentum_context.py` | ≤20 | ≤22 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 8 | 916 | 05:50 | `mint_identity_registry` | `mint_identity_registry.py` | ≤2.1 | ≤2.3 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 9 | 254 | 06:00 | `social_ingest` | `social_ingest.py` | 52 | 52 | VERIFIED (pipeline_runs, n=5) | 5m |  |
| 10 | 367 | 06:00 | `strategy_backtester` | `safe_flock.sh` | 2.0 | 2.0 | VERIFIED (safe_flock, n=5) | 5m |  |
| 11 | 379 | 06:10 | `backtest_history_snapshot` | `safe_flock.sh` | 1.0 | 1.0 | partial (safe_flock, 3/5) | 5m |  |
| 12 | 259 | 06:15 | `fred_data_ingest` | `fred_data_ingest.py` | 5.0 | 6.1 | VERIFIED (pipeline_runs, n=7) | 5m |  |
| 13 | 898 | 06:15 | `candidate_discovery_orchestrator` | `candidate_discovery_orchestrator.py` | ≤36 | ≤56 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 14 | 639 | 06:20 | `backtest_results_aggregator` | `backtest_results_aggregator.py` | 1.0 | 1.0 | partial (log_end, 1/5) | 5m |  |
| 15 | 467 | 06:20 | `watch_directives_monitor` | `watch_directives_monitor.py` | ≤9.9 | ≤117 | UPPER BOUND (PAM group) — NOT VERIFIED | 10m |  |
| 16 | 210 | 06:30 | `market_regime_collector_am` | `market_regime_collector.py` | ≤51 | ≤124 | UPPER BOUND (PAM group) — NOT VERIFIED | 10m |  |
| 17 | 215 | 06:35 | `classify_candidates` | `classify_candidates.py` | ≤290 | ≤757 | UPPER BOUND (PAM group) — NOT VERIFIED | 30m |  |
| 18 | 216 | 06:35 | `market_regime_classifier` | `market_regime_classifier.py` | ≤290 | ≤757 | UPPER BOUND (PAM group) — NOT VERIFIED | 30m |  |
| 19 | 583 | 06:35 | `earnings_enrich` | `earnings_enrich.py"` | ≤290 | ≤757 | UPPER BOUND (PAM group) — NOT VERIFIED | 30m |  |
| 20 | 776 | 06:35 | `research_intelligence_materialize` | `research_intelligence_materialize.py` | ≤231 | ≤749 | UPPER BOUND (PAM group) — NOT VERIFIED | 30m |  |
| 21 | 584 | 06:38 | `fund_technicals_enrich` | `fund_technicals_enrich.py"` | ≤3.1 | ≤3.1 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 22 | 534 | 06:40 | `refresh_symbol_cards` | `refresh_symbol_cards.py` | ≤58 | ≤86 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 23 | 915 | 06:40 | `build_lesson_candidates` | `build_lesson_candidates.py` | ≤58 | ≤85 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 24 | 585 | 06:42 | `distributions_enrich` | `distributions_enrich.py"` | ≤3.1 | ≤7.6 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 25 | 221 | 06:45 | `sync_watchlist_items_to_db` | `sync_watchlist_items_to_db.py` | ≤60 | ≤70 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 26 | 540 | 06:45 | `build_symbol_profiles` | `build_symbol_profiles.py` | ≤60 | ≤70 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 27 | 754 | 06:45 | `volatility_tier_refresh` | `volatility_tier_refresh.py` | ≤60 | ≤70 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 28 | 836 | 06:47 | `watch_valuation_backfill` | `watch_valuation_backfill.py` | 360 | 381 | VERIFIED (pam_exact, n=7) | 20m |  |
| 29 | 947 | 06:52 | `cio_draft_plan_hygiene` | `cio_draft_plan_hygiene.py` | ≤10 | ≤14 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 30 | 231 | 06:55 | `materialize_income_engine` | `materialize_income_engine.py` | ≤1.0 | ≤3.1 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 31 | 275 | 07:00 | `agent_watchlist_engine` | `agent_watchlist_engine.py` | 0.1 | 0.1 | VERIFIED (pipeline_runs, n=7) | 5m |  |
| 32 | 463 | 07:00 | `llm_retry_monitor` | `llm_retry_monitor.py` | ≤66 | ≤138 | UPPER BOUND (PAM group) — NOT VERIFIED | 10m |  |
| 33 | 813 | 07:00 | `iris_taxonomy_agent` | `iris_taxonomy_agent.py` | ≤66 | ≤138 | UPPER BOUND (PAM group) — NOT VERIFIED | 10m |  |
| 34 | 825 | 07:00 | `opening_intelligence` | `opening_intelligence.py` | ≤66 | ≤79 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 35 | 895 | 07:00 | `research_watchlist_discovery` | `research_watchlist_discovery.py` | ≤66 | ≤79 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 36 | 227 | 07:05 | `sync_dividend_data` | `sync_dividend_data.py` | ≤9.3 | ≤10 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 37 | 535 | 07:10 | `recommendation_intelligence_engine` | `recommendation_intelligence_engine.py` | ≤6.8 | ≤11 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 38 | 192 | 07:20 | `price_db_sync` | `price_db_sync.py` | ≤78 | ≤117 | UPPER BOUND (PAM group) — NOT VERIFIED | 10m |  |
| 39 | 193 | 07:20 | `llm_intelligence_enrichment_am` | `llm_intelligence_enrichment.py` | 78 | 117 | VERIFIED (log_end, n=5) | 10m |  |
| 40 | 409 | 07:20 | `iris_proposal_curator` | `iris_proposal_curator.py` | ≤76 | ≤117 | UPPER BOUND (PAM group) — NOT VERIFIED | 10m |  |

**Deferred — too slow or not verified; stays a parallel line** (8)

| cron L | today | script | category | reason |
|---|---|---|---|---|
| 189 | 07:15 | `portfolio_orchestrator.py` | DEFERRED_PARALLEL_LANE | VERIFIED too slow: portfolio_orchestrator median 970 s / p95 2289 s / max 2519 s (safe_flock). Stays its own 07:15 line (parallel lane). |
| 399 | 07:15 | `holdings_llm_refresh.py` | DEFERRED_PARALLEL_LANE | VERIFIED 356 s median / 422 s p95 but an LLM lane (holdings_llm_refresh, AGENT_DECISION_PAYLOAD=1): keep as its own 07:15 line so the paid work stays isolated. |
| 183 | 07:15 | `external_market_data_ingest.py` | DEFERRED_PARALLEL_LANE | NOT VERIFIED; the 07:15 group upper bound is loose (median 1104 s) because portfolio_orchestrator shares the minute. external_market_data_ingest also overruns its */15 slot 42% of the time (study §3). Instrument first. |
| 184 | 07:15 | `write_state_freshness_history.py` | DEFERRED_PARALLEL_LANE | NOT VERIFIED (lower bound 0 s, upper bound shares the 07:15 group). Likely fast; instrument during the parallel-run week. |
| 1017 | 06:10 | `build_catalyst_graph.py` | DEFERRED_PARALLEL_LANE | NOT VERIFIED; 06:10 group upper bound 430 s median is shared with pro_analyst_fetch — one of the two takes ~7 min. Instrument both first. |
| 460 | 06:10 | `pro_analyst_fetch.py` | DEFERRED_PARALLEL_LANE | NOT VERIFIED; shares the 06:10 group with build_catalyst_graph (upper 427 s median). Daily line. |
| 1057 | 06:00 | `microstructure_recorder.py` | DEFERRED_PARALLEL_LANE | microstructure_recorder 06:00: a session recorder that runs ~3.5 h (PAM session 12,481 s on both firings) — a daemon-style line, never a serial step. |
| 899 | 06:00 | `drain_discovery_backlog.py` | DEFERRED_PARALLEL_LANE | drain_discovery_backlog 06:00 — Hermes discovery inbox (rank 8 coordinator tick table). |

**Excluded — never a step** (27)

| cron L | today | script | category | reason |
|---|---|---|---|---|
| 816 | 06:12 | `broker_stop_reconcile.py` | BROKER_STOP | broker_stop_reconcile 06:12 — broker is the source of truth for stop coverage: broker/stop line |
| 514 | 07:20 | `snaptrade_activity_ingest.py` | BROKER_SYNC | snaptrade_activity_ingest 07:20 — broker sync |
| 165 | 06:00 | `telegram_smart_alerts.py` | MARKET_DAY_GATE | market_day_gate line (telegram_smart_alerts 06:00) — excluded by rule; operator send |
| 339 | 07:00 (0 7,9,12,16,20) | `event_detector.py` | MARKET_DAY_GATE | market_day_gate line (event detector 07:00) — excluded by rule |
| 175 | 07:30 | `send_morning_brief.py` | OPERATOR_SEND | send_morning_brief 07:30 — the consumer the stage must precede; operator-decided single send (09-14) |
| 1004 | 07:05 | `llm_spend_report.py` | OPERATOR_SEND | llm_spend_report 07:05 — texts the operator; rank 10 |
| 182 | 06:15 | `agent_router_cron.sh` | DEV_TREE_WRAPPER | agent_router_cron.sh 06:15 — dev-tree wrapper with no cron log; fix the tree first (study §6) |
| 196 | 06:25 | `agent_intelligence_cron.sh` | DEV_TREE_WRAPPER | agent_intelligence_cron.sh 06:25 — dev-tree wrapper; PAM group upper bound 1500 s; fix the tree first |
| 860 | 06:20 | `hermes_cross_source_synthesizer.py` | LLM_LANE | hermes_cross_source_synthesizer Mon/Thu 06:20 (llm_priority_guard, timeout 20m) — LLM lane; log never created (study §2) |
| 872 | 06:15 | `siem_to_hermes_backlog.py` | HERMES_OWNED | siem_to_hermes_backlog 06:15 — absorbed by config/pipelines/hermes_overnight.json stage night |
| 869 | 05:30 | `hermes_discovery_scorecard.py` | HERMES_OWNED | hermes_discovery_scorecard 05:30 — absorbed by hermes_overnight.json stage night |
| 443 | 07:30 | `hermes_topic_monitor_bridge.py` | HERMES_OWNED | hermes_topic_monitor_bridge 07:30 — Hermes; at the brief minute, not before it |
| 558 | 06:50 | `crawl_v3_dashboard.py` | NOT_A_PRODUCER | crawl_v3_dashboard 06:50 — visual/error QA crawl of the dashboard, not a brief input |
| 456 | 06:00 | `source_attribution_monitor.py` | NOT_A_PRODUCER | source_attribution_monitor 06:00 — monitor/alarm, not a producer |
| 213 | 07:30 | `alert_missing_conditions.py` | AT_OR_AFTER_BRIEF | alert_missing_conditions 07:30 — at the brief minute |
| 261 | 07:30 | `symbol_enrichment.py` | AT_OR_AFTER_BRIEF | symbol_enrichment 07:30 — at the brief minute (VERIFIED 51 s) |
| 602 | 07:30 | `generate_analyst_daily_digest.py` | AT_OR_AFTER_BRIEF | generate_analyst_daily_digest 07:30 — at the brief minute |
| 427 | 06:45 (45 6,12,18) | `news_to_catalyst.py` | PASS_THROUGH | news_to_catalyst 6,12,18 — multi-hour line passing through |
| 441 | 06:50 (50 6,12,18) | `research_insight_extractor.py` | PASS_THROUGH | research_insight_extractor 6,12,18 — multi-hour line passing through |
| 1011 | 07:20 (20 7,12,17) | `catalyst_symbol_impact_writer.py` | PASS_THROUGH | catalyst_symbol_impact_writer 7,12,17 — multi-hour |
| 1027 | 07:20 (20 7,19) | `drain_cio_stance_classification.py` | PASS_THROUGH | drain_cio_stance_classification 7,19 — multi-hour |
| 430 | 07:00 (0 7,13) | `signal_fusion.py` | PASS_THROUGH | signal_fusion --full 7,13 — multi-hour, overlaps the */30 --active line (study §3) |
| 357 | 06:35 | `overnight_batch.py` | CADENCE_MISMATCH | overnight_batch tax sweep Mon 06:35 — weekly |
| 536 | 06:30 | `classify_instruments.py` | CADENCE_MISMATCH | classify_instruments Sat 06:30 — weekly |
| 537 | 07:00 | `etf_analyst_enrich.py` | CADENCE_MISMATCH | etf_analyst_enrich Sat 07:00 — weekly |
| 552 | 07:15 | `etf_performance_enrich.py` | CADENCE_MISMATCH | etf_performance_enrich Sat 07:15 — weekly |
| 166 | 06:00 | `backup_verify.py` | CADENCE_MISMATCH | backup_verify 1st of month 06:00 — monthly |

### 5c. `hermes_learning.json`

**Stage `learn`** — proposed `50 10 * * *`, window 10:50-11:50

| # | cron L | today | step id | script | median s | p95 s | measured | timeout | flags |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 692 | 10:50 | `outcome_grader` | `safe_flock.sh` | 6.0 | 7.0 | VERIFIED (safe_flock, n=7) | 5m |  |
| 2 | 702 | 11:05 | `tag_engine` | `safe_flock.sh` | 245 | 252 | VERIFIED (safe_flock, n=7) | 15m |  |
| 3 | 696 | 11:25 | `outcome_feedback_agent` | `safe_flock.sh` | 4.0 | 6.7 | VERIFIED (safe_flock, n=7) | 5m |  |
| 4 | 475 | 11:35 | `outcome_learning` | `safe_flock.sh` | 2.0 | 2.0 | VERIFIED (safe_flock, n=7) | 5m |  |
| 5 | 684 | 11:40 | `score_history_retention` | `hermes_score_history_retention.py` | ≤72 | ≤133 | UPPER BOUND (PAM group) — NOT VERIFIED | 10m |  |
| 6 | 705 | 11:45 | `config_governor` | `hermes_config_governor.py` | ≤138 | ≤167 | UPPER BOUND (PAM group) — NOT VERIFIED | 10m |  |

**Stage `tune`** — proposed `0 17 * * *`, window 17:00-17:15

| # | cron L | today | step id | script | median s | p95 s | measured | timeout | flags |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 610 | 17:00 | `autonomous_self_tune` | `hermes_autonomous_self_tune.py` | ≤123 | ≤824 | UPPER BOUND (PAM group) — NOT VERIFIED | 30m |  |

**Excluded** (3)

| cron L | today | script | category | reason |
|---|---|---|---|---|
| 737 | 13:40 | `hermes_analyst_coverage.py` | HERMES_OTHER | hermes_analyst_coverage 13:40 (llm_priority_guard + safe_flock + read-model build) — not part of the 10:50→17:00 learning chain; rank 8 |
| 897 | 11:15 (15 11,15) | `hermes_social_sentiment.py` | HERMES_OTHER | hermes_social_sentiment 11:15/15:15 — not part of the learning chain |
| 985 | *:15 | `hermes_external_feedback_loop.py` | HERMES_OTHER | hermes_external_feedback_loop hourly (LLM_GLOBAL_DAILY_USD_CAP=2.00) — hourly cadence with its own cap; tranche A decision D3 |

### 5d. `hermes_overnight.json`

**Stage `night`** — proposed `20 2 * * *`, window 02:20-06:15

| # | cron L | today | step id | script | median s | p95 s | measured | timeout | flags |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 783 | 02:20 | `backlog_drain` | `llm_priority_guard.sh` | ≤94 | ≤371 | UPPER BOUND (PAM group) — NOT VERIFIED | 3300s |  |
| 2 | 1023 | 03:25 | `universe_history_retention` | `hermes_universe_history_retention.py` | ≤0.4 | ≤0.4 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 3 | 861 | 03:45 | `discovery_yield_builder` | `hermes_discovery_yield_builder.py` | ≤19 | ≤32 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 4 | 719 | 03:50 | `tag_lift_discovery` | `hermes_tag_lift_discovery.py` | ≤1.9 | ≤3.1 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 5 | 721 | 04:25 | `industry_novelty_discovery` | `hermes_industry_novelty_discovery.py` | ≤0.4 | ≤0.5 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 6 | 869 | 05:30 | `discovery_scorecard` | `hermes_discovery_scorecard.py` | ≤60 | ≤64 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |
| 7 | 872 | 06:15 | `siem_to_hermes_backlog` | `siem_to_hermes_backlog.py` | ≤36 | ≤54 | UPPER BOUND (PAM group) — NOT VERIFIED | 5m |  |

**Stage `close`** — proposed `13 23 * * *`, window 23:13-23:59

| # | cron L | today | step id | script | median s | p95 s | measured | timeout | flags |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 550 | 23:13 | `commit_hermes_daily` | `commit_hermes_daily.sh` | 0.0 | 0.1 | VERIFIED (pam_exact, n=7) | 5m |  |
| 2 | 392 | 23:30 | `source_curation` | `safe_flock.sh` | 274 | 282 | partial (safe_flock, 2/7) | 15m |  |

**Excluded** (4)

| cron L | today | script | category | reason |
|---|---|---|---|---|
| 717 | */2:0 | `hermes_discovery_ingestors.py` | HERMES_OTHER | hermes_discovery_ingestors 0 */2 — 2-hourly tick, not the nightly chain (rank 8) |
| 718 | */3:15 | `hermes_entity_spike_discovery.py` | HERMES_OTHER | hermes_entity_spike_discovery 15 */3 — 3-hourly (rank 8) |
| 720 | */3:20 | `hermes_analyst_signal_discovery.py` | HERMES_OTHER | hermes_analyst_signal_discovery 20 */3 — 3-hourly (rank 8) |
| 723 | *:5 | `hermes_research_worker_pool.py` | HERMES_OTHER | hermes_research_worker_pool hourly — self-gated lanes (rank 8) |

## 6. Install sequence (operator cron grant per step; nothing here is done by this PR)

1. **Instrument first** (no crontab change): the dev-tree wrappers flagged `DEV_TREE_WRAPPER` (`run_scheduled_atp2_research_cycle.sh`, `run_scheduled_stale_proposal_sweeper.sh`, `run_scheduled_strategy_audits.sh`) are repointed to CURRENT (study §6 — folding them unchanged keeps dev-tree code executing). The NOT VERIFIED steps get a receipt: wrapping their cron line in `safe_flock.sh` (16 lines already have it) is the cheapest instrument and is itself a cron edit → grant.
2. **Parallel-run week, one stage at a time, starting with `after_close --stage broker-truth`** (2 steps, both fit at p95): install the stage line in `--dry-run` (it writes its `PipelineRun@v1` summary and prints the plan; the old lines keep running). Declare the lane row `ACTIVE` with `scheduler.kind=cron` in the same PR (`check_lane_registry.py --fail-on-new` fails an undeclared line). Compare 5 days of `data/runtime/pipeline_after_close_broker-truth_last.json` against the old lines' receipts/logs.
3. **Cutover of that stage**: flip the line to `--apply` and comment out (not delete — §0 rail 6; the registry carries the RETIRED rows) the absorbed lines in the same crontab edit, with a `crontab -l` backup to `docs/implementation/n8n-parallel/proposals/crontab_before_tranche_b_<stage>.txt`. Remove the absorbed lines from the registry `undeclared_baseline` in the same PR.
4. Repeat 2–3 for `close-capture` (after its 8 unverified steps have receipts and the p95 sum fits 1680 s), then `planning`, then `premarket` (whose 05:45 start needs the deferred 06:10 pair measured), then the four Hermes stages (`learn` first: 4/6 steps VERIFIED).
5. After each cutover: `python3 scripts/check_lane_registry.py --fail-on-new --state-drift` must be clean on the host; the summary JSON mtime is the lane's freshness signal for `pipeline_freshness_monitor`.

## 7. Rollback

- A stage misbehaves during the parallel-run week: it is in `--dry-run`, so nothing to roll back — remove its line.
- After cutover: restore the commented absorbed lines from the same crontab edit (or the backup file), set the stage line back to `--dry-run` or remove it, flip the registry rows back (`state_since` + evidence). The step commands are verbatim, so an absorbed line restored to cron behaves exactly as before; the only state the runner adds is its own logs/receipts under `logs/pipelines/` and `data/runtime/pipeline_*_last.json`.
- A single bad step: continue-on-error already isolates it (`status=failed`/`timeout` in the summary); delete the step from the manifest and restore just that cron line.

## 8. Open items for the operator / parent

- `check_lane_registry.py --fail-on-new` on this host reports 3 undeclared cron lines (`auto_proposal_generator */30 9-16`, `watchlist_enrichment_sweep */30 9-16`, `plan_drift_revalidator 0 10,13`) with origin/main's registry and with this branch's registry alike; they are the tranche A rank-1 rewrites already in the live crontab and declared by `origin/wt/cron-tranche-a-20261007` (`3dc20d84b`), with which the gate is clean. This branch adds 0 violations (structural errors 0).
- Decide whether `llm_intelligence_enrichment` (07:20 / 16:20, no wrapper or cap today) belongs in a pipeline stage or in an LLM lane.
- The three `OPERATOR_SEND` and `HERMES_OWNED` exclusions are deferred to ranks 8–10, not dropped.
