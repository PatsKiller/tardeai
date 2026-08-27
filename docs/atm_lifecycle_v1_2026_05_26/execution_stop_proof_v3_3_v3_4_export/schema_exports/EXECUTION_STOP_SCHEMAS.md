# Execution / Stop Proof Schema Export
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
 max_adverse_excursion           | numeric                  |           |          | 
 max_favorable_excursion         | numeric                  |           |          | 
 outcome_verdict                 | text                     |           |          | 
 status                          | text                     |           |          | 'open'::text
 logged_by                       | text                     |           |          | 'system'::text
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
 packet_completion_pct_at_submit | numeric                  |           |          | 
 data_quality_grade              | text                     |           |          | 
Indexes:
    "paper_execution_quality_pkey" PRIMARY KEY, btree (id)
    "idx_peq_trade_created" btree (paper_trade_id, created_at DESC)
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
 final_entry                      | numeric                  |           |          | 
 final_stop                       | numeric                  |           |          | 
 final_target1                    | numeric                  |           |          | 
 final_shares                     | integer                  |           |          | 
 final_dollar_risk                | numeric                  |           |          | 
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

