# Full Lifecycle Data Flow

```
Finviz/News/Social → screener_runner → strategy_signals
                                           ↓
                    orchestrator scoring → scored tickers → trade-ai page
                                           ↓
                    auto_proposal_generator → paper_trade_proposals
                                           ↓
                    atm_auto_approver → atm_decision_log (approve/reject/defer)
                                           ↓
                    proposal_paper_submitter → alpaca_paper_adapter → paper_trades (order)
                                           ↓
                    alpaca fill → paper_trades.entry_price/shares (fill)
                                           ↓
                    unified_stop_supervisor → stop_loss updates (every 3 min)
                    strategy_trailing_policy → trailing tier adjustments
                                           ↓
                    atm_position_reconciler → reconciliation_runs/items (audit every 15 min)
                                           ↓
                    paper_execution_quality_analyzer → paper_execution_quality (TCA at EOD)
                                           ↓
                    stop_hit / target_hit / manual close → paper_trades.exit_*
                                           ↓
                    automated-journal endpoint → journal view (3 open, 14 closed)
                                           ↓
                    trade_learning_engine → trade_lesson_memory / strategy_lesson_rollup
                                           ↓
                    feedback_loop_processor → agent calibration
```

## Key Tables per Stage

| Stage | Primary Table | Secondary |
|-------|--------------|-----------|
| Prospect | strategy_signals | finviz_screener_results |
| Proposal | paper_trade_proposals | — |
| Approval | atm_decision_log | — |
| Execution | paper_trades | — |
| Stop/Trailing | paper_trades.stop_loss | — |
| Reconciliation | atm_position_reconciliation_runs/items | — |
| TCA | paper_execution_quality | — |
| Exit | paper_trades.exit_* | — |
| Journal | (computed from paper_trades) | — |
| Learning | trade_lesson_memory | strategy_lesson_rollup |
| Lifecycle | lifecycle_events | — |
