# LLM Backtesting Relevant Schema Summary

## paper_trades
Rows: 34
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
```

## lifecycle_trace
Rows: 480
```
                           Table "public.lifecycle_trace"
     Column      |           Type           | Collation | Nullable |    Default     
-----------------+--------------------------+-----------+----------+----------------
 trace_id        | text                     |           | not null | 
 created_at      | timestamp with time zone |           |          | now()
 updated_at      | timestamp with time zone |           |          | now()
 symbol          | text                     |           | not null | 
 strategy_id     | text                     |           |          | 
 strategy_family | text                     |           |          | 
 source_stage    | text                     |           |          | 
 current_stage   | text                     |           |          | 
 source_system   | text                     |           |          | 
 prospect_id     | text                     |           |          | 
 research_id     | text                     |           |          | 
 signal_id       | text                     |           |          | 
 proposal_id     | text                     |           |          | 
 paper_trade_id  | bigint                   |           |          | 
 broker_order_id | text                     |           |          | 
 status          | text                     |           |          | 'active'::text
 confidence      | numeric                  |           |          | 
 score           | numeric                  |           |          | 
 reason          | text                     |           |          | 
 payload         | jsonb                    |           |          | 
Indexes:
    "lifecycle_trace_pkey" PRIMARY KEY, btree (trace_id)
```

## lifecycle_trace_events
Rows: 480
```
                                        Table "public.lifecycle_trace_events"
    Column     |           Type           | Collation | Nullable |                      Default                       
---------------+--------------------------+-----------+----------+----------------------------------------------------
 id            | bigint                   |           | not null | nextval('lifecycle_trace_events_id_seq'::regclass)
 trace_id      | text                     |           |          | 
 event_time    | timestamp with time zone |           |          | now()
 stage         | text                     |           | not null | 
 event_type    | text                     |           | not null | 
 source_script | text                     |           |          | 
 source_table  | text                     |           |          | 
 source_id     | text                     |           |          | 
 status        | text                     |           |          | 
 message       | text                     |           |          | 
 payload       | jsonb                    |           |          | 
Indexes:
    "lifecycle_trace_events_pkey" PRIMARY KEY, btree (id)
    "idx_lte_time" btree (event_time DESC)
    "idx_lte_trace" btree (trace_id)
Foreign-key constraints:
    "lifecycle_trace_events_trace_id_fkey" FOREIGN KEY (trace_id) REFERENCES lifecycle_trace(trace_id)

```

## paper_trade_proposals
Rows: 124
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
```

## proposal_dedup_audit
Rows: 13
```
                                             Table "public.proposal_dedup_audit"
         Column         |           Type           | Collation | Nullable |                     Default                      
------------------------+--------------------------+-----------+----------+--------------------------------------------------
 id                     | bigint                   |           | not null | nextval('proposal_dedup_audit_id_seq'::regclass)
 created_at             | timestamp with time zone |           |          | now()
 duplicate_key          | text                     |           | not null | 
 symbol                 | text                     |           |          | 
 strategy_id            | text                     |           |          | 
 canonical_proposal_id  | text                     |           |          | 
 duplicate_proposal_ids | jsonb                    |           |          | 
 duplicate_count        | integer                  |           |          | 
 recommended_action     | text                     |           |          | 
 payload                | jsonb                    |           |          | 
Indexes:
    "proposal_dedup_audit_pkey" PRIMARY KEY, btree (id)
    "idx_pda_key" btree (duplicate_key)

```

## paper_execution_quality
Rows: 13
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
```

## lifecycle_events
Rows: 245
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
```

## Tables NOT yet created (v3.8 design)
- trade_llm_reviews: NEW
- monthly_llm_meta_reviews: NEW

lifecycle_events can temporarily hold LLM review status using stage='llm_review'
