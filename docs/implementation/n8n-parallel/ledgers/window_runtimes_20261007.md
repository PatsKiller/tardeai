# Window runtimes — fixed-minute cron lines in 05:30–08:00 and 16:00–18:40 (7 days to 2026-10-07)

Status: MEASURED 2026-10-07 (read-only; see the JSON twin `window_runtimes_20261007.json` for sources, bounds and notes).

Coverage: 248 lines — **45 VERIFIED on every firing**, 5 partially verified, 196 bounded only (lower bound from the log span and/or upper bound from the PAM session group — NOT VERIFIED), 2 never fired in the window. `V` = verified; `med/p95/max` are verified seconds; `upper med/p95` is the PAM-group upper bound; `lower` the log-span lower bound.

| L | window | schedule | script | fires | V | runs | med s | p95 s | max s | lower med | upper med | upper p95 | source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 429 | AM | `30 5 * * *` | `catalyst_calibration.py` | 7 |  | 0 |  |  |  |  | 60 | 64 | pam_group_max(upper) |
| 869 | AM | `30 5 * * *` | `hermes_discovery_scorecard.py` | 7 |  | 0 |  |  |  |  | 60 | 64 | pam_group_max(upper) |
| 458 | AM | `40 5 * * *` | `catalyst_calibration_monitor.py` | 7 |  | 0 |  |  |  |  | 24 | 65 | pam_group_max(upper) |
| 622 | AM | `40 5 * * *` | `register_analyst_sources.py` | 7 |  | 0 |  |  |  |  | 24 | 65 | pam_group_max(upper) |
| 631 | AM | `40 5 * * *` | `overnight_batch.py` | 7 | V | 7 | 0.1 | 0.1 | 0.1 |  |  |  | pipeline_runs |
| 266 | AM | `45 5 * * 1-5` | `indicator_cache_refresh.py` | 5 | V | 5 | 390 | 397 | 399 |  |  |  | log_end |
| 454 | AM | `45 5 * * *` | `source_outcome_attribution.py` | 7 |  | 0 |  |  |  |  | 20 | 22 | pam_group_max(upper) |
| 674 | AM | `45 5 * * 1-5` | `run_sec_form4_momentum_context.py` | 5 |  | 0 |  |  |  | 0.0 | 20 | 22 | log_span(lower)+pam_group_max(upper) |
| 916 | AM | `50 5 * * 1-5` | `mint_identity_registry.py` | 5 |  | 0 |  |  |  |  | 2.1 | 2.3 | pam_group_max(upper) |
| 165 | AM | `0 6 * * 1-5` | `telegram_smart_alerts.py` | 5 |  | 0 |  |  |  | 0.0 | 253 | 12482 | log_span(lower)+pam_group_max(upper) |
| 166 | AM | `0 6 1 * *` | `backup_verify.py` | 1 | V | 1 | 3.0 | 3.0 | 3.0 |  |  |  | log_end |
| 254 | AM | `0 6 * * 1-5` | `social_ingest.py` | 5 | V | 5 | 52 | 52 | 52 |  |  |  | pipeline_runs |
| 367 | AM | `0 6 * * 1-5` | `strategy_backtester.py` | 5 | V | 5 | 2.0 | 2.0 | 2.0 |  |  |  | safe_flock |
| 372 | AM | `0 6 * * 0` | `check_system_versions.sh` | 1 |  | 0 |  |  |  |  | 95 | 95 | pam_group_max(upper) |
| 456 | AM | `0 6 * * *` | `source_attribution_monitor.py` | 7 |  | 0 |  |  |  |  | 208 | 12481 | pam_group_max(upper) |
| 899 | AM | `0 6 * * 1-5` | `drain_discovery_backlog.py` | 5 |  | 0 |  |  |  |  | 253 | 12482 | pam_group_max(upper) |
| 1057 | AM | `0 6 * * 1-5` | `microstructure_recorder.py` | 2 |  | 0 |  |  |  |  | 12481 | 12482 | pam_group_max(upper) |
| 379 | AM | `10 6 * * 1-5` | `backtest_history_snapshot.py` | 5 |  | 3 | 1.0 | 1.0 | 1.0 | 0.0 | 438 | 445 | safe_flock |
| 460 | AM | `10 6 * * *` | `pro_analyst_fetch.py` | 7 |  | 0 |  |  |  |  | 427 | 442 | pam_group_max(upper) |
| 1017 | AM | `10 6 * * 1-5` | `build_catalyst_graph.py` | 5 |  | 0 |  |  |  |  | 430 | 443 | pam_group_max(upper) |
| 816 | AM | `12 6 * * 1-5` | `broker_stop_reconcile.py` | 5 |  | 0 |  |  |  |  | 2.5 | 2.6 | pam_group_max(upper) |
| 182 | AM | `15 6 * * 1-5` | `agent_router_cron.sh` | 5 |  | 0 |  |  |  |  | 36 | 56 | pam_group_max(upper) |
| 259 | AM | `15 6 * * *` | `fred_data_ingest.py` | 7 | V | 7 | 5.0 | 6.1 | 6.1 |  |  |  | pipeline_runs |
| 872 | AM | `15 6 * * *` | `siem_to_hermes_backlog.py` | 7 |  | 0 |  |  |  |  | 36 | 54 | pam_group_max(upper) |
| 898 | AM | `15 6 * * 1-5` | `candidate_discovery_orchestrator.py` | 5 |  | 0 |  |  |  |  | 36 | 56 | pam_group_max(upper) |
| 467 | AM | `20 6 * * *` | `watch_directives_monitor.py` | 7 |  | 0 |  |  |  |  | 9.9 | 117 | pam_group_max(upper) |
| 639 | AM | `20 6 * * 1-5` | `backtest_results_aggregator.py` | 5 |  | 1 | 1.0 | 1.0 | 1.0 | 0.0 | 8.9 | 10 | log_end |
| 860 | AM | `20 6 * * 1,4` | `hermes_cross_source_synthesizer.py` | 2 |  | 0 |  |  |  |  | 5.8 | 9.7 | pam_group_max(upper) |
| 196 | AM | `25 6 * * 1-5` | `agent_intelligence_cron.sh` | 5 |  | 0 |  |  |  |  | 9.5 | 11 | pam_group_max(upper) |
| 210 | AM | `30 6 * * 1-5` | `market_regime_collector.py` | 5 |  | 0 |  |  |  |  | 51 | 124 | pam_group_max(upper) |
| 536 | AM | `30 6 * * 6` | `classify_instruments.py` | 1 |  | 0 |  |  |  |  | 58 | 58 | pam_group_max(upper) |
| 215 | AM | `35 6 * * 1-5` | `classify_candidates.py` | 5 |  | 0 |  |  |  |  | 290 | 757 | pam_group_max(upper) |
| 216 | AM | `35 6 * * 1-5` | `market_regime_classifier.py` | 5 |  | 0 |  |  |  |  | 290 | 757 | pam_group_max(upper) |
| 357 | AM | `35 6 * * 1` | `overnight_batch.py` | 1 | V | 1 | 0.1 | 0.1 | 0.1 |  |  |  | pipeline_runs |
| 583 | AM | `35 6 * * 1-5` | `earnings_enrich.py` | 5 |  | 0 |  |  |  |  | 290 | 757 | pam_group_max(upper) |
| 776 | AM | `35 6 * * *` | `research_intelligence_materialize.py` | 7 |  | 0 |  |  |  |  | 231 | 749 | pam_group_max(upper) |
| 584 | AM | `38 6 * * 1-5` | `fund_technicals_enrich.py` | 5 |  | 0 |  |  |  |  | 3.1 | 3.1 | pam_group_max(upper) |
| 534 | AM | `40 6 * * 1-5` | `refresh_symbol_cards.py` | 5 |  | 0 |  |  |  |  | 58 | 86 | pam_group_max(upper) |
| 915 | AM | `40 6 * * *` | `build_lesson_candidates.py` | 7 |  | 0 |  |  |  |  | 58 | 85 | pam_group_max(upper) |
| 1050 | AM | `40 6 * * 1` | `maturity_remeasure.py` | 1 |  | 0 |  |  |  |  | 23 | 23 | pam_group_max(upper) |
| 585 | AM | `42 6 * * 1-5` | `distributions_enrich.py` | 5 |  | 0 |  |  |  |  | 3.1 | 7.6 | pam_group_max(upper) |
| 221 | AM | `45 6 * * 1-5` | `sync_watchlist_items_to_db.py` | 5 |  | 0 |  |  |  |  | 60 | 70 | pam_group_max(upper) |
| 427 | AM | `45 6,12,18 * * *` | `news_to_catalyst.py` | 7 |  | 0 |  |  |  |  | 60 | 69 | pam_group_max(upper) |
| 540 | AM | `45 6 * * 1-5` | `build_symbol_profiles.py` | 5 |  | 0 |  |  |  |  | 60 | 70 | pam_group_max(upper) |
| 754 | AM | `45 6 * * 1-5` | `volatility_tier_refresh.py` | 5 |  | 0 |  |  |  |  | 60 | 70 | pam_group_max(upper) |
| 836 | AM | `47 6 * * *` | `watch_valuation_backfill.py` | 7 | V | 7 | 360 | 381 | 384 |  |  |  | pam_exact |
| 441 | AM | `50 6,12,18 * * *` | `research_insight_extractor.py` | 7 |  | 0 |  |  |  |  | 104 | 113 | pam_group_max(upper) |
| 558 | AM | `50 6 * * *` | `crawl_v3_dashboard.py` | 7 |  | 0 |  |  |  |  | 104 | 113 | pam_group_max(upper) |
| 947 | AM | `52 6 * * *` | `cio_draft_plan_hygiene.py` | 7 |  | 0 |  |  |  |  | 10 | 14 | pam_group_max(upper) |
| 231 | AM | `55 6 * * 1-5` | `materialize_income_engine.py` | 5 |  | 0 |  |  |  |  | 1.0 | 3.1 | pam_group_max(upper) |
| 275 | AM | `0 7 * * *` | `agent_watchlist_engine.py` | 7 | V | 7 | 0.1 | 0.1 | 0.2 |  |  |  | pipeline_runs |
| 430 | AM | `0 7,13 * * 1-5` | `signal_fusion.py` | 5 |  | 0 |  |  |  |  | 66 | 79 | pam_group_max(upper) |
| 463 | AM | `0 7 * * *` | `llm_retry_monitor.py` | 7 |  | 0 |  |  |  |  | 66 | 138 | pam_group_max(upper) |
| 537 | AM | `0 7 * * 6` | `etf_analyst_enrich.py` | 1 |  | 0 |  |  |  |  | 163 | 163 | pam_group_max(upper) |
| 813 | AM | `0 7 * * *` | `iris_taxonomy_agent.py` | 7 |  | 0 |  |  |  |  | 66 | 138 | pam_group_max(upper) |
| 825 | AM | `0 7 * * 1-5` | `opening_intelligence.py` | 5 |  | 0 |  |  |  |  | 66 | 79 | pam_group_max(upper) |
| 895 | AM | `0 7 * * 1-5` | `research_watchlist_discovery.py` | 5 |  | 0 |  |  |  |  | 66 | 79 | pam_group_max(upper) |
| 227 | AM | `5 7 * * 1-5` | `sync_dividend_data.py` | 5 |  | 0 |  |  |  |  | 9.3 | 10 | pam_group_max(upper) |
| 1004 | AM | `5 7 * * *` | `llm_spend_report.py` | 7 |  | 0 |  |  |  |  | 7.6 | 10 | pam_group_max(upper) |
| 535 | AM | `10 7 * * *` | `recommendation_intelligence_engine.py` | 7 |  | 0 |  |  |  |  | 6.8 | 11 | pam_group_max(upper) |
| 1005 | AM | `10 7 * * 1` | `llm_spend_report.py` | 1 |  | 0 |  |  |  |  | 6.8 | 6.8 | pam_group_max(upper) |
| 183 | AM | `15 7 * * 1-5` | `external_market_data_ingest.py` | 5 |  | 0 |  |  |  |  | 1104 | 1411 | pam_group_max(upper) |
| 184 | AM | `15 7 * * 1-5` | `write_state_freshness_history.py` | 5 |  | 0 |  |  |  | 0.0 | 1104 | 1411 | log_span(lower)+pam_group_max(upper) |
| 189 | AM | `15 7 * * 1-5` | `portfolio_orchestrator.py` | 5 | V | 5 | 970 | 2289 | 2519 |  |  |  | safe_flock |
| 399 | AM | `15 7 * * 1-5` | `holdings_llm_refresh.py` | 5 | V | 5 | 356 | 422 | 432 |  |  |  | safe_flock |
| 552 | AM | `15 7 * * 6` | `etf_performance_enrich.py` | 1 |  | 0 |  |  |  |  | 317 | 317 | pam_group_max(upper) |
| 1006 | AM | `15 7 1 * *` | `llm_spend_report.py` | 1 |  | 0 |  |  |  |  | 1162 | 1162 | pam_group_max(upper) |
| 192 | AM | `20 7 * * 1-5` | `price_db_sync.py` | 5 |  | 0 |  |  |  |  | 78 | 117 | pam_group_max(upper) |
| 193 | AM | `20 7 * * 1-5` | `llm_intelligence_enrichment.py` | 5 | V | 5 | 78 | 117 | 117 |  |  |  | log_end |
| 409 | AM | `20 7 * * *` | `iris_proposal_curator.py` | 7 |  | 0 |  |  |  | 0.0 | 76 | 117 | log_span(lower)+pam_group_max(upper) |
| 514 | AM | `20 7 * * 1-6` | `snaptrade_activity_ingest.py` | 6 |  | 0 |  |  |  |  | 77 | 117 | pam_group_max(upper) |
| 1027 | AM | `20 7,19 * * 1-5` | `drain_cio_stance_classification.py` | 5 |  | 0 |  |  |  |  | 78 | 117 | pam_group_max(upper) |
| 581 | AM | `25 7 * * 1` | `fee_efficiency_analyzer.py` | 1 |  | 0 |  |  |  |  | 17 | 17 | pam_group_max(upper) |
| 175 | AM | `30 7 * * 1-5` | `send_morning_brief.py` | 5 |  | 0 |  |  |  | 0.0 | 121 | 221 | log_span(lower)+pam_group_max(upper) |
| 211 | AM | `30 7 * * 0` | `agent_router_cron.sh` | 1 |  | 0 |  |  |  |  | 54 | 54 | pam_group_max(upper) |
| 213 | AM | `30 7 * * 1-5` | `alert_missing_conditions.py` | 5 | V | 5 | 3.0 | 3.0 | 3.0 |  |  |  | log_end |
| 261 | AM | `30 7 * * 1-5` | `symbol_enrichment.py` | 5 | V | 5 | 51 | 117 | 123 |  |  |  | pipeline_runs |
| 443 | AM | `30 7 * * *` | `hermes_topic_monitor_bridge.py` | 7 |  | 0 |  |  |  |  | 100 | 220 | pam_group_max(upper) |
| 602 | AM | `30 7 * * 1-5` | `generate_analyst_daily_digest.py` | 5 |  | 0 |  |  |  |  | 121 | 221 | pam_group_max(upper) |
| 814 | AM | `30 7 * * *` | `iris_taxonomy_agent.py` | 7 |  | 0 |  |  |  |  | 100 | 220 | pam_group_max(upper) |
| 603 | AM | `35 7 * * 1-5` | `analyst_urgent_refresh.py` | 5 |  | 0 |  |  |  | 165 | 111 | 373 | log_span(lower)+pam_group_max(upper) |
| 219 | AM | `40 7 * * 1-5` | `portfolio_level_qa.py` | 5 |  | 0 |  |  |  |  | 66 | 76 | pam_group_max(upper) |
| 516 | AM | `40 7 * * 1-5` | `portfolio_lookthrough_themes.py` | 5 |  | 0 |  |  |  |  | 66 | 76 | pam_group_max(upper) |
| 582 | AM | `40 7 1 * *` | `validate_expense_ratios.py` | 1 |  | 0 |  |  |  |  | 66 | 66 | pam_group_max(upper) |
| 609 | AM | `45 7,15 * * *` | `hermes_pipeline_health.py` | 7 |  | 0 |  |  |  |  | 32 | 58 | pam_group_max(upper) |
| 858 | AM | `45 7 * * *` | `hermes_research_agenda.py` | 7 |  | 0 |  |  |  |  | 32 | 58 | pam_group_max(upper) |
| 229 | AM | `50 7 * * 1-5` | `record_decision_outcome.py` | 5 |  | 0 |  |  |  |  | 5.5 | 11 | pam_group_max(upper) |
| 233 | AM | `55 7 * * 1-5` | `classifier_health_check.py` | 5 |  | 0 |  |  |  |  | 3.4 | 9.0 | pam_group_max(upper) |
| 168 | AM | `0 8 * * 0` | `agent_intelligence_cron.sh` | 1 |  | 0 |  |  |  |  | 95 | 95 | pam_group_max(upper) |
| 169 | AM | `0 8 * * 0` | `data_gap_resolver.py` | 1 | V | 1 | 10 | 10 | 10 |  |  |  | log_end |
| 170 | AM | `0 8 * * 1` | `external_market_data_ingest.py` | 1 |  | 0 |  |  |  |  | 317 | 317 | pam_group_max(upper) |
| 172 | AM | `0 8 * * 1-5` | `iterate_research_topics.py` | 5 |  | 0 |  |  |  |  | 216 | 299 | pam_group_max(upper) |
| 173 | AM | `0 8 * * 1-5` | `send_alert_digest.py` | 5 |  | 0 |  |  |  | 0.0 | 216 | 299 | log_span(lower)+pam_group_max(upper) |
| 176 | AM | `0 8,20 * * 1-5` | `paper_performance_governance.py` | 5 |  | 0 |  |  |  | 0.0 | 216 | 299 | log_span(lower)+pam_group_max(upper) |
| 271 | AM | `0 8 * * 1-5` | `indicator_engine.py` | 5 | V | 5 | 1.0 | 1.2 | 1.3 |  |  |  | pipeline_runs |
| 482 | AM | `0 8,20 * * *` | `hermes_subject_enhance.py` | 7 |  | 0 |  |  |  |  | 205 | 290 | pam_group_max(upper) |
| 560 | AM | `0 8 * * 1-5` | `run_inference_cycle.sh` | 5 | V | 5 | 244 | 263 | 265 |  |  |  | log_end |
| 798 | AM | `0 8 * * 6` | `oversight_weekly_digest.py` | 1 |  | 0 |  |  |  |  | 68 | 68 | pam_group_max(upper) |
| 882 | AM | `0 8 * * 0` | `?` | 1 |  | 0 |  |  |  |  | 95 | 95 | pam_group_max(upper) |
| 900 | AM | `0 8 * * 1-5` | `desk_suggestions_digest.py` | 5 |  | 0 |  |  |  |  | 216 | 299 | pam_group_max(upper) |
| 743 | AM | `25 6-15 * * 1-5` | `hermes_momentum_catalyst_researcher.py` | 10 |  | 0 |  |  |  |  | 9.4 | 19 | pam_group_max(upper) |
| 257 | AM | `0,30 6-9 * * 1-5` | `social_scalp_scanner.py` | 25 |  | 20 | 28 | 86 | 98 | 205 | 253 | 12482 | log_end |
| 277 | BOTH | `0 */2 * * *` | `pipeline_watchdog.py` | 28 |  | 0 |  |  |  | 0.0 | 169 | 8448 | log_span(lower)+pam_group_max(upper) |
| 717 | BOTH | `0 */2 * * *` | `hermes_discovery_ingestors.py` | 28 |  | 0 |  |  |  | 0.0 | 169 | 8448 | log_span(lower)+pam_group_max(upper) |
| 476 | BOTH | `5 */2 * * *` | `hermes_top20_external_intel.py` | 21 |  | 0 |  |  |  |  | 192 | 808 | pam_group_max(upper) |
| 625 | BOTH | `15 */2 * * *` | `build_hermes_canonical_status.py` | 21 |  | 0 |  |  |  |  | 55 | 1079 | pam_group_max(upper) |
| 641 | BOTH | `15 */2 * * *` | `enrich_proposal_technicals.py` | 21 |  | 0 |  |  |  | 0.0 | 55 | 1079 | log_span(lower)+pam_group_max(upper) |
| 479 | BOTH | `20 */2 * * *` | `hermes_subject_enhance.py` | 21 |  | 0 |  |  |  |  | 22 | 380 | pam_group_max(upper) |
| 718 | BOTH | `15 */3 * * *` | `hermes_entity_spike_discovery.py` | 14 |  | 0 |  |  |  |  | 40 | 366 | pam_group_max(upper) |
| 720 | BOTH | `20 */3 * * *` | `hermes_analyst_signal_discovery.py` | 14 |  | 0 |  |  |  |  | 19 | 386 | pam_group_max(upper) |
| 263 | BOTH | `0 */4 * * *` | `rag_indexer.py` | 14 |  | 9 | 158 | 225 | 254 |  | 216 | 299 | pipeline_runs |
| 948 | BOTH | `0 */4 * * *` | `p1_digest_sender.py` | 14 | V | 14 | 4.0 | 7.7 | 11 |  |  |  | safe_flock |
| 936 | BOTH | `5 */6 * * *` | `refresh_operator_product.py` | 14 |  | 0 |  |  |  |  | 224 | 717 | pam_group_max(upper) |
| 637 | BOTH | `15 */6 * * *` | `paper_trade_advisory.py` | 14 |  | 0 |  |  |  |  | 40 | 366 | pam_group_max(upper) |
| 638 | BOTH | `30 */6 * * *` | `wire_advisory_lessons.py` | 14 |  | 0 |  |  |  |  | 140 | 393 | pam_group_max(upper) |
| 998 | BOTH | `0 * * * *` | `run_persistent_wake.py` | 42 |  | 0 |  |  |  | 0.0 | 96 | 1074 | log_span(lower)+pam_group_max(upper) |
| 1040 | BOTH | `3 * * * *` | `export_options_runtime_snapshot.py` | 35 |  | 0 |  |  |  |  | 0.2 | 14 | pam_group_max(upper) |
| 405 | BOTH | `5 * * * *` | `sync-docs-to-drive.sh` | 35 | V | 35 | 15 | 155 | 331 |  |  |  | safe_flock |
| 723 | BOTH | `5 * * * *` | `hermes_research_worker_pool.py` | 35 |  | 0 |  |  |  | 0.0 | 133 | 710 | log_span(lower)+pam_group_max(upper) |
| 1046 | BOTH | `5 * * * *` | `approval_package_reminder.py` | 2 |  | 0 |  |  |  | 0.0 | 338 | 635 | log_span(lower)+pam_group_max(upper) |
| 1048 | BOTH | `12 * * * *` | `approval_reminder_reconcile.py` | 2 |  | 0 |  |  |  | 0.0 | 32 | 59 | log_span(lower)+pam_group_max(upper) |
| 985 | BOTH | `15 * * * *` | `hermes_external_feedback_loop.py` | 35 |  | 0 |  |  |  | 0.0 | 88 | 1121 | log_span(lower)+pam_group_max(upper) |
| 473 | BOTH | `15,45 * * * *` | `hermes_score_alerts.py` | 70 |  | 0 |  |  |  |  | 58 | 1091 | pam_group_max(upper) |
| 764 | BOTH | `20 * * * *` | `topic_research_synthesizer.py` | 35 |  | 0 |  |  |  | 0.0 | 53 | 377 | log_span(lower)+pam_group_max(upper) |
| 914 | BOTH | `20 * * * *` | `resolve_due_checkpoints.py` | 20 |  | 0 |  |  |  | 0.0 | 95 | 381 | log_span(lower)+pam_group_max(upper) |
| 1019 | BOTH | `20 * * * *` | `report_goal_loop_baseline.py` | 35 |  | 0 |  |  |  | 0.0 | 53 | 377 | log_span(lower)+pam_group_max(upper) |
| 1024 | BOTH | `20 * * * *` | `check_llm_provider_health.py` | 35 |  | 0 |  |  |  |  | 53 | 377 | pam_group_max(upper) |
| 956 | BOTH | `25 * * * *` | `backfill_document_mentions.py` | 35 | V | 35 | 1500 | 1500 | 1500 |  |  |  | pam_timeout_kill |
| 551 | BOTH | `25,55 * * * *` | `directive_keyword_enhancer.py` | 70 |  | 0 |  |  |  |  | 0.9 | 164 | pam_group_max(upper) |
| 1042 | BOTH | `27 * * * *` | `symbol_news_curation_monitor.py` | 35 |  | 0 |  |  |  |  | 28 | 73 | pam_group_max(upper) |
| 1020 | BOTH | `35 * * * *` | `cio_gate_measurement_bridge.py` | 42 |  | 0 |  |  |  | 0.0 | 2.4 | 402 | log_span(lower)+pam_group_max(upper) |
| 1026 | BOTH | `35 * * * *` | `sync_code_mirror_to_drive.sh` | 42 | V | 42 | 26 | 137 | 170 |  |  |  | safe_flock |
| 1021 | BOTH | `40 * * * *` | `run_goal_pilot_material_change.py` | 42 |  | 0 |  |  |  | 0.0 | 46 | 1012 | log_span(lower)+pam_group_max(upper) |
| 1000 | BOTH | `45 * * * *` | `run_governed_research_producer.py` | 35 |  | 0 |  |  |  |  | 39 | 155 | pam_group_max(upper) |
| 1008 | BOTH | `50 * * * *` | `deepseek_balance_snapshot.py` | 35 |  | 0 |  |  |  | 0.0 | 5.0 | 116 | log_span(lower)+pam_group_max(upper) |
| 1022 | BOTH | `50 * * * *` | `run_dormant_lane_consumers.py` | 35 |  | 0 |  |  |  | 0.0 | 5.0 | 116 | log_span(lower)+pam_group_max(upper) |
| 997 | BOTH | `55 * * * *` | `wake_selection_feed.py` | 35 |  | 0 |  |  |  |  | 0.7 | 4.3 | pam_group_max(upper) |
| 1036 | BOTH | `7,22,37,52 * * * *` | `options_thesis_lifecycle.py` | 147 |  | 0 |  |  |  | 0.0 | 5.7 | 21 | log_span(lower)+pam_group_max(upper) |
| 687 | BOTH | `7,37 * * * *` | `hermes_scope_governor.py` | 77 | V | 77 | 8.0 | 12 | 16 |  |  |  | safe_flock |
| 1038 | BOTH | `9,24,39,54 * * * *` | `options_memory_projector.py` | 147 |  | 0 |  |  |  |  | 0.2 | 83 | pam_group_max(upper) |
| 434 | BOTH | `40 6,12,18 * * *` | `hermes_news_bridge.py` | 14 |  | 0 |  |  |  |  | 49 | 1612 | pam_group_max(upper) |
| 167 | BOTH | `0 7,8,9,10,11,12,13,14,15,16,17 * * 1-5` | `incubator_proposal_promoter.py` | 20 | V | 20 | 12 | 19 | 26 |  |  |  | safe_flock |
| 339 | BOTH | `0 7,9,12,16,20 * * 1-5` | `event_detector.py` | 10 |  | 0 |  |  |  | 2.0 | 155 | 697 | log_span(lower)+pam_group_max(upper) |
| 1011 | BOTH | `20 7,12,17 * * 1-5` | `catalyst_symbol_impact_writer.py` | 10 |  | 0 |  |  |  |  | 77 | 339 | pam_group_max(upper) |
| 92 | BOTH | `45 7,10,12,13,16 * * 1-5` | `run_scheduled_quote_refresh.sh` | 10 | V | 10 | 29 | 38 | 39 |  |  |  | pipeline_runs |
| 738 | BOTH | `25 6-18/3 * * 1-5` | `finviz_health_check.py` | 10 |  | 0 |  |  |  |  | 8.3 | 11 | pam_group_max(upper) |
| 491 | BOTH | `15 7-17/2 * * 1-5` | `pipeline_freshness_slo.py` | 10 |  | 0 |  |  |  |  | 1052 | 1333 | pam_group_max(upper) |
| 783 | HERMES | `20 2 * * *` | `hermes_backlog_drain.py` | 7 |  | 0 |  |  |  |  | 94 | 371 | pam_group_max(upper) |
| 1023 | HERMES | `25 3 * * *` | `hermes_universe_history_retention.py` | 7 |  | 0 |  |  |  |  | 0.4 | 0.4 | pam_group_max(upper) |
| 861 | HERMES | `45 3 * * *` | `hermes_discovery_yield_builder.py` | 7 |  | 0 |  |  |  |  | 19 | 32 | pam_group_max(upper) |
| 719 | HERMES | `50 3 * * *` | `hermes_tag_lift_discovery.py` | 7 |  | 0 |  |  |  |  | 1.9 | 3.1 | pam_group_max(upper) |
| 721 | HERMES | `25 4 * * *` | `hermes_industry_novelty_discovery.py` | 7 |  | 0 |  |  |  |  | 0.4 | 0.5 | pam_group_max(upper) |
| 692 | HERMES | `50 10 * * *` | `hermes_outcome_grader.py` | 7 | V | 7 | 6.0 | 7.0 | 7.0 |  |  |  | safe_flock |
| 702 | HERMES | `5 11 * * *` | `hermes_tag_engine.py` | 7 | V | 7 | 245 | 252 | 253 |  |  |  | safe_flock |
| 897 | HERMES | `15 11,15 * * 1-5` | `hermes_social_sentiment.py` | 10 |  | 0 |  |  |  |  | 129 | 214 | pam_group_max(upper) |
| 696 | HERMES | `25 11 * * *` | `hermes_outcome_feedback_agent.py` | 7 | V | 7 | 4.0 | 6.7 | 7.0 |  |  |  | safe_flock |
| 475 | HERMES | `35 11 * * *` | `hermes_outcome_learning.py` | 7 | V | 7 | 2.0 | 2.0 | 2.0 |  |  |  | safe_flock |
| 684 | HERMES | `40 11 * * *` | `hermes_score_history_retention.py` | 7 |  | 0 |  |  |  |  | 72 | 133 | pam_group_max(upper) |
| 705 | HERMES | `45 11 * * *` | `hermes_config_governor.py` | 7 |  | 0 |  |  |  |  | 138 | 167 | pam_group_max(upper) |
| 737 | HERMES | `40 13 * * 1-5` | `hermes_analyst_coverage.py` | 5 | V | 5 | 101 | 135 | 140 |  |  |  | safe_flock |
| 550 | HERMES | `13 23 * * *` | `commit_hermes_daily.sh` | 7 | V | 7 | 0.0 | 0.1 | 0.1 |  |  |  | pam_exact |
| 392 | HERMES | `30 23 * * *` | `hermes_source_curation.py` | 7 |  | 2 | 274 | 282 | 283 |  | 61 | 68 | safe_flock |
| 910 | PM | `15 */4 * * *` | `cio_lineage_completion_report.py` | 7 |  | 0 |  |  |  |  | 789 | 1080 | pam_group_max(upper) |
| 628 | PM | `20 */4 * * *` | `pipeline_freshness_monitor.py` | 7 |  | 0 |  |  |  |  | 89 | 367 | pam_group_max(upper) |
| 1049 | PM | `20 8,12,17,21 * * 1-5` | `sec_filings_feed.py` | 5 |  | 0 |  |  |  |  | 77 | 340 | pam_group_max(upper) |
| 291 | PM | `30 8,16 * * *` | `alert_dispatcher_unified.py` | 7 |  | 0 |  |  |  | 3.0 | 209 | 950 | log_span(lower)+pam_group_max(upper) |
| 1013 | PM | `40 8,12,16 * * 1-5` | `watch_goods_consistency_check.py` | 5 |  | 0 |  |  |  | 0.0 | 886 | 1131 | log_span(lower)+pam_group_max(upper) |
| 681 | PM | `0 10,14,18 * * 0,6` | `news_ingestion.py` | 2 | V | 2 | 321 | 322 | 322 |  |  |  | pipeline_runs |
| 1025 | PM | `10 10,13,16,19 * * *` | `drain_llm_deferred.py` | 7 |  | 0 |  |  |  |  | 2.7 | 3409 | pam_group_max(upper) |
| 556 | PM | `15 10,16 * * 1-5` | `finviz_sector_research.py` | 5 |  | 0 |  |  |  |  | 832 | 1080 | pam_group_max(upper) |
| 608 | PM | `20 10,16 * * 1-5` | `hermes_think_tank.py` | 5 |  | 0 |  |  |  |  | 89 | 370 | pam_group_max(upper) |
| 137 | PM | `0 10-16 * * 1-5` | `alpaca_paper_adapter.py` | 5 | V | 5 | 3.0 | 3.8 | 4.0 |  |  |  | safe_flock |
| 138 | PM | `0 10-16 * * 1-5` | `data_gap_resolver.py` | 5 |  | 0 |  |  |  | 16 | 293 | 844 | log_span(lower)+pam_group_max(upper) |
| 615 | PM | `0 10-16 * * 1-5` | `research_scheduler.py` | 5 |  | 0 |  |  |  |  | 293 | 844 | pam_group_max(upper) |
| 148 | PM | `0 16 * * 1-5` | `trade_ai_orchestrator.py` | 5 | V | 5 | 1260 | 1261 | 1261 |  |  |  | safe_flock |
| 149 | PM | `0 16 * * 1-5` | `send_alert_digest.py` | 5 |  | 0 |  |  |  | 0.0 | 293 | 844 | log_span(lower)+pam_group_max(upper) |
| 224 | PM | `5 16 * * 1-5` | `market_regime_collector.py` | 5 |  | 0 |  |  |  |  | 204 | 730 | pam_group_max(upper) |
| 225 | PM | `5 16 * * 1-5` | `run_scheduled_atp2_research_cycle.sh` | 5 | V | 5 | 0.6 | 0.9 | 0.9 |  |  |  | pipeline_runs |
| 243 | PM | `5 16 * * 1-5` | `eod_open_trade_alert.py` | 5 |  | 0 |  |  |  | 0.0 | 204 | 730 | log_span(lower)+pam_group_max(upper) |
| 733 | PM | `5 16 * * 1-5` | `run_options_monitor.sh` | 5 |  | 0 |  |  |  |  | 204 | 730 | pam_group_max(upper) |
| 864 | PM | `5 16 * * 1,3,5` | `run_watch_review_workers.py` | 3 |  | 0 |  |  |  | 0.0 | 204 | 395 | log_span(lower)+pam_group_max(upper) |
| 179 | PM | `10 16 * * 1-5` | `run_scheduled_stale_proposal_sweeper.sh` | 5 | V | 5 | 0.5 | 0.8 | 0.9 |  |  |  | pipeline_runs |
| 469 | PM | `10 16 * * 1-5` | `portfolio_repricer.py` | 5 | V | 5 | 25 | 56 | 62 |  |  |  | safe_flock |
| 1061 | PM | `10 16 * * 1-5` | `session_review.py` | 1 |  | 0 |  |  |  |  | 40 | 40 | pam_group_max(upper) |
| 1028 | PM | `15 16 * * *` | `notify_material_change.py` | 7 |  | 0 |  |  |  |  | 789 | 1080 | pam_group_max(upper) |
| 793 | PM | `18 16 * * 1-5` | `finviz_industry_groups.py` | 5 |  | 0 |  |  |  |  | 15 | 16 | pam_group_max(upper) |
| 194 | PM | `20 16 * * 1-5` | `llm_intelligence_enrichment.py` | 5 | V | 5 | 81 | 88 | 89 |  |  |  | log_end |
| 866 | PM | `20 16 * * 1,3,5` | `run_watch_review_workers.py` | 3 |  | 0 |  |  |  | 0.0 | 86 | 347 | log_span(lower)+pam_group_max(upper) |
| 549 | PM | `25 16 * * 1-5` | `strategy_tilt.py` | 5 |  | 0 |  |  |  |  | 0.7 | 1.6 | pam_group_max(upper) |
| 204 | PM | `30 16 * * 1-5` | `run_closed_trade_digest_cron.sh` | 5 | V | 5 | 4.2 | 5.6 | 6.0 |  |  |  | pipeline_runs |
| 341 | PM | `30 16 * * 1-5` | `paper_execution_quality_analyzer.py` | 5 |  | 0 |  |  |  | 1.0 | 213 | 1054 | log_span(lower)+pam_group_max(upper) |
| 502 | PM | `30 16 * * 1-5` | `technicals_gap_backfill.py` | 5 |  | 0 |  |  |  |  | 213 | 1054 | pam_group_max(upper) |
| 562 | PM | `30 16 * * 1-5` | `run_inference_cycle.sh` | 5 | V | 5 | 218 | 243 | 246 |  |  |  | log_end |
| 655 | PM | `30 16 * * 1-5` | `proposal_monitor.py` | 5 |  | 0 |  |  |  | 5.0 | 213 | 1054 | log_span(lower)+pam_group_max(upper) |
| 498 | PM | `33 16 * * 1-5` | `sync_basis_from_broker.py` | 5 |  | 0 |  |  |  |  | 8.2 | 17 | pam_group_max(upper) |
| 499 | PM | `35 16 * * 1-5` | `audit_position_basis.py` | 5 |  | 0 |  |  |  |  | 2.3 | 2.6 | pam_group_max(upper) |
| 481 | PM | `40 16 * * 1-5` | `hermes_subject_enhance.py` | 5 |  | 0 |  |  |  |  | 886 | 1131 | pam_group_max(upper) |
| 647 | PM | `40 16 * * 1-5` | `run_pullback_macd_screener.sh` | 5 |  | 0 |  |  |  |  | 886 | 1131 | pam_group_max(upper) |
| 348 | PM | `45 16 * * 1-5` | `atm_position_reconciler.py` | 5 |  | 0 |  |  |  |  | 76 | 223 | pam_group_max(upper) |
| 504 | PM | `45 16 * * 1-5` | `audit_enrichment_coverage.py` | 5 |  | 0 |  |  |  |  | 76 | 223 | pam_group_max(upper) |
| 771 | PM | `45 16 * * 1-5` | `research_intelligence_queue.py` | 5 |  | 0 |  |  |  |  | 76 | 223 | pam_group_max(upper) |
| 342 | PM | `0 17 * * 1-5` | `paper_execution_quality.py` | 5 |  | 0 |  |  |  | 0.0 | 123 | 909 | log_span(lower)+pam_group_max(upper) |
| 610 | PM | `0 17 * * *` | `hermes_autonomous_self_tune.py` | 7 |  | 0 |  |  |  |  | 123 | 824 | pam_group_max(upper) |
| 621 | PM | `0 17 * * 0` | `claude_challenger_curator.py` | 1 |  | 0 |  |  |  |  | 80 | 80 | pam_group_max(upper) |
| 500 | PM | `5 17 * * 1-5` | `holding_protection_advisor.py` | 5 |  | 0 |  |  |  |  | 196 | 322 | pam_group_max(upper) |
| 656 | PM | `5 17 * * 1-5` | `run_scheduled_strategy_audits.sh` | 5 |  | 0 |  |  |  |  | 196 | 322 | pam_group_max(upper) |
| 805 | PM | `5 17 * * 1-5` | `investment_costs.py` | 5 |  | 0 |  |  |  |  | 196 | 322 | pam_group_max(upper) |
| 735 | PM | `10 17 * * 1-5` | `run_options_paper_position_monitor.sh` | 5 |  | 0 |  |  |  |  | 1.9 | 2.4 | pam_group_max(upper) |
| 902 | PM | `17 17 * * 1-5` | `run_governed_symbol_thesis_acquisition.sh` | 5 | V | 5 | 81 | 258 | 300 |  |  |  | pam_exact |
| 503 | PM | `20 17 * * 1` | `holding_protection_advisor.py` | 1 |  | 0 |  |  |  |  | 340 | 340 | pam_group_max(upper) |
| 785 | PM | `20 17 * * 1-5` | `sector_rs_daily.py` | 5 |  | 0 |  |  |  |  | 77 | 340 | pam_group_max(upper) |
| 1070 | PM | `20 17 * * 1-5` | `positions_sync.py` | 1 |  | 0 |  |  |  |  | 338 | 338 | pam_group_max(upper) |
| 708 | PM | `25 17 * * 1-5` | `plan_drift_revalidator.py` | 5 |  | 0 |  |  |  |  | 184 | 343 | pam_group_max(upper) |
| 791 | PM | `25 17 * * 1-5` | `sector_momentum_engine.py` | 5 |  | 0 |  |  |  |  | 184 | 343 | pam_group_max(upper) |
| 1072 | PM | `25 17 * * 1-5` | `positions_proof_daily.py` | 1 |  | 0 |  |  |  |  | 344 | 344 | pam_group_max(upper) |
| 205 | PM | `30 17 * * 1-5` | `trade_ai_orchestrator.py` | 5 | V | 5 | 719 | 801 | 805 |  |  |  | safe_flock |
| 206 | PM | `30 17 * * 1-5` | `run_afterhours_candidate_preparation.sh` | 5 | V | 5 | 2.5 | 2.7 | 2.8 |  |  |  | pipeline_runs |
| 505 | PM | `35 17 * * 1-5` | `watchlist_entry_planner.py` | 5 |  | 0 |  |  |  |  | 52 | 93 | pam_group_max(upper) |
| 512 | PM | `35 17 * * 1-5` | `snaptrade_sync.py` | 5 |  | 0 |  |  |  | 0.0 | 52 | 93 | log_span(lower)+pam_group_max(upper) |
| 677 | PM | `35 17 * * 1-5` | `stop_drift_alert.py` | 5 |  | 0 |  |  |  | 0.0 | 52 | 93 | log_span(lower)+pam_group_max(upper) |
| 794 | PM | `35 17 * * 1-5` | `options_chain_snapshot.py` | 5 |  | 0 |  |  |  |  | 52 | 93 | pam_group_max(upper) |
| 774 | PM | `40 17 * * 1-5` | `holdings_gain_guardian.py` | 5 |  | 0 |  |  |  |  | 36 | 40 | pam_group_max(upper) |
| 506 | PM | `45 17 * * 1-5` | `watchlist_entry_planner.py` | 5 |  | 0 |  |  |  |  | 120 | 156 | pam_group_max(upper) |
| 795 | PM | `50 17 * * 1-5` | `defense_recommendations.py` | 5 |  | 0 |  |  |  |  | 100 | 126 | pam_group_max(upper) |
| 787 | PM | `55 17 * * 1-5` | `alert_daily_digest.py` | 5 |  | 0 |  |  |  |  | 1.9 | 2.2 | pam_group_max(upper) |
| 807 | PM | `55 17 * * 1-5` | `defense_inverse_stoplights.py` | 5 |  | 0 |  |  |  |  | 1.9 | 2.2 | pam_group_max(upper) |
| 151 | PM | `0 18 * * *` | `rescan_tickets.py` | 7 |  | 0 |  |  |  |  | 83 | 122 | pam_group_max(upper) |
| 153 | PM | `0 18 * * 1-5` | `data_gap_resolver.py` | 5 |  | 0 |  |  |  | 9.0 | 83 | 126 | log_span(lower)+pam_group_max(upper) |
| 397 | PM | `0 18,22 * * *` | `catalyst_momentum_engine.py` | 7 | V | 7 | 3.0 | 4.0 | 4.0 |  |  |  | safe_flock |
| 532 | PM | `0 18 * * 0` | `rotation_rebalance_digest.py` | 1 |  | 0 |  |  |  |  | 96 | 96 | pam_group_max(upper) |
| 878 | PM | `0 18 * * *` | `ops_daily_digest.py` | 7 |  | 0 |  |  |  |  | 83 | 122 | pam_group_max(upper) |
| 493 | PM | `10 18 * * 1-5` | `compute_source_weights.py` | 5 |  | 0 |  |  |  |  | 1.3 | 19 | pam_group_max(upper) |
| 484 | PM | `15 18 * * 1-5` | `schwab_transaction_ingest.py` | 5 |  | 0 |  |  |  |  | 89 | 716 | pam_group_max(upper) |
| 797 | PM | `15 18 * * 5` | `defense_weekly_paid_review.py` | 1 |  | 0 |  |  |  |  | 56 | 56 | pam_group_max(upper) |
| 859 | PM | `15 18 * * 1-5` | `hermes_research_agenda.py` | 5 |  | 0 |  |  |  |  | 89 | 716 | pam_group_max(upper) |
| 1032 | PM | `20 18 * * *` | `sweep_commitment_outcomes.py` | 7 |  | 0 |  |  |  |  | 20 | 391 | pam_group_max(upper) |
| 314 | PM | `30 18 * * *` | `topic_curator.py` | 7 |  | 0 |  |  |  |  | 360 | 402 | pam_group_max(upper) |
| 381 | PM | `30 18 * * 1-5` | `trade_backtest_engine.py` | 5 | V | 5 | 116 | 137 | 137 |  |  |  | safe_flock |
| 486 | PM | `30 18 * * 1-5` | `journal_review_builder.py` | 5 |  | 0 |  |  |  |  | 361 | 405 | pam_group_max(upper) |
| 806 | PM | `35 18 * * 1-5` | `schwab_econfirm_reconcile.py` | 5 |  | 0 |  |  |  |  | 2.2 | 2.6 | pam_group_max(upper) |
| 740 | PM | `40 18 * * 1-5` | `trade_thesis_review_engine.py` | 5 |  | 0 |  |  |  |  | 45 | 3561 | pam_group_max(upper) |
| 1052 | PM | `40 18 * * *` | `report_agent_number_grounding.py` | 6 |  | 0 |  |  |  |  | 42 | 3341 | pam_group_max(upper) |
| 601 | PM | `0,30 9-16 * * 1-5` | `run_broker_proposal_curator.sh` | 10 |  | 0 |  |  |  | 0.0 | 252 | 1127 | log_span(lower)+pam_group_max(upper) |
| 285 | PM | `0 9-16 * * 1-5` | `risk_gate.py` | 5 | V | 5 | 2.3 | 3.5 | 3.7 |  |  |  | pipeline_runs |
| 485 | PM | `3,18,33,48 9-16 * * 1-5` | `schwab_transaction_ingest.py` | 0 |  | 0 |  |  |  |  |  |  | no_firing |
| 531 | PM | `7,22,37,52 9-16 * * 1-5` | `schwab_position_sync.py` | 0 |  | 0 |  |  |  |  |  |  | no_firing |
| 1069 | PM | `9,24,39,54 9-16 * * 1-5` | `positions_sync.py` | 4 |  | 0 |  |  |  | 2.0 | 88 | 2162 | log_span(lower)+pam_group_max(upper) |
| 588 | PM | `0 9-18/3 * * 1-5` | `coder_dispatch.py` | 5 |  | 0 |  |  |  |  | 83 | 126 | pam_group_max(upper) |
