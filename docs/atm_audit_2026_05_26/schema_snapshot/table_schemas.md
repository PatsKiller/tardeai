# Schema Snapshot -- ATM Audit 2026-05-26

Status:      HISTORICAL
as_of:       2026-05-26T11:21:21-04:00
Measured at: efcc51365 / not measured

## pipeline_runs (11 columns)
  id                                       bigint               nullable=NO default=nextval('pipeline_runs_id_seq1
  run_id                                   text                 nullable=NO default=
  pipeline_key                             text                 nullable=NO default=
  run_label                                text                 nullable=YES default=
  status                                   text                 nullable=NO default='created'::text
  trigger_source                           text                 nullable=YES default=
  started_at                               timestamp with time zone nullable=YES default=
  finished_at                              timestamp with time zone nullable=YES default=
  duration_seconds                         numeric              nullable=YES default=
  summary                                  jsonb                nullable=YES default=
  created_at                               timestamp with time zone nullable=YES default=now()

## system_health_checks (17 columns)
  id                                       integer              nullable=NO default=nextval('system_health_checks_
  check_type                               text                 nullable=NO default=
  component                                text                 nullable=NO default=
  status                                   text                 nullable=NO default=
  expected_schedule                        text                 nullable=YES default=
  last_success_at                          timestamp with time zone nullable=YES default=
  last_failure_at                          timestamp with time zone nullable=YES default=
  last_run_duration_sec                    double precision     nullable=YES default=
  expected_max_duration_sec                double precision     nullable=YES default=
  failure_count                            integer              nullable=YES default=0
  retry_count                              integer              nullable=YES default=0
  last_error                               text                 nullable=YES default=
  last_action                              text                 nullable=YES default=
  downstream_impact                        text                 nullable=YES default=
  severity                                 text                 nullable=YES default='INFO'::text
  created_at                               timestamp with time zone nullable=YES default=now()
  updated_at                               timestamp with time zone nullable=YES default=now()

## system_health_events (8 columns)
  id                                       integer              nullable=NO default=nextval('system_health_events_
  component                                text                 nullable=NO default=
  event_type                               text                 nullable=NO default=
  severity                                 text                 nullable=NO default=
  message                                  text                 nullable=YES default=
  action_taken                             text                 nullable=YES default=
  success                                  boolean              nullable=YES default=
  created_at                               timestamp with time zone nullable=YES default=now()

## paper_trade_proposals (202 columns)
  id                                       integer              nullable=NO default=nextval('paper_trade_proposals
  symbol                                   text                 nullable=NO default=
  strategy_id                              text                 nullable=NO default='momentum_scalp'::text
  setup_type                               text                 nullable=YES default=
  signal_score                             numeric              nullable=YES default=
  signal_grade                             text                 nullable=YES default=
  signal_decision                          text                 nullable=YES default=
  source_signal_id                         integer              nullable=YES default=
  source_strategy_card_id                  integer              nullable=YES default=
  trade_plan_id                            integer              nullable=YES default=
  rvol                                     numeric              nullable=YES default=
  float_m                                  numeric              nullable=YES default=
  gap_pct                                  numeric              nullable=YES default=
  catalyst                                 text                 nullable=YES default=
  catalyst_verified                        boolean              nullable=YES default=false
  source_quality_score                     numeric              nullable=YES default=
  data_quality_score                       integer              nullable=YES default=
  intel_readiness                          integer              nullable=YES default=
  vix_at_proposal                          numeric              nullable=YES default=
  market_regime                            text                 nullable=YES default=
  proposed_account                         text                 nullable=YES default=
  proposed_entry                           numeric              nullable=NO default=
  proposed_stop                            numeric              nullable=NO default=
  proposed_target1                         numeric              nullable=NO default=
  proposed_target2                         numeric              nullable=YES default=
  proposed_shares                          integer              nullable=NO default=
  proposed_dollar_size                     numeric              nullable=YES default=
  proposed_dollar_risk                     numeric              nullable=YES default=
  proposed_stop_pct                        numeric              nullable=YES default=
  proposed_rr                              numeric              nullable=YES default=
  tos_order_string                         text                 nullable=YES default=
  final_account                            text                 nullable=YES default=
  final_entry                              numeric              nullable=YES default=
  final_stop                               numeric              nullable=YES default=
  final_target1                            numeric              nullable=YES default=
  final_shares                             integer              nullable=YES default=
  final_dollar_risk                        numeric              nullable=YES default=
  risk_gate_result                         text                 nullable=YES default=
  risk_gate_codes                          jsonb                nullable=YES default=
  proposed_by                              text                 nullable=YES default='system'::text
  status                                   text                 nullable=YES default='PENDING'::text
  paper_trade_id                           integer              nullable=YES default=
  approved_at                              timestamp with time zone nullable=YES default=
  rejected_at                              timestamp with time zone nullable=YES default=
  rejection_reason                         text                 nullable=YES default=
  expires_at                               timestamp with time zone nullable=NO default=
  created_at                               timestamp with time zone nullable=YES default=now()
  updated_at                               timestamp with time zone nullable=YES default=now()
  quality_pass                             boolean              nullable=YES default=
  quality_reason_codes                     jsonb                nullable=YES default=
  hidden_by_quality_filter                 boolean              nullable=YES default=false
  source_table                             text                 nullable=YES default=
  source_record_id                         text                 nullable=YES default=
  screener_name                            text                 nullable=YES default=
  discovery_source                         text                 nullable=YES default=
  setup_description                        text                 nullable=YES default=
  catalyst_confidence                      numeric              nullable=YES default=
  critic_verdict                           text                 nullable=YES default=
  critic_confidence                        numeric              nullable=YES default=
  critic_reasoning                         text                 nullable=YES default=
  sector                                   text                 nullable=YES default=
  industry                                 text                 nullable=YES default=
  country                                  text                 nullable=YES default=
  atr                                      numeric              nullable=YES default=
  atr_pct                                  numeric              nullable=YES default=
  rsi                                      numeric              nullable=YES default=
  vwap_distance                            numeric              nullable=YES default=
  above_vwap                               boolean              nullable=YES default=
  fib_context                              jsonb                nullable=YES default=
  normal_pattern_summary                   text                 nullable=YES default=
  missing_data                             jsonb                nullable=YES default=
  risk_pct_portfolio                       numeric              nullable=YES default=
  target1_dollar_reward                    numeric              nullable=YES default=
  target2_dollar_reward                    numeric              nullable=YES default=
  research_packet_id                       integer              nullable=YES default=
  agent_review_status                      text                 nullable=YES default=
  local_llm_review_status                  text                 nullable=YES default=
  backtest_status                          text                 nullable=YES default=
  research_score                           numeric              nullable=YES default=
  confidence_score                         numeric              nullable=YES default=
  live_readiness_score                     numeric              nullable=YES default=
  approval_blocked_reason                  text                 nullable=YES default=
  approval_allowed                         boolean              nullable=YES default=
  required_reviews                         jsonb                nullable=YES default=
  completed_reviews                        jsonb                nullable=YES default=
  stock_history_summary                    text                 nullable=YES default=
  technical_context                        jsonb                nullable=YES default=
  backtest_summary                         jsonb                nullable=YES default=
  auto_created                             boolean              nullable=YES default=false
  auto_proposal_run_id                     integer              nullable=YES default=
  sizing_adjusted                          boolean              nullable=YES default=false
  original_shares                          integer              nullable=YES default=
  adjusted_shares                          integer              nullable=YES default=
  sizing_reason                            text                 nullable=YES default=
  auto_proposal_reason                     jsonb                nullable=YES default=
  source_run_label                         text                 nullable=YES default=
  auto_execution_label                     text                 nullable=YES default=
  institutional_packet_ready               boolean              nullable=YES default=false
  latest_execution_readiness               text                 nullable=YES default=
  latest_strategy_edge                     jsonb                nullable=YES default=
  latest_evidence_snapshot_id              integer              nullable=YES default=
  alpaca_paper_submit_enabled              boolean              nullable=YES default=false
  live_submit_blocked_reason               text                 nullable=YES default='Live trading disabled pending
  lifecycle_status                         text                 nullable=YES default='ACTIVE'::text
  lifecycle_message                        text                 nullable=YES default=
  entry_zone_status                        text                 nullable=YES default=
  entry_zone_valid                         boolean              nullable=YES default=
  current_price                            numeric              nullable=YES default=
  price_drift_pct                          numeric              nullable=YES default=
  last_price_source                        text                 nullable=YES default=
  last_price_checked_at                    timestamp with time zone nullable=YES default=
  base_expires_at                          timestamp with time zone nullable=YES default=
  max_expires_at                           timestamp with time zone nullable=YES default=
  expiry_extended_count                    integer              nullable=YES default=0
  last_lifecycle_check_at                  timestamp with time zone nullable=YES default=
  overnight_monitoring_enabled             boolean              nullable=YES default=false
  proposal_timeframe_class                 text                 nullable=YES default=
  manual_review_required                   boolean              nullable=YES default=false
  lifecycle_blockers                       jsonb                nullable=YES default=
  lifecycle_warnings                       jsonb                nullable=YES default=
  primary_strategy_id                      text                 nullable=YES default=
  secondary_strategy_ids                   jsonb                nullable=YES default=
  setup_stack                              jsonb                nullable=YES default=
  strategy_config_hash                     text                 nullable=YES default=
  strategy_prompt_context                  text                 nullable=YES default=
  packet_state                             text                 nullable=YES default='NEW'::text
  packet_completion_pct                    numeric              nullable=YES default=0
  llm_review_status                        text                 nullable=YES default='NOT_REQUESTED'::text
  packet_last_enriched_at                  timestamp with time zone nullable=YES default=
  packet_next_refresh_at                   timestamp with time zone nullable=YES default=
  packet_blockers                          jsonb                nullable=YES default=
  packet_warnings                          jsonb                nullable=YES default=
  missing_data_by_section                  jsonb                nullable=YES default=
  action_state                             text                 nullable=YES default=
  action_label                             text                 nullable=YES default=
  top_blocker                              text                 nullable=YES default=
  next_actions                             jsonb                nullable=YES default=
  llm_review_queued_at                     timestamp with time zone nullable=YES default=
  enrichment_attempt_count                 integer              nullable=YES default=0
  last_enrichment_error                    text                 nullable=YES default=
  llm_model_used                           text                 nullable=YES default=
  llm_review_stage                         text                 nullable=YES default=
  llm_review_chunks                        jsonb                nullable=YES default=
  paper_submit_state                       text                 nullable=YES default='NOT_SUBMITTED'::text
  paper_submit_blockers                    jsonb                nullable=YES default=
  paper_submit_warnings                    jsonb                nullable=YES default=
  paper_submit_checked_at                  timestamp with time zone nullable=YES default=
  paper_submitted_at                       timestamp with time zone nullable=YES default=
  paper_client_order_id                    text                 nullable=YES default=
  paper_broker_order_id                    text                 nullable=YES default=
  paper_submit_payload                     jsonb                nullable=YES default=
  paper_submit_result                      jsonb                nullable=YES default=
  execution_recheck_required               boolean              nullable=YES default=true
  approved_pending_recheck                 boolean              nullable=YES default=false
  execution_recheck_reason                 text                 nullable=YES default=
  last_recheck_id                          text                 nullable=YES default=
  execution_validated_at                   timestamp with time zone nullable=YES default=
  execution_readiness_score                numeric              nullable=YES default=
  material_change_pending_approval         boolean              nullable=YES default=false
  next_recheck_at                          timestamp with time zone nullable=YES default=
  recommendation_created_at                timestamp with time zone nullable=YES default=
  last_plan_price                          numeric              nullable=YES default=
  last_plan_updated_at                     timestamp with time zone nullable=YES default=
  execution_status                         text                 nullable=YES default='not_submitted'::text
  execution_eligibility_status             text                 nullable=YES default=
  execution_eligibility_reason             text                 nullable=YES default=
  live_price_at_execution                  numeric              nullable=YES default=
  live_price_timestamp                     timestamp with time zone nullable=YES default=
  outcome_trade_id                         integer              nullable=YES default=
  outcome_r_multiple                       numeric              nullable=YES default=
  outcome_pnl                              numeric              nullable=YES default=
  outcome_pnl_pct                          numeric              nullable=YES default=
  outcome_verdict                          character varying    nullable=YES default=
  outcome_thesis_confirmed                 boolean              nullable=YES default=
  outcome_closed_at                        timestamp with time zone nullable=YES default=
  outcome_hold_hours                       integer              nullable=YES default=
  expiry_reason                            text                 nullable=YES default=
  executed_at                              timestamp with time zone nullable=YES default=
  executed_trade_id                        integer              nullable=YES default=
  is_top_pick                              boolean              nullable=YES default=false
  rank_among_peers                         integer              nullable=YES default=
  peer_group_id                            text                 nullable=YES default=
  alert_count                              integer              nullable=YES default=0
  last_alert_at                            timestamp with time zone nullable=YES default=
  last_alert_type                          text                 nullable=YES default=
  expired_reason                           text                 nullable=YES default=
  expired_at                               timestamp with time zone nullable=YES default=
  override_payload                         jsonb                nullable=YES default=
  approved_by                              text                 nullable=YES default=
  target_account                           text                 nullable=YES default='alpaca_paper'::text
  atm_action                               text                 nullable=YES default=
  atm_action_set_by                        text                 nullable=YES default=
  atm_action_set_at                        timestamp with time zone nullable=YES default=
  enrichment_failures                      integer              nullable=NO default=0
  enrichment_status                        text                 nullable=YES default=
  enrichment_last_attempt_at               timestamp with time zone nullable=YES default=
  enrichment_last_error                    text                 nullable=YES default=
  atm_evaluation_count                     integer              nullable=NO default=0
  atm_last_evaluation_at                   timestamp with time zone nullable=YES default=
  atm_last_failure_reason                  text                 nullable=YES default=
  atm_expired_at                           timestamp with time zone nullable=YES default=
  atm_expiry_reason                        text                 nullable=YES default=

## paper_trades (107 columns)
  id                                       integer              nullable=NO default=nextval('paper_trades_id_seq':
  signal_id                                integer              nullable=YES default=
  strategy_id                              text                 nullable=NO default=
  symbol                                   text                 nullable=NO default=
  account                                  text                 nullable=NO default=
  entry_price                              numeric              nullable=YES default=
  entry_time                               timestamp with time zone nullable=YES default=
  shares                                   integer              nullable=YES default=
  dollar_size                              numeric              nullable=YES default=
  stop_loss                                numeric              nullable=YES default=
  target_1                                 numeric              nullable=YES default=
  target_2                                 numeric              nullable=YES default=
  dollar_risk                              numeric              nullable=YES default=150
  score_at_entry                           integer              nullable=YES default=
  rvol_at_entry                            numeric              nullable=YES default=
  float_m_at_entry                         numeric              nullable=YES default=
  catalyst_at_entry                        text                 nullable=YES default=
  catalyst_verified                        boolean              nullable=YES default=
  intel_readiness                          integer              nullable=YES default=
  vix_at_entry                             numeric              nullable=YES default=
  market_regime                            text                 nullable=YES default=
  trade_plan_id                            integer              nullable=YES default=
  exit_price                               numeric              nullable=YES default=
  exit_time                                timestamp with time zone nullable=YES default=
  exit_reason                              text                 nullable=YES default=
  pnl                                      numeric              nullable=YES default=
  pnl_pct                                  numeric              nullable=YES default=
  hold_time_min                            integer              nullable=YES default=
  planned_entry                            numeric              nullable=YES default=
  entry_slippage                           numeric              nullable=YES default=
  planned_stop                             numeric              nullable=YES default=
  stop_slippage                            numeric              nullable=YES default=
  max_adverse_excursion                    numeric              nullable=YES default=
  max_favorable_excursion                  numeric              nullable=YES default=
  outcome_verdict                          text                 nullable=YES default=
  status                                   text                 nullable=YES default='open'::text
  logged_by                                text                 nullable=YES default='system'::text
  created_at                               timestamp with time zone nullable=YES default=now()
  closed_at                                timestamp with time zone nullable=YES default=
  updated_at                               timestamp with time zone nullable=YES default=now()
  broker_order_id                          text                 nullable=YES default=
  broker_status                            text                 nullable=YES default=
  order_type                               text                 nullable=YES default=
  source_signal_id                         integer              nullable=YES default=
  source_strategy_card_id                  integer              nullable=YES default=
  risk_gate_result                         text                 nullable=YES default=
  risk_gate_reason_codes                   jsonb                nullable=YES default=
  opened_via                               text                 nullable=YES default=
  closed_via                               text                 nullable=YES default=
  current_price                            numeric              nullable=YES default=
  unrealized_pnl                           numeric              nullable=YES default=
  last_synced_at                           timestamp with time zone nullable=YES default=
  notes                                    text                 nullable=YES default=
  proposal_id                              integer              nullable=YES default=
  setup_type                               text                 nullable=YES default=
  signal_grade                             text                 nullable=YES default=
  automation_source                        text                 nullable=YES default=
  broker_submitted_at                      timestamp with time zone nullable=YES default=
  broker_filled_at                         timestamp with time zone nullable=YES default=
  broker_closed_at                         timestamp with time zone nullable=YES default=
  source_quality_score                     numeric              nullable=YES default=
  data_quality_score                       integer              nullable=YES default=
  r_multiple                               numeric              nullable=YES default=
  planned_vs_actual_entry                  numeric              nullable=YES default=
  monitored_at                             timestamp with time zone nullable=YES default=
  last_alert_at                            timestamp with time zone nullable=YES default=
  stale_flag                               boolean              nullable=YES default=false
  thesis_status                            text                 nullable=YES default=
  post_trade_analyzed                      boolean              nullable=YES default=false
  iris_curated                             boolean              nullable=YES default=false
  aegis_summarized                         boolean              nullable=YES default=false
  research_packet_id                       integer              nullable=YES default=
  decision_state                           text                 nullable=YES default=
  confidence_score                         numeric              nullable=YES default=
  agent_votes                              jsonb                nullable=YES default=
  backtest_quality                         text                 nullable=YES default=
  approval_mode                            text                 nullable=YES default=
  broker                                   text                 nullable=YES default='alpaca_paper'::text
  client_order_id                          text                 nullable=YES default=
  bracket_order                            boolean              nullable=YES default=false
  take_profit_price                        numeric              nullable=YES default=
  stop_loss_price                          numeric              nullable=YES default=
  submitted_at                             timestamp with time zone nullable=YES default=
  filled_at                                timestamp with time zone nullable=YES default=
  close_requested_at                       timestamp with time zone nullable=YES default=
  close_reason                             text                 nullable=YES default=
  close_order_id                           text                 nullable=YES default=
  close_result                             jsonb                nullable=YES default=
  entered_after_recheck                    boolean              nullable=YES default=false
  entry_recheck_id                         text                 nullable=YES default=
  entry_readiness_score                    numeric              nullable=YES default=
  recommendation_to_entry_seconds          numeric              nullable=YES default=
  approval_to_entry_seconds                numeric              nullable=YES default=
  risk_params_at_fill                      jsonb                nullable=YES default=
  lifecycle_state                          text                 nullable=YES default='open'::text
  revalidation_verdict                     character varying    nullable=YES default=
  revalidation_score                       integer              nullable=YES default=
  revalidation_flags                       jsonb                nullable=YES default=
  price_at_approval                        numeric              nullable=YES default=
  staleness_at_submit_min                  integer              nullable=YES default=
  broker_confirmed                         boolean              nullable=YES default=
  target_account                           text                 nullable=YES default='alpaca_paper'::text
  atm_decision_id                          bigint               nullable=YES default=
  atm_config_hash                          text                 nullable=YES default=
  atm_during_b1                            boolean              nullable=YES default=false
  stop_order_id                            text                 nullable=YES default=
  stop_updated_at                          timestamp with time zone nullable=YES default=

## strategy_signals (47 columns)
  id                                       integer              nullable=NO default=nextval('strategy_signals_id_s
  strategy_id                              text                 nullable=NO default=
  symbol                                   text                 nullable=NO default=
  signal_type                              text                 nullable=NO default='LONG'::text
  signal_grade                             text                 nullable=YES default=
  signal_score                             numeric              nullable=YES default=
  price                                    numeric              nullable=YES default=
  rvol                                     numeric              nullable=YES default=
  float_m                                  numeric              nullable=YES default=
  gap_pct                                  numeric              nullable=YES default=
  catalyst                                 text                 nullable=YES default=
  catalyst_verified                        boolean              nullable=YES default=false
  setup_description                        text                 nullable=YES default=
  entry_low                                numeric              nullable=YES default=
  entry_high                               numeric              nullable=YES default=
  stop_loss                                numeric              nullable=YES default=
  target_1                                 numeric              nullable=YES default=
  target_2                                 numeric              nullable=YES default=
  risk_reward                              numeric              nullable=YES default=
  shares                                   integer              nullable=YES default=
  dollar_risk                              numeric              nullable=YES default=
  vix_at_signal                            numeric              nullable=YES default=
  market_regime                            text                 nullable=YES default=
  sector                                   text                 nullable=YES default=
  intel_readiness                          integer              nullable=YES default=
  source_quality                           numeric              nullable=YES default=
  status                                   text                 nullable=YES default='active'::text
  fired_at                                 timestamp with time zone nullable=YES default=now()
  expires_at                               timestamp with time zone nullable=YES default=
  telegram_sent                            boolean              nullable=YES default=false
  trade_journal_id                         integer              nullable=YES default=
  outcome_verdict                          text                 nullable=YES default=
  outcome_pnl                              numeric              nullable=YES default=
  source_table                             text                 nullable=YES default=
  source_record_id                         text                 nullable=YES default=
  scan_run_label                           text                 nullable=YES default=
  screener_label                           text                 nullable=YES default=
  discovery_source                         text                 nullable=YES default=
  sync_created_by                          text                 nullable=YES default=
  sync_run_id                              text                 nullable=YES default=
  route_match_reasons                      jsonb                nullable=YES default=
  route_reject_reasons                     jsonb                nullable=YES default=
  route_score                              numeric              nullable=YES default=
  setup_stack                              jsonb                nullable=YES default=
  primary_strategy_id                      text                 nullable=YES default=
  secondary_strategy_ids                   jsonb                nullable=YES default=
  strategy_config_hash                     text                 nullable=YES default=

## paper_execution_quality (34 columns)
  id                                       integer              nullable=NO default=nextval('paper_execution_quali
  paper_trade_id                           integer              nullable=YES default=
  proposal_id                              integer              nullable=YES default=
  symbol                                   text                 nullable=NO default=
  strategy_id                              text                 nullable=YES default=
  order_id                                 text                 nullable=YES default=
  client_order_id                          text                 nullable=YES default=
  intended_entry                           numeric              nullable=YES default=
  submitted_limit_price                    numeric              nullable=YES default=
  fill_price                               numeric              nullable=YES default=
  arrival_price                            numeric              nullable=YES default=
  quote_bid                                numeric              nullable=YES default=
  quote_ask                                numeric              nullable=YES default=
  spread_pct                               numeric              nullable=YES default=
  slippage_pct                             numeric              nullable=YES default=
  slippage_dollars                         numeric              nullable=YES default=
  fill_quality                             text                 nullable=YES default=
  liquidity_context                        jsonb                nullable=YES default=
  tca_payload                              jsonb                nullable=YES default=
  created_at                               timestamp with time zone nullable=YES default=now()
  order_submitted_at                       timestamp with time zone nullable=YES default=
  order_filled_at                          timestamp with time zone nullable=YES default=
  time_to_fill_seconds                     numeric              nullable=YES default=
  intended_shares                          numeric              nullable=YES default=
  filled_shares                            numeric              nullable=YES default=
  partial_fill                             boolean              nullable=YES default=false
  price_improvement_pct                    numeric              nullable=YES default=
  quote_age_seconds                        numeric              nullable=YES default=
  market_session                           text                 nullable=YES default=
  readiness_state_at_submit                text                 nullable=YES default=
  lifecycle_state_at_submit                text                 nullable=YES default=
  action_state_at_submit                   text                 nullable=YES default=
  packet_completion_pct_at_submit          numeric              nullable=YES default=
  data_quality_grade                       text                 nullable=YES default=

## paper_execution_quality_events (19 columns)
  id                                       bigint               nullable=NO default=nextval('paper_execution_quali
  paper_trade_id                           bigint               nullable=YES default=
  symbol                                   text                 nullable=NO default=
  event_type                               text                 nullable=NO default=
  broker_order_id                          text                 nullable=YES default=
  expected_price                           numeric              nullable=YES default=
  actual_price                             numeric              nullable=YES default=
  slippage_abs                             numeric              nullable=YES default=
  slippage_bps                             numeric              nullable=YES default=
  expected_qty                             numeric              nullable=YES default=
  actual_qty                               numeric              nullable=YES default=
  fill_latency_seconds                     numeric              nullable=YES default=
  spread_bps                               numeric              nullable=YES default=
  quote_source                             text                 nullable=YES default=
  quote_freshness_seconds                  numeric              nullable=YES default=
  market_session                           text                 nullable=YES default=
  quality_grade                            text                 nullable=YES default=
  result                                   jsonb                nullable=YES default=
  created_at                               timestamp with time zone nullable=YES default=now()

## paper_trade_outcome_analytics (30 columns)
  id                                       bigint               nullable=NO default=nextval('paper_trade_outcome_a
  paper_trade_id                           bigint               nullable=YES default=
  symbol                                   text                 nullable=NO default=
  strategy_id                              text                 nullable=YES default=
  opened_at                                timestamp with time zone nullable=YES default=
  closed_at                                timestamp with time zone nullable=YES default=
  hold_minutes                             numeric              nullable=YES default=
  entry_price                              numeric              nullable=YES default=
  exit_price                               numeric              nullable=YES default=
  stop_price                               numeric              nullable=YES default=
  target_price                             numeric              nullable=YES default=
  pnl                                      numeric              nullable=YES default=
  pnl_pct                                  numeric              nullable=YES default=
  r_multiple                               numeric              nullable=YES default=
  max_favorable_excursion                  numeric              nullable=YES default=
  max_adverse_excursion                    numeric              nullable=YES default=
  exit_reason                              text                 nullable=YES default=
  planned_r                                numeric              nullable=YES default=
  realized_r                               numeric              nullable=YES default=
  followed_plan                            boolean              nullable=YES default=
  stop_adjusted_count                      integer              nullable=YES default=0
  limit_adjusted_count                     integer              nullable=YES default=0
  modification_proposals_count             integer              nullable=YES default=0
  approved_modifications_count             integer              nullable=YES default=0
  rejected_modifications_count             integer              nullable=YES default=0
  tca_grade                                text                 nullable=YES default=
  outcome_verdict                          text                 nullable=YES default=
  lessons                                  jsonb                nullable=YES default=
  created_at                               timestamp with time zone nullable=YES default=now()
  updated_at                               timestamp with time zone nullable=YES default=now()

## trade_ai_scans (49 columns)
  id                                       bigint               nullable=NO default=nextval('trade_ai_scans_id_seq
  run_id                                   text                 nullable=NO default=
  run_date                                 date                 nullable=NO default=
  run_label                                text                 nullable=NO default=
  run_type                                 text                 nullable=NO default='full'::text
  scanned_at                               timestamp with time zone nullable=NO default=now()
  symbol                                   text                 nullable=NO default=
  score                                    integer              nullable=NO default=
  grade                                    text                 nullable=YES default=
  decision                                 text                 nullable=NO default=
  original_decision                        text                 nullable=YES default=
  rvol                                     real                 nullable=YES default=
  price                                    real                 nullable=YES default=
  change_pct                               real                 nullable=YES default=
  gap_pct                                  real                 nullable=YES default=
  float_m                                  real                 nullable=YES default=
  volume                                   bigint               nullable=YES default=
  catalyst                                 text                 nullable=YES default=
  catalyst_verified                        boolean              nullable=YES default=
  catalyst_confidence                      real                 nullable=YES default=
  catalyst_source                          text                 nullable=YES default=
  critic_verdict                           text                 nullable=YES default=
  critic_confidence                        real                 nullable=YES default=
  critic_reasoning                         text                 nullable=YES default=
  decision_changed                         boolean              nullable=YES default=false
  disqualified                             boolean              nullable=YES default=false
  disqualification_reason                  text                 nullable=YES default=
  sector                                   text                 nullable=YES default=
  industry                                 text                 nullable=YES default=
  country                                  text                 nullable=YES default=
  sector_etf                               text                 nullable=YES default=
  ticker_perf_1m                           real                 nullable=YES default=
  sector_perf_1m                           real                 nullable=YES default=
  vs_sector_pct                            real                 nullable=YES default=
  social_sentiment                         text                 nullable=YES default=
  social_score                             real                 nullable=YES default=
  social_reddit                            integer              nullable=YES default=0
  social_stocktwits                        integer              nullable=YES default=0
  social_bullish_pct                       real                 nullable=YES default=
  social_wsb                               integer              nullable=YES default=0
  source                                   text                 nullable=YES default='screener'::text
  source_detail                            text                 nullable=YES default=
  mention_count                            integer              nullable=YES default=0
  social_sources                           ARRAY                nullable=YES default='{}'::text[]
  screener_label                           text                 nullable=YES default=
  intelligence_readiness                   integer              nullable=YES default=0
  intel_components                         jsonb                nullable=YES default=
  intelligence_readiness_source            text                 nullable=YES default='computed'::text
  intelligence_readiness_updated_at        timestamp with time zone nullable=YES default=now()

## incubator_universe (38 columns)
  id                                       integer              nullable=NO default=nextval('incubator_universe_id
  symbol                                   text                 nullable=NO default=
  strategy_id                              text                 nullable=YES default=
  first_seen_at                            timestamp with time zone nullable=YES default=now()
  last_seen_at                             timestamp with time zone nullable=YES default=now()
  status                                   text                 nullable=YES default='ACTIVE'::text
  lifecycle_state                          text                 nullable=YES default='ROLLED_ON'::text
  source_first_seen                        text                 nullable=YES default=
  source_latest                            text                 nullable=YES default=
  source_run_label                         text                 nullable=YES default=
  baseline_score                           numeric              nullable=YES default=
  latest_score                             numeric              nullable=YES default=
  best_score                               numeric              nullable=YES default=
  score_delta                              numeric              nullable=YES default=
  rvol_baseline                            numeric              nullable=YES default=
  rvol_latest                              numeric              nullable=YES default=
  gap_baseline                             numeric              nullable=YES default=
  gap_latest                               numeric              nullable=YES default=
  catalyst                                 text                 nullable=YES default=
  catalyst_verified                        boolean              nullable=YES default=
  sector                                   text                 nullable=YES default=
  industry                                 text                 nullable=YES default=
  days_active                              integer              nullable=YES default=0
  promoted_to_signal_at                    timestamp with time zone nullable=YES default=
  promoted_to_proposal_at                  timestamp with time zone nullable=YES default=
  last_paper_trade_id                      integer              nullable=YES default=
  last_outcome                             text                 nullable=YES default=
  rolloff_reason                           text                 nullable=YES default=
  notes                                    text                 nullable=YES default=
  evidence_payload                         jsonb                nullable=YES default=
  created_at                               timestamp with time zone nullable=YES default=now()
  updated_at                               timestamp with time zone nullable=YES default=now()
  llm_screen_grade                         text                 nullable=YES default=
  llm_screen_verdict                       text                 nullable=YES default=
  llm_screen_confidence                    integer              nullable=YES default=
  llm_screen_model                         text                 nullable=YES default=
  llm_screen_result                        jsonb                nullable=YES default=
  llm_screen_at                            timestamp with time zone nullable=YES default=

## incubator_events (9 columns)
  id                                       integer              nullable=NO default=nextval('incubator_events_id_s
  symbol                                   text                 nullable=NO default=
  strategy_id                              text                 nullable=YES default=
  event_type                               text                 nullable=NO default=
  reason_codes                             jsonb                nullable=YES default=
  old_score                                numeric              nullable=YES default=
  new_score                                numeric              nullable=YES default=
  payload                                  jsonb                nullable=YES default=
  created_at                               timestamp with time zone nullable=YES default=now()

## pipeline_schedule (11 columns)
  id                                       integer              nullable=NO default=nextval('pipeline_schedule_id_
  script_name                              text                 nullable=NO default=
  display_name                             text                 nullable=YES default=
  expected_hour                            integer              nullable=YES default=
  expected_min                             integer              nullable=YES default=
  max_latency_min                          integer              nullable=YES default=15
  min_rows                                 integer              nullable=YES default=0
  critical                                 boolean              nullable=YES default=false
  active                                   boolean              nullable=YES default=true
  command                                  text                 nullable=YES default=
  run_days                                 text                 nullable=YES default='1-5'::text

## atm_decisions -- TABLE NOT FOUND

## stop_trail_decisions -- TABLE NOT FOUND

## broker_reconciliation_items (20 columns)
  id                                       integer              nullable=NO default=nextval('broker_reconciliation
  run_id                                   integer              nullable=YES default=
  broker                                   text                 nullable=YES default='alpaca_paper'::text
  broker_order_id                          text                 nullable=YES default=
  client_order_id                          text                 nullable=YES default=
  paper_trade_id                           integer              nullable=YES default=
  proposal_id                              integer              nullable=YES default=
  symbol                                   text                 nullable=YES default=
  reconciliation_state                     text                 nullable=YES default=
  issue_code                               text                 nullable=YES default=
  payload                                  jsonb                nullable=YES default=
  created_at                               timestamp with time zone nullable=YES default=now()
  local_status                             text                 nullable=YES default=
  broker_status                            text                 nullable=YES default=
  local_qty                                numeric              nullable=YES default=
  broker_qty                               numeric              nullable=YES default=
  local_avg_price                          numeric              nullable=YES default=
  broker_avg_price                         numeric              nullable=YES default=
  severity                                 text                 nullable=YES default='INFO'::text
  recommended_action                       text                 nullable=YES default=

## alert_dispatch_log (10 columns)
  id                                       integer              nullable=NO default=nextval('alert_dispatch_log_id
  alert_type                               text                 nullable=NO default=
  tier                                     text                 nullable=NO default=
  symbol                                   text                 nullable=YES default=
  condition_key                            text                 nullable=YES default=
  severity                                 text                 nullable=YES default='INFO'::text
  message                                  text                 nullable=YES default=
  metadata                                 jsonb                nullable=YES default='{}'::jsonb
  action_taken                             text                 nullable=YES default=
  created_at                               timestamp with time zone nullable=YES default=now()

## agent_queue -- TABLE NOT FOUND

## agent_curation_events (10 columns)
  id                                       integer              nullable=NO default=nextval('agent_curation_events
  paper_trade_id                           integer              nullable=YES default=
  proposal_id                              integer              nullable=YES default=
  symbol                                   text                 nullable=YES default=
  strategy_id                              text                 nullable=YES default=
  agent_name                               text                 nullable=NO default=
  event_type                               text                 nullable=NO default=
  event_summary                            text                 nullable=YES default=
  payload                                  jsonb                nullable=YES default=
  created_at                               timestamp with time zone nullable=YES default=now()
