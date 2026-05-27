# Full Lifecycle Schema Export

## strategy_signals
Rows: 337
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
```

## paper_trade_proposals
Rows: 114
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
```

## atm_decision_log
Rows: 106
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

## paper_trades
Rows: 31
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
```

## paper_execution_quality
Rows: 10
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
```

## atm_position_reconciliation_runs
Rows: 1
```
                                              Table "public.atm_position_reconciliation_runs"
          Column          |           Type           | Collation | Nullable |                           Default                            
--------------------------+--------------------------+-----------+----------+--------------------------------------------------------------
 id                       | bigint                   |           | not null | nextval('atm_position_reconciliation_runs_id_seq'::regclass)
 run_id                   | text                     |           | not null | 
 started_at               | timestamp with time zone |           | not null | 
 completed_at             | timestamp with time zone |           |          | 
 mode                     | text                     |           | not null | 'audit_only'::text
 journal_source           | text                     |           |          | 
 db_open_count            | integer                  |           | not null | 0
 journal_open_count       | integer                  |           | not null | 0
 matched_count            | integer                  |           | not null | 0
 mismatch_count           | integer                  |           | not null | 0
 duplicate_count          | integer                  |           | not null | 0
 mirror_account_count     | integer                  |           | not null | 0
 missing_identifier_count | integer                  |           | not null | 0
 status                   | text                     |           | not null | 'unknown'::text
 payload                  | jsonb                    |           |          | 
 created_at               | timestamp with time zone |           | not null | now()
Indexes:
    "atm_position_reconciliation_runs_pkey" PRIMARY KEY, btree (id)
    "atm_position_reconciliation_runs_run_id_key" UNIQUE CONSTRAINT, btree (run_id)
    "idx_atm_pos_recon_runs_started_at" btree (started_at DESC)
    "idx_atm_pos_recon_runs_status" btree (status)
Referenced by:
    TABLE "atm_position_reconciliation_items" CONSTRAINT "atm_position_reconciliation_items_run_id_fkey" FOREIGN KEY (run_id) REFERENCES atm_position_reconciliation_runs(run_id) ON DELETE CASCADE

```

## atm_position_reconciliation_items
Rows: 3
```
                                           Table "public.atm_position_reconciliation_items"
       Column       |           Type           | Collation | Nullable |                            Default                            
--------------------+--------------------------+-----------+----------+---------------------------------------------------------------
 id                 | bigint                   |           | not null | nextval('atm_position_reconciliation_items_id_seq'::regclass)
 run_id             | text                     |           | not null | 
 paper_trade_id     | bigint                   |           |          | 
 lifecycle_id       | text                     |           |          | 
 symbol             | text                     |           |          | 
 strategy_id        | text                     |           |          | 
 account            | text                     |           |          | 
 broker_order_id    | text                     |           |          | 
 journal_match_key  | text                     |           |          | 
 classification     | text                     |           | not null | 
 severity           | text                     |           | not null | 'info'::text
 reason             | text                     |           |          | 
 recommended_action | text                     |           |          | 
 payload            | jsonb                    |           |          | 
 created_at         | timestamp with time zone |           | not null | now()
Indexes:
    "atm_position_reconciliation_items_pkey" PRIMARY KEY, btree (id)
    "idx_atm_pos_recon_items_classification" btree (classification)
    "idx_atm_pos_recon_items_run_id" btree (run_id)
    "idx_atm_pos_recon_items_severity" btree (severity)
    "idx_atm_pos_recon_items_symbol" btree (symbol)
Foreign-key constraints:
    "atm_position_reconciliation_items_run_id_fkey" FOREIGN KEY (run_id) REFERENCES atm_position_reconciliation_runs(run_id) ON DELETE CASCADE

```

## atm_overdue_position_decisions
Rows: 12
```
                                              Table "public.atm_overdue_position_decisions"
          Column          |           Type           | Collation | Nullable |                          Default                           
--------------------------+--------------------------+-----------+----------+------------------------------------------------------------
 id                       | bigint                   |           | not null | nextval('atm_overdue_position_decisions_id_seq'::regclass)
 decision_id              | text                     |           | not null | 
 created_at               | timestamp with time zone |           | not null | now()
 updated_at               | timestamp with time zone |           | not null | now()
 operator                 | text                     |           |          | 'john'::text
 lifecycle_id             | text                     |           |          | 
 paper_trade_id           | bigint                   |           |          | 
 symbol                   | text                     |           | not null | 
 strategy_id              | text                     |           |          | 
 strategy_family          | text                     |           |          | 
 days_held                | numeric                  |           |          | 
 time_stop_status         | text                     |           |          | 
 stop_missing             | boolean                  |           |          | false
 broker_stop_proof_status | text                     |           |          | 
 decision                 | text                     |           | not null | 
 decision_reason          | text                     |           |          | 
 operator_note            | text                     |           |          | 
 status                   | text                     |           | not null | 'recorded'::text
 source_page              | text                     |           |          | 'atm-control-room'::text
 payload                  | jsonb                    |           |          | 
Indexes:
    "atm_overdue_position_decisions_pkey" PRIMARY KEY, btree (id)
    "atm_overdue_position_decisions_decision_id_key" UNIQUE CONSTRAINT, btree (decision_id)
    "idx_aopd_created" btree (created_at DESC)
    "idx_aopd_lc" btree (lifecycle_id)
    "idx_aopd_status" btree (status)
    "idx_aopd_sym" btree (symbol)
    "idx_aopd_trade" btree (paper_trade_id)

```

## atm_manual_close_review_decisions
Rows: 1
```
                                         Table "public.atm_manual_close_review_decisions"
     Column      |           Type           | Collation | Nullable |                            Default                            
-----------------+--------------------------+-----------+----------+---------------------------------------------------------------
 id              | bigint                   |           | not null | nextval('atm_manual_close_review_decisions_id_seq'::regclass)
 review_id       | text                     |           | not null | 
 created_at      | timestamp with time zone |           |          | now()
 updated_at      | timestamp with time zone |           |          | now()
 operator        | text                     |           |          | 'john'::text
 lifecycle_id    | text                     |           |          | 
 paper_trade_id  | bigint                   |           |          | 
 symbol          | text                     |           | not null | 
 strategy_id     | text                     |           |          | 
 decision        | text                     |           | not null | 
 decision_reason | text                     |           |          | 
 operator_note   | text                     |           |          | 
 status          | text                     |           |          | 'recorded'::text
 payload         | jsonb                    |           |          | 
Indexes:
    "atm_manual_close_review_decisions_pkey" PRIMARY KEY, btree (id)
    "atm_manual_close_review_decisions_review_id_key" UNIQUE CONSTRAINT, btree (review_id)
    "idx_amcr_status" btree (status)
    "idx_amcr_sym" btree (symbol)
    "idx_amcr_trade" btree (paper_trade_id)

```

## atm_close_previews
Rows: 0
```
                                            Table "public.atm_close_previews"
        Column        |           Type           | Collation | Nullable |                    Default                     
----------------------+--------------------------+-----------+----------+------------------------------------------------
 id                   | bigint                   |           | not null | nextval('atm_close_previews_id_seq'::regclass)
 close_preview_id     | text                     |           | not null | 
 created_at           | timestamp with time zone |           |          | now()
 operator             | text                     |           |          | 'john'::text
 lifecycle_id         | text                     |           |          | 
 paper_trade_id       | bigint                   |           | not null | 
 symbol               | text                     |           | not null | 
 strategy_id          | text                     |           |          | 
 account              | text                     |           |          | 
 side                 | text                     |           |          | 'sell'::text
 quantity             | numeric                  |           |          | 
 entry_price          | numeric                  |           |          | 
 current_price        | numeric                  |           |          | 
 estimated_exit_price | numeric                  |           |          | 
 estimated_pnl        | numeric                  |           |          | 
 estimated_pnl_pct    | numeric                  |           |          | 
 db_stop              | numeric                  |           |          | 
 stop_implication     | text                     |           |          | 
 time_stop_status     | text                     |           |          | 
 close_reason         | text                     |           |          | 
 status               | text                     |           |          | 'preview_created'::text
 payload              | jsonb                    |           |          | 
Indexes:
    "atm_close_previews_pkey" PRIMARY KEY, btree (id)
    "atm_close_previews_close_preview_id_key" UNIQUE CONSTRAINT, btree (close_preview_id)
    "idx_acp_trade" btree (paper_trade_id)

```

## atm_close_actions
Rows: 4
```
                                           Table "public.atm_close_actions"
       Column        |           Type           | Collation | Nullable |                    Default                    
---------------------+--------------------------+-----------+----------+-----------------------------------------------
 id                  | bigint                   |           | not null | nextval('atm_close_actions_id_seq'::regclass)
 close_action_id     | text                     |           | not null | 
 created_at          | timestamp with time zone |           |          | now()
 operator            | text                     |           |          | 'john'::text
 close_preview_id    | text                     |           |          | 
 lifecycle_id        | text                     |           |          | 
 paper_trade_id      | bigint                   |           | not null | 
 symbol              | text                     |           | not null | 
 action              | text                     |           | not null | 
 action_status       | text                     |           | not null | 'recorded'::text
 safety_confirmation | text                     |           |          | 
 broker_order_id     | text                     |           |          | 
 error               | text                     |           |          | 
 payload             | jsonb                    |           |          | 
Indexes:
    "atm_close_actions_pkey" PRIMARY KEY, btree (id)
    "atm_close_actions_close_action_id_key" UNIQUE CONSTRAINT, btree (close_action_id)
    "idx_aca_trade" btree (paper_trade_id)

```

## lifecycle_events
Rows: 239
```
                                            Table "public.lifecycle_events"
        Column        |           Type           | Collation | Nullable |                   Default                    
----------------------+--------------------------+-----------+----------+----------------------------------------------
 id                   | bigint                   |           | not null | nextval('lifecycle_events_id_seq'::regclass)
 lifecycle_id         | text                     |           | not null | 
 event_ts             | timestamp with time zone |           | not null | now()
 stage                | text                     |           | not null | 
 event_type           | text                     |           | not null | 
 status               | text                     |           |          | 
 symbol               | text                     |           |          | 
 strategy_id          | text                     |           |          | 
 strategy_family      | text                     |           |          | 
 candidate_id         | text                     |           |          | 
 signal_id            | text                     |           |          | 
 proposal_id          | text                     |           |          | 
 decision_id          | text                     |           |          | 
 paper_trade_id       | bigint                   |           |          | 
 paper_order_id       | text                     |           |          | 
 broker_order_id      | text                     |           |          | 
 stop_order_id        | text                     |           |          | 
 execution_quality_id | bigint                   |           |          | 
 journal_id           | text                     |           |          | 
 backtest_id          | text                     |           |          | 
 agent_owner          | text                     |           |          | 
 raci_responsible     | text                     |           |          | 
 raci_accountable     | text                     |           |          | 
 source_script        | text                     |           |          | 
 source_table         | text                     |           |          | 
 source_pk            | text                     |           |          | 
 payload              | jsonb                    |           |          | 
 created_at           | timestamp with time zone |           |          | now()
Indexes:
    "lifecycle_events_pkey" PRIMARY KEY, btree (id)
    "idx_le_event_ts" btree (event_ts DESC)
    "idx_le_lifecycle_id" btree (lifecycle_id)
```

## trade_lesson_memory
Rows: 10
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

## strategy_lesson_rollup
Rows: 6
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

## system_health_checks
Rows: 2249
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

## system_health_events
Rows: 1089
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

## pipeline_schedule
Rows: 13
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

## accounts
Rows: 5
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

