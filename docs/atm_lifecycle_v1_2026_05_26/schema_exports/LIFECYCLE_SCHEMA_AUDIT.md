# Lifecycle Schema Audit

**Generated:** 2026-05-26T19:56:49Z

## All Tables

```
                 tablename                 
-------------------------------------------
 account_placement_rules
 account_transfers
 account_value_anchors
 accounts
 action_queue
 action_signals_history
 advisor_observations
 advisor_recommendations
 aegis_covered_call_candidates
 aegis_discovery_index
 aegis_evidence_ledger
 aegis_feedback_log
 aegis_improvement_proposals
 aegis_outcome_tracking
 aegis_portfolio_briefs
 aegis_rotation_candidates
 aegis_steph_escalations
 aegis_steph_resolution_history
 aegis_symbol_snapshot_nightly
 afterhours_candidate_snapshot
 afterhours_readiness_run
 agent_calibration
 agent_calibration_events
 agent_calibration_run_log
 agent_calibration_windows
 agent_chain_runs
 agent_classification_suggestions
 agent_conflicts
 agent_context_refreshes
 agent_curation_events
 agent_data_source_rules
 agent_debate_log
 agent_decision_journal
 agent_disagreement_outcomes
 agent_discovery_log
 agent_event_queue
 agent_feedback_log
 agent_handoffs
 agent_intelligence_rules
 agent_learning_scores
 agent_performance_history
 agent_recommendation_outcome_links
 agent_recommendation_outcomes
 agent_recommendation_registry
 agent_sample_tracking
 agent_sec_rules
 agent_skills
 agent_weight_shadow_proposals
 ai_reports
 ai_watchlist_history
 alert_dispatch_log
 alert_effectiveness
 alert_event_links
 alert_events
 alex_hygiene_log
 analyst_consensus_history
 analyst_data_history
 approval_log
 article_index
 asset_intelligence_history
 atm_config_history
 atm_decision_log
 atm_state
 atm_state_events
 audit_log
 auto_proposal_decisions
 auto_proposal_runs
 backtest_datasets
 backtest_learning_evidence_links
 backtest_run_log
 blocked_content
 broker_reconciliation_items
 broker_reconciliation_runs
 candidate_discovery_events
 catalyst_events
 catalyst_historical_reactions
 catalyst_quality_results
 catalyst_sentiment_analysis
 catalyst_symbol_impact
 catalyst_type_weights
 challenger_definitions
 champion_challenger_results
 cio_decision_responses
 cio_decisions
 classifier_health_daily
 closed_trade_digest_log
 confidence_calibration_history
 config_change_proposals
 config_document_history
 config_documents
 content_embeddings
 content_embeddings_qwen3_shadow
 content_embeddings_qwen3_test
 content_entity_links
 cost_basis_anchors
 daily_snapshots
 daily_system_metrics
 data_gap_registry
 data_source_health
 decision_inputs
 decision_outcomes
 deep_overnight_llm_queue
 deep_overnight_llm_results
 digest_queue
 discovery_candidates_history
 dividend_history
 dof_auction_history
 dof_auction_runs
 dof_dmv_lookups
 dof_enrichment_queue
 dof_jobs
 dof_judgment_checks
 dof_manual_overrides
 dof_manual_queue
 dof_nicb_results
 dof_pdf_history
 dof_price_snapshots
 dof_ticket_events
 dof_ticket_lookups
 dof_vehicle_enrichment
 dof_vehicle_prices
 dof_vehicle_scores
 dof_vehicle_targets
 dof_vehicles
 dof_vin_appearances
 dof_vinaudit_results
 enrichment_log
 escalation_queue
 finviz_screeners
 fred_economic_series
 fundamental_data
 fused_signals
 gap_resolution_outcomes
 gemma3_calibration_events
 governance_approvals
 historical_trade_strategy_classifications
 holdings
 holdings_json_mirror
 human_feedback_examples
 income_asset_profiles
 income_projection_history
 incubator_events
 incubator_universe
 indicator_confluence_cache
 indicator_signal_history
 intel_briefs
 intelligence_entities
 intelligence_whiteboard
 iris_hygiene_log
 iris_hygiene_pending
 iris_library_gap_fills
 iris_run_log
 iris_taxonomy_proposals
 john_decision_history
 john_decision_queue
 journal_agent_coaching
 journal_trade_review_history
 journal_trade_reviews
 learning_digest_delivery_log
 learning_evidence
 learning_experiments
 learning_hypotheses
 learning_promotion_decisions
 learning_recommendations
 learning_rollback_events
 llm_feedback_observations
 llm_intelligence_cache
 llm_learning_recommendations
 llm_prompt_experiments
 local_llm_runs
 market_ohlcv_bars
 market_quote_snapshots
 market_quotes
 market_regime_indicators
 market_regime_snapshots
 marl_counterfactual_actions
 marl_policy_evaluations
 marl_policy_versions
 marl_simulation_runs
 marl_suggestions
 marl_training_datasets
 marl_training_episodes
 news_articles
 news_attention_spikes
 notification_log
 open_trade_alerts
 open_trade_due_diligence_events
 open_trade_intelligence_snapshots
 operator_review_queue
 overnight_actionable_outcomes
 paper_broker_reconciliation_items
 paper_broker_reconciliation_runs
 paper_dashboard_snapshots
 paper_execution_events
 paper_execution_quality
 paper_execution_quality_events
 paper_order_modification_proposals
 paper_performance_governance
 paper_proposal_analysis
 paper_proposal_approval_audit
 paper_proposal_approval_audit_events
 paper_proposal_stale_sweep_audit
 paper_strategy_scorecards
 paper_system_sync_log
 paper_trade_analysis
 paper_trade_commands
 paper_trade_execution_rechecks
 paper_trade_execution_windows
 paper_trade_lifecycle_outcomes
 paper_trade_multi_reviews
 paper_trade_outcome_analytics
 paper_trade_pre_execution_events
 paper_trade_proposals
 paper_trade_risk_actions
 paper_trades
 paper_validation_daily_metrics
 paper_validation_policy
 pattern_library
 performance_daily
 personal_history
 personal_situation
 personal_tax_history
 pipeline_definitions
 pipeline_events
 pipeline_runs
 pipeline_runs_legacy
 pipeline_schedule
 pipeline_stage_dependencies
 pipeline_stage_runs
 pipeline_stages
 portfolio_catalyst_summary
 portfolio_income_goals
 portfolio_intelligence_events
 portfolio_layers
 portfolio_level_qa_history
 portfolio_snapshots
 portfolio_target_allocations
 post_trade_price_analysis
 previously_traded_watchlist
 price_cache
 proposal_agent_reviews
 proposal_backtest_snapshots
 proposal_enrichment_events
 proposal_event_log
 proposal_evidence_snapshots
 proposal_execution_readiness
 proposal_lifecycle_events
 proposal_llm_review_queue
 proposal_outcome_chain
 proposal_quality_reviews
 proposal_research_packets
 proposal_technical_snapshots
 qualified_intelligence
 rebalance_analysis_results
 rebalance_plan_actions
 rebalance_plans
 recovery_outcome_log
 regime_learning_evidence_links
 regime_trade_alignment
 research_insights
 research_sources
 risk_gate_results
 risk_regime_run_log
 risk_synthesis_results
 run_summary
 scalp_decision_outcomes
 scalp_scan_results
 screener_config
 screener_run_health
 screener_symbol_membership
 screener_symbol_membership_history
 sec_13f
 sec_form4
 sec_xbrl
 self_improvement_component_health
 self_improvement_operator_notes
 self_improvement_snapshots
 sentiment_observations
 signal_clusters
 signal_flow_audit
 signal_history
 social_mentions
 social_posts
 social_sentiment_history
 social_volume_spikes
 source_learning_scores
 source_performance
 state_freshness_history
 stop_confirmations
 stop_decisions
 stop_snooze
 stopped_out_relist_events
 stopped_out_watch
 stopped_out_watch_history
 strategy_activations
 strategy_backtest_results
 strategy_backtest_runs
 strategy_backtest_trades
 strategy_cards
 strategy_config_versions
 strategy_group_caps
 strategy_learning_scores
 strategy_lesson_rollup
 strategy_parameter_versions
 strategy_performance_snapshots
 strategy_prompt_context_cache
 strategy_regime_profiles
 strategy_registry
 strategy_rotation_recommendations
 strategy_rotation_signals
 strategy_rule_evaluations
 strategy_rule_history
 strategy_rule_sets
 strategy_setup_matches
 strategy_signals
 strategy_state_transitions
 strategy_watchpool
 system_controls
 system_facts_history
 system_health_checks
 system_health_events
 tax_events
 telegram_proposal_messages
 thesis_learning_evidence_links
 ticker_classification_history
 ticker_dividend_data
 ticker_prices
 ticker_snapshot_daily
 ticker_strategy_classifications
 topic_curation_feedback
 topic_monitor
 trade_ai_scans
 trade_ai_state
 trade_backtest_results
 trade_closed
 trade_instructions
 trade_lesson_memory
 trade_plans
 trade_thesis_outcomes
 trade_thesis_reviews
 trade_transactions
 trailing_stop_analysis
 transcript_intel_history
 universe_strategy_fit_audit
 user_research_topics
 watchdog_actions
 watchlist_agent_jobs
 watchlist_agent_results
 watchlist_analysis_maturity
 watchlist_escalation_policies
 watchlist_events
 watchlist_final_synthesis
 watchlist_items
 watchlist_items_legacy
 watchlist_proposals
 watchlist_research_cards
 watchlist_research_events
 watchlist_research_queue
 watchlist_research_results
 watchlist_strategy_cards
 watchlist_synthesis_safety_history
 weekly_learning_digest_items
 weekly_learning_digests
 yahoo_analyst_targets_history
 youtube_backfill_queue
 youtube_backfill_status
 youtube_channel_candidates
 youtube_channels
 youtube_ingest_queue
 youtube_transcripts
(370 rows)

```

## Table: strategy_signals

```
                                             Table "public.strategy_signals"
         Column         |           Type           | Collation | Nullable |                   Default                    
------------------------+--------------------------+-----------+----------+----------------------------------------------
 id                     | integer                  |           | not null | nextval('strategy_signals_id_seq'::regclass)
 strategy_id            | text                     |           | not null | 
 symbol                 | text                     |           | not null | 
 signal_type            | text                     |           | not null | 'LONG'::text
 signal_grade           | text                     |           |          | 
 signal_score           | numeric                  |           |          | 
 price                  | numeric                  |           |          | 
 rvol                   | numeric                  |           |          | 
 float_m                | numeric                  |           |          | 
 gap_pct                | numeric                  |           |          | 
 catalyst               | text                     |           |          | 
 catalyst_verified      | boolean                  |           |          | false
 setup_description      | text                     |           |          | 
 entry_low              | numeric                  |           |          | 
 entry_high             | numeric                  |           |          | 
 stop_loss              | numeric                  |           |          | 
 target_1               | numeric                  |           |          | 
 target_2               | numeric                  |           |          | 
 risk_reward            | numeric                  |           |          | 
 shares                 | integer                  |           |          | 
 dollar_risk            | numeric                  |           |          | 
 vix_at_signal          | numeric                  |           |          | 
 market_regime          | text                     |           |          | 
 sector                 | text                     |           |          | 
 intel_readiness        | integer                  |           |          | 
 source_quality         | numeric                  |           |          | 
 status                 | text                     |           |          | 'active'::text
 fired_at               | timestamp with time zone |           |          | now()
 expires_at             | timestamp with time zone |           |          | 
 telegram_sent          | boolean                  |           |          | false
 trade_journal_id       | integer                  |           |          | 
 outcome_verdict        | text                     |           |          | 
 outcome_pnl            | numeric                  |           |          | 
 source_table           | text                     |           |          | 
 source_record_id       | text                     |           |          | 
 scan_run_label         | text                     |           |          | 
 screener_label         | text                     |           |          | 
```

### Sample rows

```
 id  |      strategy_id       | symbol | signal_type | signal_grade | signal_score | price | rvol  | float_m | gap_pct |                                         catalyst                                         | catalyst_verified |                                  setup_description                                   | entry_low | entry_high | stop_loss | target_1 | target_2 | risk_reward | shares | dollar_risk | vix_at_signal | market_regime |   sector   | intel_readiness | source_quality | status |           fired_at            |          expires_at           | telegram_sent | trade_journal_id | outcome_verdict | outcome_pnl |  source_table  | source_record_id | scan_run_label | screener_label | discovery_source |   sync_created_by    |          sync_run_id          |                                       route_match_reasons                                       | route_reject_reasons | route_score | setup_stack | primary_strategy_id | secondary_strategy_ids | strategy_config_hash 
-----+------------------------+--------+-------------+--------------+--------------+-------+-------+---------+---------+------------------------------------------------------------------------------------------+-------------------+--------------------------------------------------------------------------------------+-----------+------------+-----------+----------+----------+-------------+--------+-------------+---------------+---------------+------------+-----------------+----------------+--------+-------------------------------+-------------------------------+---------------+------------------+-----------------+-------------+----------------+------------------+----------------+----------------+------------------+----------------------+-------------------------------+-------------------------------------------------------------------------------------------------+----------------------+-------------+-------------+---------------------+------------------------+----------------------
 334 | fib_retracement_bounce | PONY   | GO          | A            |           42 |  9.41 | 12.15 |  284.61 |   15.58 | Pony AI Inc. (NASDAQ:PONY) Soars After Q1 2026 Earnings Beat and Raised Robotaxi Targets | t                 | RVOL 12.2x | Float 285M | Gap +15.6% | Verified catalyst | A 42pts | Source screener |      9.41 |       9.41 |      8.94 |    10.35 |          |         2.0 |    212 |       99.64 |               |               | Technology |              55 |                | active | 2026-05-26 10:37:13.183208-04 | 2026-05-26 18:37:13.183211-04 | f             |                  |                 |             | trade_ai_scans | 14097            | 0900           |                | screener         | strategy_signal_sync | sync_20260526_143711_181c84d5 | ["price 9.41 in [5.0-300.0]", "rvol 12.2 >= 0.8", "float 285M <= 1000.0M", "score 42 >= 30.0"]  | []                   |             |             |                     |                        | 
 333 | earnings_pre_buildup   | PONY   | GO          | A            |           42 |  9.41 | 12.15 |  284.61 |   15.58 | Pony AI Inc. (NASDAQ:PONY) Soars After Q1 2026 Earnings Beat and Raised Robotaxi Targets | t                 | RVOL 12.2x | Float 285M | Gap +15.6% | Verified catalyst | A 42pts | Source screener |      9.41 |       9.41 |      8.94 |    10.35 |          |         2.0 |    212 |       99.64 |               |               | Technology |              55 |                | active | 2026-05-26 10:37:13.021855-04 | 2026-05-26 18:37:13.021856-04 | f             |                  |                 |             | trade_ai_scans | 14097            | 0900           |                | screener         | strategy_signal_sync | sync_20260526_143711_181c84d5 | ["price 9.41 in [5.0-300.0]", "rvol 12.2 >= 1.2", "float 285M <= 99999.0M", "score 42 >= 30.0"] | []                   |             |             |                     |                        | 
 332 | swing_breakout         | PONY   | GO          | A            |           42 |  9.41 | 12.15 |  284.61 |   15.58 | Pony AI Inc. (NASDAQ:PONY) Soars After Q1 2026 Earnings Beat and Raised Robotaxi Targets | t                 | RVOL 12.2x | Float 285M | Gap +15.6% | Verified catalyst | A 42pts | Source screener |      9.41 |       9.41 |      8.94 |    10.35 |          |         2.0 |    212 |       99.64 |               |               | Technology |              55 |                | active | 2026-05-26 10:37:12.874124-04 | 2026-05-26 18:37:12.874125-04 | f             |                  |                 |             | trade_ai_scans | 14097            | 0900           |                | screener         | strategy_signal_sync | sync_20260526_143711_181c84d5 | ["price 9.41 in [5.0-150.0]", "rvol 12.2 >= 1.5", "float 285M <= 500.0M", "score 42 >= 35.0"]   | []                   |             |             |                     |                        | 
(3 rows)

```

## Table: paper_trade_proposals

```
                                                         Table "public.paper_trade_proposals"
              Column              |           Type           | Collation | Nullable |                             Default                              
----------------------------------+--------------------------+-----------+----------+------------------------------------------------------------------
 id                               | integer                  |           | not null | nextval('paper_trade_proposals_id_seq'::regclass)
 symbol                           | text                     |           | not null | 
 strategy_id                      | text                     |           | not null | 'momentum_scalp'::text
 setup_type                       | text                     |           |          | 
 signal_score                     | numeric                  |           |          | 
 signal_grade                     | text                     |           |          | 
 signal_decision                  | text                     |           |          | 
 source_signal_id                 | integer                  |           |          | 
 source_strategy_card_id          | integer                  |           |          | 
 trade_plan_id                    | integer                  |           |          | 
 rvol                             | numeric                  |           |          | 
 float_m                          | numeric                  |           |          | 
 gap_pct                          | numeric                  |           |          | 
 catalyst                         | text                     |           |          | 
 catalyst_verified                | boolean                  |           |          | false
 source_quality_score             | numeric                  |           |          | 
 data_quality_score               | integer                  |           |          | 
 intel_readiness                  | integer                  |           |          | 
 vix_at_proposal                  | numeric                  |           |          | 
 market_regime                    | text                     |           |          | 
 proposed_account                 | text                     |           |          | 
 proposed_entry                   | numeric                  |           | not null | 
 proposed_stop                    | numeric                  |           | not null | 
 proposed_target1                 | numeric                  |           | not null | 
 proposed_target2                 | numeric                  |           |          | 
 proposed_shares                  | integer                  |           | not null | 
 proposed_dollar_size             | numeric                  |           |          | 
 proposed_dollar_risk             | numeric                  |           |          | 
 proposed_stop_pct                | numeric                  |           |          | 
 proposed_rr                      | numeric                  |           |          | 
 tos_order_string                 | text                     |           |          | 
 final_account                    | text                     |           |          | 
 final_entry                      | numeric                  |           |          | 
 final_stop                       | numeric                  |           |          | 
 final_target1                    | numeric                  |           |          | 
 final_shares                     | integer                  |           |          | 
 final_dollar_risk                | numeric                  |           |          | 
```

### Sample rows

```
 id  | symbol |    strategy_id     |     setup_type     | signal_score | signal_grade | signal_decision | source_signal_id | source_strategy_card_id | trade_plan_id | rvol | float_m | gap_pct |                                 catalyst                                  | catalyst_verified | source_quality_score | data_quality_score | intel_readiness | vix_at_proposal | market_regime | proposed_account | proposed_entry | proposed_stop | proposed_target1 | proposed_target2 | proposed_shares | proposed_dollar_size | proposed_dollar_risk | proposed_stop_pct | proposed_rr | tos_order_string | final_account | final_entry | final_stop | final_target1 | final_shares | final_dollar_risk | risk_gate_result | risk_gate_codes |    proposed_by     |  status  | paper_trade_id | approved_at | rejected_at | rejection_reason |          expires_at           |          created_at           |          updated_at           | quality_pass | quality_reason_codes | hidden_by_quality_filter |    source_table    | source_record_id |     screener_name     | discovery_source | setup_description | catalyst_confidence | critic_verdict | critic_confidence | critic_reasoning |         sector         |            industry            | country | atr | atr_pct |  rsi  | vwap_distance | above_vwap | fib_context | normal_pattern_summary | missing_data | risk_pct_portfolio | target1_dollar_reward | target2_dollar_reward | research_packet_id | agent_review_status | local_llm_review_status | backtest_status | research_score | confidence_score | live_readiness_score |         approval_blocked_reason          | approval_allowed | required_reviews | completed_reviews | stock_history_summary |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      technical_context                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | backtest_summary | auto_created | auto_proposal_run_id | sizing_adjusted | original_shares | adjusted_shares | sizing_reason | auto_proposal_reason |        source_run_label         | auto_execution_label | institutional_packet_ready | latest_execution_readiness | latest_strategy_edge | latest_evidence_snapshot_id | alpaca_paper_submit_enabled |                live_submit_blocked_reason                | lifecycle_status |               lifecycle_message               |  entry_zone_status  | entry_zone_valid | current_price | price_drift_pct | last_price_source |     last_price_checked_at     | base_expires_at | max_expires_at | expiry_extended_count | last_lifecycle_check_at | overnight_monitoring_enabled | proposal_timeframe_class | manual_review_required | lifecycle_blockers | lifecycle_warnings | primary_strategy_id | secondary_strategy_ids | setup_stack | strategy_config_hash | strategy_prompt_context | packet_state | packet_completion_pct | llm_review_status |   packet_last_enriched_at    | packet_next_refresh_at | packet_blockers | packet_warnings |                                                                                                                                                                  missing_data_by_section                                                                                                                                                                   | action_state | action_label |         top_blocker          |                                       next_actions                                       |     llm_review_queued_at      | enrichment_attempt_count | last_enrichment_error | llm_model_used | llm_review_stage | llm_review_chunks | paper_submit_state | paper_submit_blockers | paper_submit_warnings | paper_submit_checked_at | paper_submitted_at | paper_client_order_id | paper_broker_order_id | paper_submit_payload | paper_submit_result | execution_recheck_required | approved_pending_recheck | execution_recheck_reason | last_recheck_id | execution_validated_at | execution_readiness_score | material_change_pending_approval | next_recheck_at | recommendation_created_at | last_plan_price | last_plan_updated_at | execution_status | execution_eligibility_status | execution_eligibility_reason | live_price_at_execution | live_price_timestamp | outcome_trade_id | outcome_r_multiple | outcome_pnl | outcome_pnl_pct | outcome_verdict | outcome_thesis_confirmed | outcome_closed_at | outcome_hold_hours |                expiry_reason                 | executed_at | executed_trade_id | is_top_pick | rank_among_peers | peer_group_id | alert_count | last_alert_at | last_alert_type | expired_reason | expired_at | override_payload | approved_by | target_account | atm_action | atm_action_set_by | atm_action_set_at | enrichment_failures | enrichment_status |  enrichment_last_attempt_at   | enrichment_last_error | atm_evaluation_count | atm_last_evaluation_at | atm_last_failure_reason | atm_expired_at | atm_expiry_reason 
-----+--------+--------------------+--------------------+--------------+--------------+-----------------+------------------+-------------------------+---------------+------+---------+---------+---------------------------------------------------------------------------+-------------------+----------------------+--------------------+-----------------+-----------------+---------------+------------------+----------------+---------------+------------------+------------------+-----------------+----------------------+----------------------+-------------------+-------------+------------------+---------------+-------------+------------+---------------+--------------+-------------------+------------------+-----------------+--------------------+----------+----------------+-------------+-------------+------------------+-------------------------------+-------------------------------+-------------------------------+--------------+----------------------+--------------------------+--------------------+------------------+-----------------------+------------------+-------------------+---------------------+----------------+-------------------+------------------+------------------------+--------------------------------+---------+-----+---------+-------+---------------+------------+-------------+------------------------+--------------+--------------------+-----------------------+-----------------------+--------------------+---------------------+-------------------------+-----------------+----------------+------------------+----------------------+------------------------------------------+------------------+------------------+-------------------+-----------------------+--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+--------------+----------------------+-----------------+-----------------+-----------------+---------------+----------------------+---------------------------------+----------------------+----------------------------+----------------------------+----------------------+-----------------------------+-----------------------------+----------------------------------------------------------+------------------+-----------------------------------------------+---------------------+------------------+---------------+-----------------+-------------------+-------------------------------+-----------------+----------------+-----------------------+-------------------------+------------------------------+--------------------------+------------------------+--------------------+--------------------+---------------------+------------------------+-------------+----------------------+-------------------------+--------------+-----------------------+-------------------+------------------------------+------------------------+-----------------+-----------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------+--------------+------------------------------+------------------------------------------------------------------------------------------+-------------------------------+--------------------------+-----------------------+----------------+------------------+-------------------+--------------------+-----------------------+-----------------------+-------------------------+--------------------+-----------------------+-----------------------+----------------------+---------------------+----------------------------+--------------------------+--------------------------+-----------------+------------------------+---------------------------+----------------------------------+-----------------+---------------------------+-----------------+----------------------+------------------+------------------------------+------------------------------+-------------------------+----------------------+------------------+--------------------+-------------+-----------------+-----------------+--------------------------+-------------------+--------------------+----------------------------------------------+-------------+-------------------+-------------+------------------+---------------+-------------+---------------+-----------------+----------------+------------+------------------+-------------+----------------+------------+-------------------+-------------------+---------------------+-------------------+-------------------------------+-----------------------+----------------------+------------------------+-------------------------+----------------+-------------------
 126 | EVER   | swing_trade        | Swing Trade        |         43.0 | A            |                 |                  |                         |               |      |         |         |                                                                           | f                 |                      |                    |                 |                 |               |                  |          19.97 |         18.97 |            21.97 |                  |             150 |                      |                      |                   |             |                  |               |             |            |               |              |                   | APPROVED         | []              | incubator_promoter | REJECTED |                |             |             |                  | 2026-05-31 10:40:54.303786-04 | 2026-05-26 10:40:54.458282-04 | 2026-05-26 10:45:25.058183-04 |              |                      | f                        | incubator_universe |                  | Incubator (7d active) | incubator        |                   |                     |                |                   |                  | Communication Services | Internet Content & Information |         |     |         | 71.62 |               |            |             |                        |              |                    |                       |                       |                    | QUEUED              |                         |                 |                |                  |                      | auto_rejected_stop_breached_before_entry |                  |                  |                   |                       | {"adx": 23.49, "atr": 1.3059, "rsi": 71.62, "rvol": 6.39, "vwap": 18.0, "ema_8": null, "ema_21": null, "ema_50": null, "symbol": "EVER", "volume": null, "atr_pct": 6.54, "ema_200": null, "float_m": 27.02, "gap_pct": 31.28, "atr_state": "volatile", "gap_state": "massive gap", "rsi_state": "overbought", "adx_regime": "moderate", "avg_volume": null, "normal_atr": null, "rvol_state": "high attention", "vwap_state": "extended above VWAP", "fib_context": {"summary": "Fib context unavailable — no daily bars or fib cache for EVER", "available": false}, "orb_context": {"summary": "ORB context unavailable — no intraday bars", "available": false, "opening_range_status": "NO_INTRADAY_DATA"}, "proposal_id": 126, "generated_at": "2026-05-26T14:45:03.665443+00:00", "current_price": 19.97, "ema_alignment": null, "proposed_entry": 19.97, "scan_timestamp": "2026-05-05 09:32:07.715957-04:00", "technical_vote": "neutral", "trend_strength": "weak trend", "ema_data_status": "INSUFFICIENT_BARS", "technical_grade": "TECH_WEAK", "technical_score": 20, "premarket_status": null, "vwap_distance_pct": 10.94, "ema_8_distance_pct": null, "price_vs_entry_pct": 0.0, "sma20_distance_pct": null, "sma50_distance_pct": null, "technical_concerns": ["RSI overbought", "Extended above VWAP — risk of mean reversion", "Massive gap — gap-fade risk"], "ema_21_distance_pct": null, "ema_50_distance_pct": null, "indicator_timestamp": "2026-05-06 17:33:47.361179-04:00", "ema_200_distance_pct": null, "float_rotation_ratio": null, "float_rotation_state": "Float rotation unavailable", "opening_range_status": "NO_INTRADAY_DATA", "normal_trading_pattern": "Pattern comparison unavailable — no historical pattern data for this symbol/setup yet", "overbought_oversold_summary": "RSI overbought; Extended above VWAP"} |                  | f            |                      | f               |                 |                 |               |                      | incubator_promote_20260526_1440 |                      | f                          | BLOCKED_PRICE_MOVED        |                      |                             | f                           | Live trading disabled pending six-month paper validation | ACTIVE           |                                               | ENTRY_ZONE_MARGINAL |                  |         18.82 |           -5.28 | finnhub           | 2026-05-26 10:45:25.058183-04 |                 |                |                     0 |                         | t                            | short_swing              | f                      |                    |                    | swing_trade         | []                     | []          |                      |                         | MISSING_DATA |                  45.0 | QUEUED            | 2026-05-26 10:45:03.54188-04 |                        |                 |                 | {"llm": ["llm_review_missing"], "agents": ["agent_reviews_missing"], "backtest": ["backtest_missing"], "catalyst": ["catalyst_missing", "catalyst_unverified", "recent_news_missing"], "critical": [], "strategy": ["setup_stack_missing"], "execution": ["execution_readiness_missing"], "technical": ["atr_missing", "vwap_missing"], "risk_reward": []} | BLOCKED      | 10 data gaps | Multiple sections incomplete | ["Run Technical Snapshot", "Check Execution Readiness", "Run Research", "Run AI Review"] | 2026-05-26 10:45:03.537563-04 |                        1 |                       |                |                  |                   | NOT_SUBMITTED      |                       |                       |                         |                    |                       |                       |                      |                     | t                          | f                        |                          |                 |                        |                           | f                                |                 |                           |                 |                      | not_submitted    |                              |                              |                         |                      |                  |                    |             |                 |                 |                          |                   |                    |                                              |             |                   | t           |                1 | EVER_126      |           0 |               |                 |                |            |                  |             | alpaca_paper   |            |                   |                   |                   0 | COMPLETE          | 2026-05-26 10:47:04.340577-04 |                       |                    0 |                        |                         |                | 
 125 | EVER   | speculative_growth | Speculative Growth |         43.0 | A            |                 |                  |                         |               |      |         |         | EverQuote Inc (NASDAQ:EVER) Surges on Q1 Earnings Beat and Upbeat Outlook | t                 |                      |                    |                 |                 |               |                  |          19.97 |         18.97 |            21.97 |                  |             150 |                      |                      |                   |             |                  |               |             |            |               |              |                   | APPROVED         | []              | incubator_promoter | EXPIRED  |                |             |             |                  | 2026-06-05 10:37:17.202389-04 | 2026-05-26 10:37:17.378482-04 | 2026-05-26 10:40:06.610309-04 |              |                      | f                        | incubator_universe |                  | Incubator (7d active) | incubator        |                   |                     |                |                   |                  |                        |                                |         |     |         | 71.62 |               |            |             |                        |              |                    |                       |                       |                    | NOT_REQUESTED       |                         |                 |                |                  |                      |                                          |                  |                  |                   |                       | {"adx": 23.49, "atr": 1.3059, "rsi": 71.62, "rvol": 6.39, "vwap": 18.0, "ema_8": null, "ema_21": null, "ema_50": null, "symbol": "EVER", "volume": null, "atr_pct": 6.54, "ema_200": null, "float_m": 27.02, "gap_pct": 31.28, "atr_state": "volatile", "gap_state": "massive gap", "rsi_state": "overbought", "adx_regime": "moderate", "avg_volume": null, "normal_atr": null, "rvol_state": "high attention", "vwap_state": "extended above VWAP", "fib_context": {"summary": "Fib context unavailable — no daily bars or fib cache for EVER", "available": false}, "orb_context": {"summary": "ORB context unavailable — no intraday bars", "available": false, "opening_range_status": "NO_INTRADAY_DATA"}, "proposal_id": 125, "generated_at": "2026-05-26T14:40:06.610208+00:00", "current_price": 19.97, "ema_alignment": null, "proposed_entry": 19.97, "scan_timestamp": "2026-05-05 09:32:07.715957-04:00", "technical_vote": "neutral", "trend_strength": "weak trend", "ema_data_status": "INSUFFICIENT_BARS", "technical_grade": "TECH_WEAK", "technical_score": 20, "premarket_status": null, "vwap_distance_pct": 10.94, "ema_8_distance_pct": null, "price_vs_entry_pct": 0.0, "sma20_distance_pct": null, "sma50_distance_pct": null, "technical_concerns": ["RSI overbought", "Extended above VWAP — risk of mean reversion", "Massive gap — gap-fade risk"], "ema_21_distance_pct": null, "ema_50_distance_pct": null, "indicator_timestamp": "2026-05-06 17:33:47.361179-04:00", "ema_200_distance_pct": null, "float_rotation_ratio": null, "float_rotation_state": "Float rotation unavailable", "opening_range_status": "NO_INTRADAY_DATA", "normal_trading_pattern": "Pattern comparison unavailable — no historical pattern data for this symbol/setup yet", "overbought_oversold_summary": "RSI overbought; Extended above VWAP"} |                  | f            |                      | f               |                 |                 |               |                      | incubator_promote_20260526_1437 |                      | f                          | BLOCKED_PRICE_MOVED        |                      |                             | f                           | Live trading disabled pending six-month paper validation | ACTIVE           |                                               | NEEDS_PRICE_CHECK   |                  |        18.915 |                 | alpaca            | 2026-05-26 10:40:06.227807-04 |                 |                |                     0 |                         | t                            | event_window             | f                      |                    |                    | speculative_growth  |                        |             |                      |                         | NEW          |                     0 | NOT_REQUESTED     |                              |                        |                 |                 |                                                                                                                                                                                                                                                                                                                                                            | BLOCKED      |              |                              |                                                                                          |                               |                        0 |                       |                |                  |                   | NOT_SUBMITTED      |                       |                       |                         |                    |                       |                       |                      |                     | t                          | f                        |                          |                 |                        |                           | f                                |                 |                           |                 |                      | not_submitted    |                              |                              |                         |                      |                  |                    |             |                 |                 |                          |                   |                    | AUTO: Stop breached — price at or below stop |             |                   | f           |                2 | EVER_126      |           0 |               |                 |                |            |                  |             | alpaca_paper   |            |                   |                   |                   0 | COMPLETE          | 2026-05-26 10:42:07.163362-04 |                       |                    0 |                        |                         |                | 
 124 | EVER   | gap_and_go         | Gap And Go         |         43.0 | A            |                 |                  |                         |               |      |         |         | EverQuote Inc (NASDAQ:EVER) Surges on Q1 Earnings Beat and Upbeat Outlook | t                 |                      |                    |                 |                 |               | TOS_PAPER        |          19.97 |         18.97 |            21.97 |                  |             150 |                      |                      |                   |             |                  |               |             |            |               |              |                   | APPROVED         | []              | incubator_promoter | expired  |                |             |             |                  | 2026-05-22 20:10:17.76376-04  | 2026-05-22 12:10:17.897013-04 | 2026-05-22 16:45:04.539533-04 |              |                      | f                        | incubator_universe |                  | Incubator (5d active) | incubator        |                   |                     |                |                   |                  |                        |                                |         |     |         | 71.62 |               |            |             |                        |              |                    |                       |                       |                    | NOT_REQUESTED       |                         |                 |                |                  |                      |                                          |                  |                  |                   |                       | {"adx": 23.49, "atr": 1.3059, "rsi": 71.62, "rvol": 6.39, "vwap": 18.0, "ema_8": null, "ema_21": null, "ema_50": null, "symbol": "EVER", "volume": null, "atr_pct": 6.54, "ema_200": null, "float_m": 27.02, "gap_pct": 31.28, "atr_state": "volatile", "gap_state": "massive gap", "rsi_state": "overbought", "adx_regime": "moderate", "avg_volume": null, "normal_atr": null, "rvol_state": "high attention", "vwap_state": "extended above VWAP", "fib_context": {"summary": "Fib context unavailable — no daily bars or fib cache for EVER", "available": false}, "orb_context": {"summary": "ORB context unavailable — no intraday bars", "available": false, "opening_range_status": "NO_INTRADAY_DATA"}, "proposal_id": 124, "generated_at": "2026-05-22T19:45:02.013694+00:00", "current_price": 19.97, "ema_alignment": null, "proposed_entry": 19.97, "scan_timestamp": "2026-05-05 09:32:07.715957-04:00", "technical_vote": "neutral", "trend_strength": "weak trend", "ema_data_status": "INSUFFICIENT_BARS", "technical_grade": "TECH_WEAK", "technical_score": 20, "premarket_status": null, "vwap_distance_pct": 10.94, "ema_8_distance_pct": null, "price_vs_entry_pct": 0.0, "sma20_distance_pct": null, "sma50_distance_pct": null, "technical_concerns": ["RSI overbought", "Extended above VWAP — risk of mean reversion", "Massive gap — gap-fade risk"], "ema_21_distance_pct": null, "ema_50_distance_pct": null, "indicator_timestamp": "2026-05-06 17:33:47.361179-04:00", "ema_200_distance_pct": null, "float_rotation_ratio": null, "float_rotation_state": "Float rotation unavailable", "opening_range_status": "NO_INTRADAY_DATA", "normal_trading_pattern": "Pattern comparison unavailable — no historical pattern data for this symbol/setup yet", "overbought_oversold_summary": "RSI overbought; Extended above VWAP"} |                  | f            |                      | f               |                 |                 |               |                      | incubator_promote_20260522_1610 |                      | f                          | BLOCKED_PRICE_MOVED        |                      |                             | f                           | Live trading disabled pending six-month paper validation | EXPIRED          | Intraday proposal: expired after market close | NEEDS_PRICE_CHECK   |                  |         18.87 |                 | alpaca            | 2026-05-22 16:45:04.539533-04 |                 |                |                     0 |                         | f                            | intraday                 | f                      |                    |                    | gap_and_go          |                        |             |                      |                         | NEW          |                     0 | NOT_REQUESTED     |                              |                        |                 |                 |                                                                                                                                                                                                                                                                                                                                                            | BLOCKED      |              |                              |                                                                                          |                               |                        0 |                       |                |                  |                   | NOT_SUBMITTED      |                       |                       |                         |                    |                       |                       |                      |                     | t                          | f                        |                          |                 |                        |                           | f                                |                 |                           |                 |                      | not_submitted    |                              |                              |                         |                      |                  |                    |             |                 |                 |                          |                   |                    |                                              |             |                   | t           |                1 | EVER_124      |           0 |               |                 |                |            |                  |             | alpaca_paper   |            |                   |                   |                   0 | COMPLETE          | 2026-05-22 15:45:46.348272-04 |                       |                    0 |                        |                         |                | 
(3 rows)

```

## Table: atm_decision_log

```
                                             Table "public.atm_decision_log"
         Column          |           Type           | Collation | Nullable |                   Default                    
-------------------------+--------------------------+-----------+----------+----------------------------------------------
 id                      | bigint                   |           | not null | nextval('atm_decision_log_id_seq'::regclass)
 decided_at              | timestamp with time zone |           | not null | now()
 proposal_id             | bigint                   |           | not null | 
 symbol                  | text                     |           | not null | 
 strategy_id             | text                     |           | not null | 
 target_account          | text                     |           | not null | 
 account_broker          | text                     |           | not null | 
 account_mode            | text                     |           | not null | 
 decision                | text                     |           | not null | 
 rejection_reasons       | jsonb                    |           |          | 
 classifier_health       | numeric(4,3)             |           |          | 
 positions_open_account  | integer                  |           |          | 
 positions_open_total    | integer                  |           |          | 
 new_today_account       | integer                  |           |          | 
 new_today_total         | integer                  |           |          | 
 daily_pnl_pct_account   | numeric(6,3)             |           |          | 
 daily_pnl_pct_aggregate | numeric(6,3)             |           |          | 
 b1_excluded             | boolean                  |           |          | false
 config_hash             | text                     |           | not null | 
 atm_mode                | text                     |           | not null | 
 trade_id                | bigint                   |           |          | 
Indexes:
    "atm_decision_log_pkey" PRIMARY KEY, btree (id)
    "idx_atm_decisions_account" btree (target_account, decided_at DESC)
    "idx_atm_decisions_proposal" btree (proposal_id)
    "idx_atm_decisions_recent" btree (decided_at DESC)
Check constraints:
    "atm_decision_log_decision_check" CHECK (decision = ANY (ARRAY['approved'::text, 'rejected'::text, 'deferred'::text, 'dry_run_approved'::text, 'dry_run_rejected'::text, 'force_approved'::text, 'force_rejected'::text, 'force_skipped'::text]))

```

### Sample rows

```
 id  |          decided_at           | proposal_id | symbol | strategy_id | target_account | account_broker | account_mode | decision |                       rejection_reasons                        | classifier_health | positions_open_account | positions_open_total | new_today_account | new_today_total | daily_pnl_pct_account | daily_pnl_pct_aggregate | b1_excluded | config_hash  | atm_mode | trade_id 
-----+-------------------------------+-------------+--------+-------------+----------------+----------------+--------------+----------+----------------------------------------------------------------+-------------------+------------------------+----------------------+-------------------+-----------------+-----------------------+-------------------------+-------------+--------------+----------+----------
 106 | 2026-05-26 10:45:01.999824-04 |         126 | EVER   | swing_trade | alpaca_paper   | alpaca         | paper        | deferred | [{"gate": "not_yet_enriched", "detail": "status=IN_PROGRESS"}] |             0.412 |                      4 |                    4 |                 0 |               0 |                 0.274 |                   0.274 | f           | ab8369972241 | active   |         
 105 | 2026-05-22 15:15:01.964058-04 |         124 | EVER   | gap_and_go  | alpaca_paper   | alpaca         | paper        | deferred | [{"gate": "not_yet_enriched", "detail": "status=IN_PROGRESS"}] |             0.000 |                      5 |                    5 |                 6 |               6 |                 0.000 |                   0.000 | f           | e0671b4e944f | active   |         
 104 | 2026-05-22 15:00:02.01363-04  |         124 | EVER   | gap_and_go  | alpaca_paper   | alpaca         | paper        | deferred | [{"gate": "not_yet_enriched", "detail": "status=IN_PROGRESS"}] |             0.000 |                      5 |                    5 |                 6 |               6 |                 0.000 |                   0.000 | f           | e0671b4e944f | active   |         
(3 rows)

```

## Table: paper_trades

```
                                                      Table "public.paper_trades"
             Column              |           Type           | Collation | Nullable |                      Default                       
---------------------------------+--------------------------+-----------+----------+----------------------------------------------------
 id                              | integer                  |           | not null | nextval('paper_trades_id_seq'::regclass)
 signal_id                       | integer                  |           |          | 
 strategy_id                     | text                     |           | not null | 
 symbol                          | text                     |           | not null | 
 account                         | text                     |           | not null | 
 entry_price                     | numeric                  |           |          | 
 entry_time                      | timestamp with time zone |           |          | 
 shares                          | integer                  |           |          | 
 dollar_size                     | numeric                  |           |          | 
 stop_loss                       | numeric                  |           |          | 
 target_1                        | numeric                  |           |          | 
 target_2                        | numeric                  |           |          | 
 dollar_risk                     | numeric                  |           |          | 150
 score_at_entry                  | integer                  |           |          | 
 rvol_at_entry                   | numeric                  |           |          | 
 float_m_at_entry                | numeric                  |           |          | 
 catalyst_at_entry               | text                     |           |          | 
 catalyst_verified               | boolean                  |           |          | 
 intel_readiness                 | integer                  |           |          | 
 vix_at_entry                    | numeric                  |           |          | 
 market_regime                   | text                     |           |          | 
 trade_plan_id                   | integer                  |           |          | 
 exit_price                      | numeric                  |           |          | 
 exit_time                       | timestamp with time zone |           |          | 
 exit_reason                     | text                     |           |          | 
 pnl                             | numeric                  |           |          | 
 pnl_pct                         | numeric                  |           |          | 
 hold_time_min                   | integer                  |           |          | 
 planned_entry                   | numeric                  |           |          | 
 entry_slippage                  | numeric                  |           |          | 
 planned_stop                    | numeric                  |           |          | 
 stop_slippage                   | numeric                  |           |          | 
 max_adverse_excursion           | numeric                  |           |          | 
 max_favorable_excursion         | numeric                  |           |          | 
 outcome_verdict                 | text                     |           |          | 
 status                          | text                     |           |          | 'open'::text
 logged_by                       | text                     |           |          | 'system'::text
```

### Sample rows

```
 id | signal_id |        strategy_id         | symbol |   account    | entry_price |          entry_time           | shares | dollar_size | stop_loss | target_1 | target_2 | dollar_risk | score_at_entry | rvol_at_entry | float_m_at_entry |                                 catalyst_at_entry                                  | catalyst_verified | intel_readiness | vix_at_entry |  market_regime  | trade_plan_id | exit_price | exit_time |               exit_reason               |  pnl  | pnl_pct | hold_time_min | planned_entry | entry_slippage | planned_stop | stop_slippage | max_adverse_excursion | max_favorable_excursion | outcome_verdict | status |   logged_by    |          created_at           |           closed_at           |          updated_at           |           broker_order_id            | broker_status | order_type | source_signal_id | source_strategy_card_id | risk_gate_result | risk_gate_reason_codes |    opened_via     |  closed_via  | current_price | unrealized_pnl | last_synced_at |                                                           notes                                                           | proposal_id |         setup_type         | signal_grade | automation_source | broker_submitted_at | broker_filled_at | broker_closed_at | source_quality_score | data_quality_score | r_multiple | planned_vs_actual_entry |         monitored_at          | last_alert_at | stale_flag | thesis_status | post_trade_analyzed | iris_curated | aegis_summarized | research_packet_id | decision_state | confidence_score | agent_votes | backtest_quality | approval_mode |    broker    | client_order_id | bracket_order | take_profit_price | stop_loss_price |         submitted_at          |           filled_at           | close_requested_at |                                             close_reason                                             | close_order_id | close_result | entered_after_recheck | entry_recheck_id | entry_readiness_score | recommendation_to_entry_seconds | approval_to_entry_seconds |                                                                                                     risk_params_at_fill                                                                                                      | lifecycle_state | revalidation_verdict | revalidation_score | revalidation_flags | price_at_approval | staleness_at_submit_min | broker_confirmed | target_account | atm_decision_id | atm_config_hash | atm_during_b1 |            stop_order_id             |        stop_updated_at        
----+-----------+----------------------------+--------+--------------+-------------+-------------------------------+--------+-------------+-----------+----------+----------+-------------+----------------+---------------+------------------+------------------------------------------------------------------------------------+-------------------+-----------------+--------------+-----------------+---------------+------------+-----------+-----------------------------------------+-------+---------+---------------+---------------+----------------+--------------+---------------+-----------------------+-------------------------+-----------------+--------+----------------+-------------------------------+-------------------------------+-------------------------------+--------------------------------------+---------------+------------+------------------+-------------------------+------------------+------------------------+-------------------+--------------+---------------+----------------+----------------+---------------------------------------------------------------------------------------------------------------------------+-------------+----------------------------+--------------+-------------------+---------------------+------------------+------------------+----------------------+--------------------+------------+-------------------------+-------------------------------+---------------+------------+---------------+---------------------+--------------+------------------+--------------------+----------------+------------------+-------------+------------------+---------------+--------------+-----------------+---------------+-------------------+-----------------+-------------------------------+-------------------------------+--------------------+------------------------------------------------------------------------------------------------------+----------------+--------------+-----------------------+------------------+-----------------------+---------------------------------+---------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-----------------+----------------------+--------------------+--------------------+-------------------+-------------------------+------------------+----------------+-----------------+-----------------+---------------+--------------------------------------+-------------------------------
 33 |           | dividend_growth_compounder | CMCSA  | ALPACA_PAPER |       24.97 |                               |    120 |      2996.4 |     23.61 |    27.34 |          |       163.2 |                |               |                  |                                                                                    |                   |                 |        17.38 | high_volatility |               |            |           |                                         | 20.75 |         |               |         24.85 |                |        23.61 |               |                 -0.52 |                     1.9 |                 | open   | alpaca_adapter | 2026-05-22 11:30:13.475741-04 |                               | 2026-05-26 15:54:07.90641-04  | b0b4ad46-e64a-46fe-a776-9ed174c76ac9 | filled        | market     |                  |                         | APPROVED         |                        | alpaca_adapter    |              |       25.1429 |          20.75 |                | Order type: market_better_price ($24.85 <= $24.85). Fill verified: filled. Shares: 120. Stop: $23.61 (placed after fill). |         123 |                            |              |                   |                     |                  |                  |                      |                    |       0.13 |                         | 2026-05-26 15:54:04.169548-04 |               | f          |               | f                   | f            | f                |                    |                |                  |             |                  |               | alpaca_paper |                 | f             |                   |                 | 2026-05-22 11:30:13.475741-04 | 2026-05-22 11:30:13.475741-04 |                    |                                                                                                      |                |              | f                     |                  |                       |                                 |                           | {"stop": 23.61, "target": 27.34, "drift_pct": 0.0, "order_type": "market", "proposed_entry": 24.85, "filled_avg_price": 24.97, "order_type_reason": "market_better_price ($24.85 <= $24.85)", "live_price_at_submit": 24.85} | open            | valid_original       |                 85 |                    |           24.8500 |                         | t                | alpaca_paper   |                 |                 | f             | e29b2971-1ff7-4024-8fd1-6c42fd89fe47 | 2026-05-22 16:55:00.002585-04
 32 |           | dividend_growth_compounder | CMCSA  | TOS_PAPER    |       24.85 | 2026-05-22 11:30:13.251622-04 |    120 |      2982.0 |     23.61 |    27.34 |          |       148.8 |             15 |               |                  | How The Story On Charter Communications (CHTR) Is Shifting After Price Target Cuts | f                 |                 |        17.38 | high_volatility |               |            |           | orphan_duplicate_from_partial_fill_race |       |         |               |         24.85 |                |        23.61 |               |                       |                         |                 | closed | dashboard      | 2026-05-22 11:30:13.251688-04 | 2026-05-22 15:43:50.565099-04 | 2026-05-22 11:30:13.251688-04 |                                      |               |            |                  |                         | APPROVED         | []                     | proposal_approved | manual_audit |               |                |                |                                                                                                                           |         123 | Dividend Growth Compounder | C            | proposal          |                     |                  |                  |                      |                    |            |                         |                               |               | f          |               | f                   | f            | f                |                    |                |                  |             |                  |               |              |                 | f             |                   |                 |                               |                               |                    | Orphan pending stub — real trade is the next row (filled). Closed during ATM remediation 2026-05-23. |                |              | f                     |                  |                       |                                 |                           |                                                                                                                                                                                                                              | closed          |                      |                    |                    |                   |                         | f                | alpaca_paper   |              64 | e0671b4e944f    | t             |                                      | 
 31 |           | reit_income                | AGNC   | ALPACA_PAPER |       10.22 |                               |    293 |     2994.46 |      9.71 |    11.24 |          |      149.43 |                |               |                  |                                                                                    |                   |                 |        17.38 | high_volatility |               |            |           |                                         | 60.06 |         |               |         10.22 |                |         9.71 |               |                  -0.1 |                    2.05 |                 | open   | alpaca_adapter | 2026-05-22 11:30:08.822688-04 |                               | 2026-05-26 15:54:07.810998-04 | 15440cb2-baf0-44a5-8c90-b85f955e6ce9 | filled        | market     |                  |                         | APPROVED         |                        | alpaca_adapter    |              |        10.425 |          60.06 |                | Order type: market_better_price ($10.22 <= $10.22). Fill verified: filled. Shares: 293. Stop: $9.71 (placed after fill).  |         120 |                            |              |                   |                     |                  |                  |                      |                    |        0.4 |                         | 2026-05-26 15:54:04.169548-04 |               | f          |               | f                   | f            | f                |                    |                |                  |             |                  |               | alpaca_paper |                 | f             |                   |                 | 2026-05-22 11:30:08.822688-04 | 2026-05-22 11:30:08.822688-04 |                    |                                                                                                      |                |              | f                     |                  |                       |                                 |                           | {"stop": 9.71, "target": 11.24, "drift_pct": 0.0, "order_type": "market", "proposed_entry": 10.22, "filled_avg_price": 10.22, "order_type_reason": "market_better_price ($10.22 <= $10.22)", "live_price_at_submit": 10.22}  | open            | valid_original       |                 85 |                    |           10.2200 |                         | t                | alpaca_paper   |                 |                 | f             | f171e7ec-9224-4358-939e-1661feb5b64e | 2026-05-22 16:54:59.991288-04
(3 rows)

```

## Table: paper_execution_quality

```
                                                 Table "public.paper_execution_quality"
             Column              |           Type           | Collation | Nullable |                       Default                       
---------------------------------+--------------------------+-----------+----------+-----------------------------------------------------
 id                              | integer                  |           | not null | nextval('paper_execution_quality_id_seq'::regclass)
 paper_trade_id                  | integer                  |           |          | 
 proposal_id                     | integer                  |           |          | 
 symbol                          | text                     |           | not null | 
 strategy_id                     | text                     |           |          | 
 order_id                        | text                     |           |          | 
 client_order_id                 | text                     |           |          | 
 intended_entry                  | numeric                  |           |          | 
 submitted_limit_price           | numeric                  |           |          | 
 fill_price                      | numeric                  |           |          | 
 arrival_price                   | numeric                  |           |          | 
 quote_bid                       | numeric                  |           |          | 
 quote_ask                       | numeric                  |           |          | 
 spread_pct                      | numeric                  |           |          | 
 slippage_pct                    | numeric                  |           |          | 
 slippage_dollars                | numeric                  |           |          | 
 fill_quality                    | text                     |           |          | 
 liquidity_context               | jsonb                    |           |          | 
 tca_payload                     | jsonb                    |           |          | 
 created_at                      | timestamp with time zone |           |          | now()
 order_submitted_at              | timestamp with time zone |           |          | 
 order_filled_at                 | timestamp with time zone |           |          | 
 time_to_fill_seconds            | numeric                  |           |          | 
 intended_shares                 | numeric                  |           |          | 
 filled_shares                   | numeric                  |           |          | 
 partial_fill                    | boolean                  |           |          | false
 price_improvement_pct           | numeric                  |           |          | 
 quote_age_seconds               | numeric                  |           |          | 
 market_session                  | text                     |           |          | 
 readiness_state_at_submit       | text                     |           |          | 
 lifecycle_state_at_submit       | text                     |           |          | 
 action_state_at_submit          | text                     |           |          | 
 packet_completion_pct_at_submit | numeric                  |           |          | 
 data_quality_grade              | text                     |           |          | 
Indexes:
    "paper_execution_quality_pkey" PRIMARY KEY, btree (id)
    "idx_peq_trade_created" btree (paper_trade_id, created_at DESC)
```

### Sample rows

```
 id | paper_trade_id | proposal_id | symbol |        strategy_id         |               order_id               | client_order_id | intended_entry | submitted_limit_price | fill_price | arrival_price | quote_bid | quote_ask | spread_pct | slippage_pct | slippage_dollars | fill_quality |                 liquidity_context                 |                                                        tca_payload                                                        |          created_at           | order_submitted_at | order_filled_at | time_to_fill_seconds | intended_shares | filled_shares | partial_fill | price_improvement_pct | quote_age_seconds | market_session | readiness_state_at_submit | lifecycle_state_at_submit | action_state_at_submit | packet_completion_pct_at_submit | data_quality_grade 
----+----------------+-------------+--------+----------------------------+--------------------------------------+-----------------+----------------+-----------------------+------------+---------------+-----------+-----------+------------+--------------+------------------+--------------+---------------------------------------------------+---------------------------------------------------------------------------------------------------------------------------+-------------------------------+--------------------+-----------------+----------------------+-----------------+---------------+--------------+-----------------------+-------------------+----------------+---------------------------+---------------------------+------------------------+---------------------------------+--------------------
 10 |             26 |         107 | ASPN   | swing_trade                |                                      |                 |           5.42 |                       |       5.42 |          5.36 |      5.35 |      5.37 |     0.3738 |          0.0 |              0.0 | EXCELLENT    | {"ask": 5.37, "bid": 5.35, "spread_pct": 0.3738}  | {"fill_price": 5.42, "fill_quality": "EXCELLENT", "slippage_pct": 0.0, "arrival_price": 5.36, "intended_entry": 5.42}     | 2026-05-26 09:43:01.955376-04 |                    |                 |                      |                 |               | f            |                       |                   |                |                           |                           |                        |                                 | 
  9 |             27 |         107 | ASPN   | swing_trade                | 8f88a449-4ce4-4355-81f5-6f331c4078aa |                 |           5.42 |                       |       5.52 |               |           |           |            |        1.845 |             55.3 | POOR         |                                                   | {"fill_price": 5.52, "fill_quality": "POOR", "slippage_pct": 1.845, "arrival_price": null, "intended_entry": 5.42}        | 2026-05-26 09:43:01.952067-04 |                    |                 |                      |                 |               | f            |                       |                   |                |                           |                           |                        |                                 | 
  8 |             28 |         117 | NWG    | dividend_growth_compounder | 45b57b20-f94                         |                 |          15.84 |                       |      15.84 |        15.795 |     15.79 |      15.8 |     0.0633 |          0.0 |              0.0 | EXCELLENT    | {"ask": 15.8, "bid": 15.79, "spread_pct": 0.0633} | {"fill_price": 15.84, "fill_quality": "EXCELLENT", "slippage_pct": 0.0, "arrival_price": 15.795, "intended_entry": 15.84} | 2026-05-26 09:43:01.9484-04   |                    |                 |                      |                 |               | f            |                       |                   |                |                           |                           |                        |                                 | 
(3 rows)

```

## Table: system_health_events

```
                                        Table "public.system_health_events"
    Column    |           Type           | Collation | Nullable |                     Default                      
--------------+--------------------------+-----------+----------+--------------------------------------------------
 id           | integer                  |           | not null | nextval('system_health_events_id_seq'::regclass)
 component    | text                     |           | not null | 
 event_type   | text                     |           | not null | 
 severity     | text                     |           | not null | 
 message      | text                     |           |          | 
 action_taken | text                     |           |          | 
 success      | boolean                  |           |          | 
 created_at   | timestamp with time zone |           |          | now()
Indexes:
    "system_health_events_pkey" PRIMARY KEY, btree (id)
    "idx_she_component" btree (component)
    "idx_she_created" btree (created_at DESC)

```

### Sample rows

```
 id  |       component        |     event_type     | severity |                   message                   | action_taken | success |          created_at           
-----+------------------------+--------------------+----------+---------------------------------------------+--------------+---------+-------------------------------
 484 | news_ingestion         | ESCALATION_DEDUPED | CRITICAL | Suppressed duplicate escalation (2h window) |              | t       | 2026-05-26 15:55:01.279091-04
 483 | finviz_screener_runner | ESCALATION_DEDUPED | CRITICAL | Suppressed duplicate escalation (2h window) |              | t       | 2026-05-26 15:55:01.273928-04
 482 | finviz_screener_runner | RETRY_EXHAUSTED    | CRITICAL | Max retries (2) exhausted today             |              | f       | 2026-05-26 15:55:01.271271-04
(3 rows)

```

## Table: system_health_checks

```
                                              Table "public.system_health_checks"
          Column           |           Type           | Collation | Nullable |                     Default                      
---------------------------+--------------------------+-----------+----------+--------------------------------------------------
 id                        | integer                  |           | not null | nextval('system_health_checks_id_seq'::regclass)
 check_type                | text                     |           | not null | 
 component                 | text                     |           | not null | 
 status                    | text                     |           | not null | 
 expected_schedule         | text                     |           |          | 
 last_success_at           | timestamp with time zone |           |          | 
 last_failure_at           | timestamp with time zone |           |          | 
 last_run_duration_sec     | double precision         |           |          | 
 expected_max_duration_sec | double precision         |           |          | 
 failure_count             | integer                  |           |          | 0
 retry_count               | integer                  |           |          | 0
 last_error                | text                     |           |          | 
 last_action               | text                     |           |          | 
 downstream_impact         | text                     |           |          | 
 severity                  | text                     |           |          | 'INFO'::text
 created_at                | timestamp with time zone |           |          | now()
 updated_at                | timestamp with time zone |           |          | now()
Indexes:
    "system_health_checks_pkey" PRIMARY KEY, btree (id)
    "idx_shc_component" btree (component)
    "idx_shc_status" btree (status)
    "idx_shc_updated" btree (updated_at DESC)

```

### Sample rows

```
  id  | check_type  |        component        | status  | expected_schedule |        last_success_at        |        last_failure_at        | last_run_duration_sec | expected_max_duration_sec | failure_count | retry_count | last_error | last_action |    downstream_impact     | severity |          created_at           |          updated_at           
------+-------------+-------------------------+---------+-------------------+-------------------------------+-------------------------------+-----------------------+---------------------------+---------------+-------------+------------+-------------+--------------------------+----------+-------------------------------+-------------------------------
 1212 | cron_health | proactive_quote_refresh | OK      | */5 9-15 * * 1-5  | 2026-05-26 15:55:01.249527-04 |                               |                       |                       120 |             0 |           0 |            |             | proposal price freshness | INFO     | 2026-05-26 15:55:01.312692-04 | 2026-05-26 15:55:01.312692-04
 1211 | cron_health | tca_analyzer            | MISSING | 30 16 * * 1-5     |                               | 2026-05-26 15:55:01.249527-04 |                       |                        60 |             1 |           0 |            |             | execution quality page   | INFO     | 2026-05-26 15:55:01.30999-04  | 2026-05-26 15:55:01.30999-04
 1210 | cron_health | pipeline_watchdog       | OK      | 0 */2 * * *       | 2026-05-26 15:55:01.249527-04 |                               |                       |                       300 |             0 |           0 |            |             | pipeline self-healing    | INFO     | 2026-05-26 15:55:01.307355-04 | 2026-05-26 15:55:01.307355-04
(3 rows)

```

## Table: accounts

```
                                             Table "public.accounts"
         Column         |           Type           | Collation | Nullable |               Default                
------------------------+--------------------------+-----------+----------+--------------------------------------
 id                     | bigint                   |           | not null | nextval('accounts_id_seq'::regclass)
 account_label          | text                     |           | not null | 
 broker                 | text                     |           | not null | 
 mode                   | text                     |           | not null | 
 auto_execution_capable | boolean                  |           | not null | false
 equity_source          | text                     |           | not null | 
 routing_adapter        | text                     |           |          | 
 enabled                | boolean                  |           | not null | false
 created_at             | timestamp with time zone |           | not null | now()
 notes                  | text                     |           |          | 
Indexes:
    "accounts_pkey" PRIMARY KEY, btree (id)
    "accounts_account_label_key" UNIQUE CONSTRAINT, btree (account_label)
Check constraints:
    "accounts_mode_check" CHECK (mode = ANY (ARRAY['paper'::text, 'live'::text]))

```

### Sample rows

```
 id |  account_label  |  broker  | mode | auto_execution_capable | equity_source | routing_adapter | enabled |          created_at           |                      notes                      
----+-----------------+----------+------+------------------------+---------------+-----------------+---------+-------------------------------+-------------------------------------------------
  5 | fidelity_401k   | fidelity | live | f                      | holdings_json |                 | f       | 2026-05-21 21:23:45.586775-04 | No routing adapter yet — manual execution only.
  4 | schwab_taxable  | schwab   | live | f                      | holdings_json |                 | f       | 2026-05-21 21:23:45.586775-04 | No routing adapter yet — manual execution only.
  3 | schwab_roth_ira | schwab   | live | f                      | holdings_json |                 | f       | 2026-05-21 21:23:45.586775-04 | No routing adapter yet — manual execution only.
(3 rows)

```

## Table: pipeline_schedule

```
                                 Table "public.pipeline_schedule"
     Column      |  Type   | Collation | Nullable |                    Default                    
-----------------+---------+-----------+----------+-----------------------------------------------
 id              | integer |           | not null | nextval('pipeline_schedule_id_seq'::regclass)
 script_name     | text    |           | not null | 
 display_name    | text    |           |          | 
 expected_hour   | integer |           |          | 
 expected_min    | integer |           |          | 
 max_latency_min | integer |           |          | 15
 min_rows        | integer |           |          | 0
 critical        | boolean |           |          | false
 active          | boolean |           |          | true
 command         | text    |           |          | 
 run_days        | text    |           |          | '1-5'::text
Indexes:
    "pipeline_schedule_pkey" PRIMARY KEY, btree (id)
    "pipeline_schedule_script_name_key" UNIQUE CONSTRAINT, btree (script_name)

```

### Sample rows

```
 id |         script_name         |           display_name           | expected_hour | expected_min | max_latency_min | min_rows | critical | active |                                                    command                                                     | run_days 
----+-----------------------------+----------------------------------+---------------+--------------+-----------------+----------+----------+--------+----------------------------------------------------------------------------------------------------------------+----------
 13 | incubator_llm_screener      | Incubator LLM Screener           |             8 |           10 |              20 |        0 | t        | t      | cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && python3 scripts/incubator_llm_screener.py --run | 1-5
 12 | incubator_proposal_promoter | Incubator Proposal Promoter      |             8 |           20 |              15 |        0 | t        | t      | python3 scripts/incubator_proposal_promoter.py --run                                                           | 1-5
 11 | pattern_extractor           | Pattern Extractor (Monthly 9 AM) |             9 |            0 |              60 |        0 | f        | t      | cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/pattern_extractor.py   | 1-5
(3 rows)

```

## Table: trade_lesson_memory

```
                                             Table "public.trade_lesson_memory"
         Column         |           Type           | Collation | Nullable |                     Default                     
------------------------+--------------------------+-----------+----------+-------------------------------------------------
 id                     | integer                  |           | not null | nextval('trade_lesson_memory_id_seq'::regclass)
 trade_id               | integer                  |           |          | 
 symbol                 | character varying(10)    |           |          | 
 strategy_id            | character varying(64)    |           |          | 
 close_date             | date                     |           |          | 
 exit_reason            | character varying(64)    |           |          | 
 dashboard_verdict      | character varying(30)    |           |          | 
 exit_quality           | character varying(20)    |           |          | 
 mistake_type           | character varying(30)    |           |          | 
 lesson_category        | character varying(30)    |           |          | 
 improved_lesson        | text                     |           |          | 
 rule_feedback          | text                     |           |          | 
 next_operator_action   | text                     |           |          | 
 action_priority        | character varying(10)    |           |          | 
 action_owner           | character varying(20)    |           |          | 
 confidence_delta       | character varying(20)    |           |          | 
 repeated_pattern_key   | character varying(128)   |           |          | 
 pattern_count          | integer                  |           |          | 1
 pnl                    | numeric(10,2)            |           |          | 
 r_multiple             | numeric(6,2)             |           |          | 
 human_review_only      | boolean                  |           |          | true
 operator_review_status | character varying(30)    |           |          | 'pending'::character varying
 source_payload_hash    | character varying(64)    |           |          | 
 created_at             | timestamp with time zone |           |          | now()
Indexes:
    "trade_lesson_memory_pkey" PRIMARY KEY, btree (id)
    "idx_tlm_lesson_category" btree (lesson_category)
    "idx_tlm_repeated_pattern_key" btree (repeated_pattern_key)
    "idx_tlm_strategy_id" btree (strategy_id)
    "idx_tlm_symbol" btree (symbol)
    "trade_lesson_memory_trade_id_lesson_category_source_payload_key" UNIQUE CONSTRAINT, btree (trade_id, lesson_category, source_payload_hash)

```

### Sample rows

```
 id | trade_id | symbol |        strategy_id         | close_date |       exit_reason       | dashboard_verdict |  exit_quality   |  mistake_type   | lesson_category |                                                                           improved_lesson                                                                           |                                                    rule_feedback                                                     |                                          next_operator_action                                           | action_priority |  action_owner   | confidence_delta |              repeated_pattern_key              | pattern_count |  pnl   | r_multiple | human_review_only | operator_review_status |       source_payload_hash        |          created_at           
----+----------+--------+----------------------------+------------+-------------------------+-------------------+-----------------+-----------------+-----------------+---------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------------------------------------------------------------------------+---------------------------------------------------------------------------------------------------------+-----------------+-----------------+------------------+------------------------------------------------+---------------+--------+------------+-------------------+------------------------+----------------------------------+-------------------------------
 11 |       24 | FLYW   | dividend_growth_compounder | 2026-05-14 | stop_hit                | RULE_BASED_LOSS   | ACCEPTABLE_EXIT | none            | stop_quality    | FLYW (dividend_growth_compounder): Stop hit at 0.2R — within acceptable R risk. Entry quality was adequate, stop placement held correctly                           | Stop distance acceptable for dividend_growth_compounder; no change needed                                            | No action — loss within acceptable risk parameters                                                      | none            | operator        | neutral          | dividend_growth_compounder_none_stop_quality   |             1 |  29.07 |       0.21 | t                 | pending                | 8cf4e9d4ceed0b2165172839ccf425cd | 2026-05-19 19:55:51.326986-04
 10 |       16 | BLBD   | earnings_catalyst          | 2026-05-12 | stop_hit_instant        | BAD_ENTRY         | NEEDS_REVIEW    | spread_slippage | entry_timing    | BLBD (earnings_catalyst): Stopped out instantly at -0.05R — entry price was likely too aggressive, spread was too wide, or stop was placed inside the bid-ask range | Review earnings_catalyst entry criteria: require tighter spread limits or wider initial stop to survive first candle | Check BLBD spread at entry time, verify stop was outside bid-ask, review earnings_catalyst entry filter | high            | strategy_review | neutral          | earnings_catalyst_spread_slippage_entry_timing |             1 | -14.80 |      -0.05 | t                 | pending                | 4a4d5b1969f140d8c741e693ac3e56ab | 2026-05-19 19:55:51.326986-04
  9 |       22 | GCTS   | momentum_scalp             | 2026-05-13 | time_stop_intraday_1545 | EARLY_EXIT        | EARLY_EXIT      | time_stop_drag  | holding_period  | GCTS (momentum_scalp): Time stop triggered — setup did not move within the allowed window. Small loss incurred, time stop prevented further drawdown                | Time stop cut a losing position early — review whether the setup needed a longer window or the entry was weak        | Review whether momentum_scalp holding window is too short for this setup type                           | low             | operator        | neutral          | momentum_scalp_time_stop_drag_holding_period   |             2 | -12.38 |      -0.14 | t                 | pending                | 70d2acfd81e0140389bc27f5183c1dca | 2026-05-19 19:55:51.326986-04
(3 rows)

```

## Table: strategy_lesson_rollup

```
                                              Table "public.strategy_lesson_rollup"
          Column          |           Type           | Collation | Nullable |                      Default                       
--------------------------+--------------------------+-----------+----------+----------------------------------------------------
 id                       | integer                  |           | not null | nextval('strategy_lesson_rollup_id_seq'::regclass)
 strategy_id              | character varying(64)    |           | not null | 
 period_start             | date                     |           |          | 
 period_end               | date                     |           |          | 
 closed_trades            | integer                  |           |          | 0
 wins                     | integer                  |           |          | 0
 losses                   | integer                  |           |          | 0
 avg_r                    | numeric(6,2)             |           |          | 
 realized_pnl             | numeric(12,2)            |           |          | 
 repeated_mistakes        | text                     |           |          | 
 positive_patterns        | text                     |           |          | 
 negative_patterns        | text                     |           |          | 
 confidence_delta_summary | text                     |           |          | 
 review_recommendation    | character varying(30)    |           |          | 
 human_review_only        | boolean                  |           |          | true
 updated_at               | timestamp with time zone |           |          | now()
Indexes:
    "strategy_lesson_rollup_pkey" PRIMARY KEY, btree (id)
    "strategy_lesson_rollup_strategy_id_period_start_period_end_key" UNIQUE CONSTRAINT, btree (strategy_id, period_start, period_end)

```

### Sample rows

```
 id |  strategy_id   | period_start | period_end | closed_trades | wins | losses | avg_r | realized_pnl | repeated_mistakes | positive_patterns | negative_patterns |    confidence_delta_summary     | review_recommendation | human_review_only |          updated_at           
----+----------------+--------------+------------+---------------+------+--------+-------+--------------+-------------------+-------------------+-------------------+---------------------------------+-----------------------+-------------------+-------------------------------
  6 | swing_trade    | 2026-04-19   | 2026-05-19 |             1 |    0 |      1 | -0.82 |       -15.39 | []                | []                | []                | positive:0 neutral:0 negative:1 | pause_strategy        | t                 | 2026-05-19 19:56:06.857952-04
  5 | swing_breakout | 2026-04-19   | 2026-05-19 |             2 |    1 |      0 |  0.23 |        67.83 | []                | []                | []                | positive:0 neutral:2 negative:0 | review_exit_rule      | t                 | 2026-05-19 19:56:06.857952-04
  4 | screener       | 2026-04-19   | 2026-05-19 |             1 |    0 |      0 |  0.00 |         0.00 | []                | []                | []                | positive:0 neutral:1 negative:0 | monitor               | t                 | 2026-05-19 19:56:06.857952-04
(3 rows)

```

## Stop-Related Tables

```
 stop_confirmations
 stop_decisions
 stop_snooze
 stopped_out_relist_events
 stopped_out_watch
 stopped_out_watch_history
 trailing_stop_analysis

```

## Backtest-Related Tables

```
 backtest_datasets
 backtest_learning_evidence_links
 backtest_run_log
 proposal_backtest_snapshots
 strategy_backtest_results
 strategy_backtest_runs
 strategy_backtest_trades
 trade_backtest_results

```

## Agent-Related Tables

```
 agent_calibration
 agent_calibration_events
 agent_calibration_run_log
 agent_calibration_windows
 agent_chain_runs
 agent_classification_suggestions
 agent_conflicts
 agent_context_refreshes
 agent_curation_events
 agent_data_source_rules
 agent_debate_log
 agent_decision_journal
 agent_disagreement_outcomes
 agent_discovery_log
 agent_event_queue
 agent_feedback_log
 agent_handoffs
 agent_intelligence_rules
 agent_learning_scores
 agent_performance_history
 agent_recommendation_outcome_links
 agent_recommendation_outcomes
 agent_recommendation_registry
 agent_sample_tracking
 agent_sec_rules
 agent_skills
 agent_weight_shadow_proposals
 journal_agent_coaching
 proposal_agent_reviews
 watchlist_agent_jobs
 watchlist_agent_results

```

## Traceability Analysis

### Key linkage columns

```
 paper_execution_quality                   | order_id
 agent_curation_events                     | paper_trade_id
 agent_recommendation_outcome_links        | paper_trade_id
 broker_reconciliation_items               | paper_trade_id
 open_trade_alerts                         | paper_trade_id
 open_trade_due_diligence_events           | paper_trade_id
 open_trade_intelligence_snapshots         | paper_trade_id
 paper_broker_reconciliation_items         | paper_trade_id
 paper_execution_events                    | paper_trade_id
 paper_execution_quality                   | paper_trade_id
 paper_execution_quality_events            | paper_trade_id
 paper_order_modification_proposals        | paper_trade_id
 paper_trade_analysis                      | paper_trade_id
 paper_trade_execution_rechecks            | paper_trade_id
 paper_trade_lifecycle_outcomes            | paper_trade_id
 paper_trade_multi_reviews                 | paper_trade_id
 paper_trade_outcome_analytics             | paper_trade_id
 paper_trade_proposals                     | paper_trade_id
 paper_trade_risk_actions                  | paper_trade_id
 proposal_event_log                        | paper_trade_id
 proposal_outcome_chain                    | paper_trade_id
 regime_trade_alignment                    | paper_trade_id
 trade_thesis_outcomes                     | paper_trade_id
 trade_thesis_reviews                      | paper_trade_id
 agent_curation_events                     | proposal_id
 agent_feedback_log                        | proposal_id
 agent_recommendation_outcome_links        | proposal_id
 atm_decision_log                          | proposal_id
 auto_proposal_decisions                   | proposal_id
 backtest_learning_evidence_links          | proposal_id
 broker_reconciliation_items               | proposal_id
 catalyst_quality_results                  | proposal_id
 config_change_proposals                   | proposal_id
 enrichment_log                            | proposal_id
 learning_promotion_decisions              | proposal_id
 learning_rollback_events                  | proposal_id
 paper_execution_events                    | proposal_id
 paper_execution_quality                   | proposal_id
 paper_order_modification_proposals        | proposal_id
 paper_proposal_analysis                   | proposal_id
 paper_proposal_approval_audit             | proposal_id
 paper_proposal_stale_sweep_audit          | proposal_id
 paper_trade_execution_windows             | proposal_id
 paper_trade_lifecycle_outcomes            | proposal_id
 paper_trade_pre_execution_events          | proposal_id
 paper_trades                              | proposal_id
 post_trade_price_analysis                 | proposal_id
 proposal_agent_reviews                    | proposal_id
 proposal_backtest_snapshots               | proposal_id
 proposal_enrichment_events                | proposal_id
 proposal_event_log                        | proposal_id
 proposal_evidence_snapshots               | proposal_id
 proposal_execution_readiness              | proposal_id
 proposal_lifecycle_events                 | proposal_id
 proposal_llm_review_queue                 | proposal_id
 proposal_outcome_chain                    | proposal_id
 proposal_quality_reviews                  | proposal_id
 proposal_research_packets                 | proposal_id
 proposal_technical_snapshots              | proposal_id
 regime_learning_evidence_links            | proposal_id
 regime_trade_alignment                    | proposal_id
 strategy_setup_matches                    | proposal_id
 telegram_proposal_messages                | proposal_id
 trade_instructions                        | proposal_id
 trade_thesis_outcomes                     | proposal_id
 trade_thesis_reviews                      | proposal_id
 audit_log                                 | signal_id
 paper_trades                              | signal_id
 regime_learning_evidence_links            | signal_id
 strategy_rotation_signals                 | signal_id
 trade_closed                              | signal_id
 trade_plans                               | signal_id
 auto_proposal_decisions                   | source_signal_id
 paper_trade_proposals                     | source_signal_id
 paper_trades                              | source_signal_id
 strategy_setup_matches                    | source_signal_id
 agent_calibration_events                  | strategy_id
 agent_calibration_windows                 | strategy_id
 agent_curation_events                     | strategy_id
 agent_disagreement_outcomes               | strategy_id
 agent_recommendation_outcome_links        | strategy_id
 agent_recommendation_registry             | strategy_id
 agent_weight_shadow_proposals             | strategy_id
 atm_decision_log                          | strategy_id
 audit_log                                 | strategy_id
 auto_proposal_decisions                   | strategy_id
 challenger_definitions                    | strategy_id
 champion_challenger_results               | strategy_id
 historical_trade_strategy_classifications | strategy_id
 incubator_events                          | strategy_id
 incubator_universe                        | strategy_id
 learning_evidence                         | strategy_id
 learning_hypotheses                       | strategy_id
 open_trade_alerts                         | strategy_id
 paper_execution_quality                   | strategy_id
 paper_performance_governance              | strategy_id
 paper_proposal_analysis                   | strategy_id
 paper_trade_analysis                      | strategy_id
 paper_trade_execution_windows             | strategy_id
 paper_trade_outcome_analytics             | strategy_id
 paper_trade_proposals                     | strategy_id
 paper_trades                              | strategy_id
 pattern_library                           | strategy_id
 post_trade_price_analysis                 | strategy_id
 proposal_agent_reviews                    | strategy_id
 proposal_backtest_snapshots               | strategy_id
 proposal_evidence_snapshots               | strategy_id
 proposal_execution_readiness              | strategy_id
 proposal_lifecycle_events                 | strategy_id
 proposal_llm_review_queue                 | strategy_id
 proposal_outcome_chain                    | strategy_id
 proposal_quality_reviews                  | strategy_id
 proposal_research_packets                 | strategy_id
 regime_trade_alignment                    | strategy_id
 risk_gate_results                         | strategy_id
 strategy_activations                      | strategy_id
 strategy_backtest_results                 | strategy_id
 strategy_backtest_runs                    | strategy_id
 strategy_backtest_trades                  | strategy_id
 strategy_cards                            | strategy_id
 strategy_config_versions                  | strategy_id
 strategy_learning_scores                  | strategy_id
 strategy_lesson_rollup                    | strategy_id
 strategy_parameter_versions               | strategy_id
 strategy_performance_snapshots            | strategy_id
 strategy_prompt_context_cache             | strategy_id
 strategy_regime_profiles                  | strategy_id
 strategy_registry                         | strategy_id
 strategy_rotation_signals                 | strategy_id
 strategy_setup_matches                    | strategy_id
 strategy_signals                          | strategy_id
 strategy_state_transitions                | strategy_id
 strategy_watchpool                        | strategy_id
 thesis_learning_evidence_links            | strategy_id
 trade_closed                              | strategy_id
 trade_lesson_memory                       | strategy_id
 trade_plans                               | strategy_id
 trade_thesis_outcomes                     | strategy_id
 trade_thesis_reviews                      | strategy_id
 trailing_stop_analysis                    | strategy_id
 universe_strategy_fit_audit               | strategy_id
 weekly_learning_digest_items              | strategy_id
 paper_trade_proposals                     | trade_plan_id
 paper_trades                              | trade_plan_id

```
