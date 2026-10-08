# Cron tranche B — cutover readiness and compressed plan (2026-10-08)

Status: PROPOSAL. Evidence as of 2026-10-08T01:49Z from `scripts/report_tranche_b_readiness.py --dry-run` against the served tree and the live crontab (nothing executed, nothing written). The eight stage lines run in `--dry-run` since 2026-10-07 22:40Z; every stage wrote its `PipelineRun@v1` summary from the manual fire at 2026-10-08 00:42Z.

Operator decision 2026-10-07: compress the cutovers (not five observation days per stage). This plan does that honestly: a stage cuts over when its absorbed lines are all present, every step has produced in the last 7 days, and the sum of medians fits the window; p95 overflow caused only by the design's PAM upper bounds is a NOTE, not a block, because the `_manifest_runner.sh` isolates a slow step (continue-on-error, per-step timeout) and the stage summary records it.

## Readiness table (live)

| stage | schedule | verdict | steps | Σ median s | Σ p95 s | window s | NOT VERIFIED (upper bounds) | notes |
|---|---|---|---|---|---|---|---|---|
| after_close/close-capture | `5 16 * * 1-5` | **GO_WITH_NOTES** | 13 | 1163 | 3730 | 1500 | 8/13 | sum p95 3730s > window 1500s (upper bounds on 8 unverified steps; medians 1163s fit) |
| after_close/broker-truth | `25 17 * * 1-5` | **GO_WITH_NOTES** | 2 | 198 | 325 | 600 | 2/2 | — |
| after_close/planning | `35 17 * * 1-5` | **GO_WITH_NOTES** | 14 | 1286 | 6480 | 3900 | 12/14 | sum p95 6480s > window 3900s (upper bounds on 12 unverified steps; medians 1287s fit) |
| premarket/premarket | `45 5 * * *` | **NO_GO** | 40 | 3433 | 6068 | 6000 | 32/40 | no receipt in 7 d: volatility_tier_refresh; sum p95 6068s > window 6000s (upper bounds on 32 unverified steps; medians 3433s fit) |
| hermes_learning/learn | `50 10 * * *` | **GO_WITH_NOTES** | 6 | 466 | 568 | 3600 | 2/6 | — |
| hermes_learning/tune | `0 17 * * *` | **GO_WITH_NOTES** | 1 | 123 | 824 | 900 | 1/1 | — |
| hermes_overnight/night | `20 2 * * *` | **NO_GO** | 7 | 212 | 526 | 14100 | 7/7 | cron line missing: universe_history_retention (absorbed elsewhere: universe_history_retention->platform-maintenance-nightly) |
| hermes_overnight/close | `13 23 * * *` | **GO_WITH_NOTES** | 2 | 61 | 68 | 2760 | 1/2 | — |

Verdict rules: **GO** = every absorbed line present, every step fresh in 7 d, Σ p95 ≤ window. **GO_WITH_NOTES** = same, but Σ p95 overflows only through unverified upper bounds while Σ median fits, or the design left steps NOT VERIFIED. **NO_GO** = a line is missing, a step has no receipt in 7 d or is unverifiable (no log, no lane), or Σ median does not fit — the step is named.

Steps the design left NOT VERIFIED (their p95 is the PAM upper bound, cited as `upper_bound:…` in the receipt):
- **after_close/close-capture**: regime_collector_pm, at_session_review, finviz_industry_groups, strategy_tilt, technicals_gap_backfill, paper_execution_quality_analyzer, audit_enrichment_coverage, research_intelligence_queue_drain
- **after_close/broker-truth**: audit_position_basis, investment_costs_ledger
- **after_close/planning**: strategy_audits, paper_execution_quality_events, sector_rs_daily, sector_momentum_engine, plan_drift_revalidator_pm, watchlist_entry_planner, watchlist_entry_planner_proposals, defense_recommendations, defense_inverse_stoplights, compute_source_weights, data_gap_resolver_pre_overnight, trade_thesis_review_engine
- **premarket/premarket**: catalyst_calibration, catalyst_calibration_monitor, register_analyst_sources, source_outcome_attribution, sec_form4_momentum_context, mint_identity_registry, backtest_history_snapshot, candidate_discovery_orchestrator, backtest_results_aggregator, watch_directives_monitor, market_regime_collector_am, classify_candidates, market_regime_classifier, earnings_enrich, research_intelligence_materialize, fund_technicals_enrich, refresh_symbol_cards, build_lesson_candidates, distributions_enrich, sync_watchlist_items_to_db, build_symbol_profiles, volatility_tier_refresh, cio_draft_plan_hygiene, materialize_income_engine, llm_retry_monitor, iris_taxonomy_agent, opening_intelligence, research_watchlist_discovery, sync_dividend_data, recommendation_intelligence_engine, price_db_sync, iris_proposal_curator
- **hermes_learning/learn**: score_history_retention, config_governor
- **hermes_learning/tune**: autonomous_self_tune
- **hermes_overnight/night**: backlog_drain, universe_history_retention, discovery_yield_builder, tag_lift_discovery, industry_novelty_discovery, discovery_scorecard, siem_to_hermes_backlog
- **hermes_overnight/close**: source_curation

## The two blockers

1. **hermes_overnight/night — `universe_history_retention`.** Its cron line was deleted on 2026-10-07 by cron tranche A rank 4: the job now runs as step 7 of `tradeai-platform-maintenance-nightly` (lane `hermes-universe-history-retention` is RETIRED, `superseded_by platform-maintenance-nightly`). The night manifest still lists it, so the cutover script refuses (1 absorbed line missing). Fix before cutover: remove the step from `config/pipelines/hermes_overnight.json` (a code PR; the runner would otherwise run the retention twice a night under the same `/tmp` lock). After that the stage is GO_WITH_NOTES (6 steps, Σ p95 526 s in a 14,100 s window).
2. **premarket/premarket — `volatility_tier_refresh`.** `logs/volatility_tier_refresh.log` is 0 bytes with mtime 2026-09-28: the step has written nothing for ten days (`--quiet`, errors to the same log). Either the job is silently healthy and mute, or it has not run; the readiness rule cannot tell, so premarket is NO_GO until the step gets a receipt (wrap the line in `safe_flock.sh` or drop `--quiet` — design §6 step 1). Everything else in premarket is fresh; Σ median 3,433 s fits the 6,000 s window, Σ p95 6,068 s is 68 s over only through 32 upper bounds.

## Compressed cutover order

Each cutover = one **cron grant** (crontab write) + one registry PR, merged before or with the cutover. Rollback per stage = `rollback_<pipeline>_<stage>.sh --apply` (restores the pre-cutover backup).

1. `hermes_overnight/close` — GO_WITH_NOTES
2. `hermes_learning/learn` — GO_WITH_NOTES
3. `after_close/broker-truth` — GO_WITH_NOTES
4. `hermes_learning/tune` — GO_WITH_NOTES
5. `after_close/planning` — GO_WITH_NOTES
6. `after_close/close-capture` — GO_WITH_NOTES
7. `hermes_overnight/night` — NO_GO; blocked by: cron line missing: universe_history_retention (absorbed elsewhere: universe_history_retention->platform-maintenance-nightly)
8. `premarket/premarket` — NO_GO; blocked by: no receipt in 7 d: volatility_tier_refresh; sum p95 6068s > window 6000s (upper bounds on 32 unverified steps; medians 3433s fit)

Proposed calendar (operator may compress further):
- **Thu 2026-10-09 (after 17:40 ET, when today's dry-run summaries for the three after-close stages exist):** `after_close/broker-truth` (2 steps, Σ p95 325 s / 600 s) and `hermes_learning/tune` (1 step). Both are the smallest blast radius.
- **Fri 2026-10-10:** `hermes_learning/learn` (6 steps, Σ p95 568 s / 3,600 s) and `hermes_overnight/close` (2 steps). Then `after_close/close-capture` and `after_close/planning` after their Thursday and Friday dry-run summaries show the 13 and 14 step plans intact (their medians fit; the p95 overflow is upper bounds — the first live run measures the true p95 and the summary carries per-step durations).
- **Sat 2026-10-11:** `hermes_overnight/night` once the manifest drops `universe_history_retention`; `premarket/premarket` once `volatility_tier_refresh` has a receipt (the Saturday 05:45 dry-run is the last check before the Sunday cutover).

## What each cutover script does (`scripts/pipelines/cutover/`)

`cutover_<pipeline>_<stage>.sh [--dry-run|--apply]` → `_cutover.py`: reads `crontab -l`; refuses unless the stage line exists exactly once in `--dry-run` and every absorbed line from the manifest (`cron_line_verbatim`) is present and uncommented; `--apply` backs the crontab up to `~/.local/state/tradeai/backups/crontab-<ts>-pre-cutover-<stage>.txt`, rewrites the stage line to `--apply`, and prefixes each absorbed line with `# RETIRED <date> tranche-b <stage> ` (never deletes — AGENTS.md §0 rail 6; `discover_commented_cron` records the retirement), then re-reads the crontab and checks the commented count equals the manifest step count. `rollback_<pipeline>_<stage>.sh --apply` restores the newest backup for that stage (after backing up the current table).

Dry-run against the served tree, 2026-10-08: close-capture 13/13 present, broker-truth 2/2, planning 14/14, premarket 40/40, learn 6/6, tune 1/1, close 2/2, night **6/7 → REFUSED** (blocker 1).

## Registry edit each cutover PR must carry (described, not applied here)

- The stage lane (`after-close-pipeline-<stage>`, `premarket-data-pipeline`, `hermes-learning-pipeline-<stage>`, `hermes-overnight-pipeline-<stage>`): `scheduler.expression` from `--dry-run` to `--apply`, `state_since` = cutover date, `state_reason` naming the backup file and the readiness verdict, `reason_evidence` = the first `--apply` summary (`data/runtime/pipeline_<pipeline>_<stage>_last.json`, `overall_status`, per-step rc).
- Every absorbed line that has a declared lane: `state` → RETIRED, `superseded_by` → the stage lane, `state_reason` "superseded by <stage lane> on <date>: cron line commented (`# RETIRED …`), the command runs verbatim as step <id> with its own lock, timeout and log".
- Every absorbed line that sits in `undeclared_baseline`: remove the string (the line is commented, no longer a live undeclared job). Lines in the pinned 2026-09-28 inherited tranche stay in that record (count pinned at 107 by `tests/test_lane_registry_inherited_tranche_20260928.py`) and are named in the stage lane's `state_reason`.
- After the crontab write: `python3 scripts/check_lane_registry.py --fail-on-new --state-drift` must be clean on the host; `pipeline_freshness_monitor` reads the stage summary mtime as the lane's freshness.

## Receipt

`scripts/report_tranche_b_readiness.py --write` writes `data/runtime/tranche_b_readiness_last.json` (`TrancheBReadiness@v1`, READ_ONLY_ADVISORY) under the state root; the proposed weekly governance packet can cite it. Tests: `tests/test_tranche_b_readiness_20261008.py` (fixture crontab through a fake `crontab` command — the real table is never touched).
