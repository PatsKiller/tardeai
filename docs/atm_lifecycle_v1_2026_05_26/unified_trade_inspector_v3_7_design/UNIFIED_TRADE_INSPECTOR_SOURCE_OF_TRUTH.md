# Inspector Tab → Source Mapping

| Tab | Source Endpoint | Source Table |
|-----|----------------|-------------|
| Overview | trade-case-study | paper_trades + lifecycle_trace |
| Source/Prospect | trace-summary | lifecycle_trace (signal stage) |
| Proposal | proposal-hygiene + proposal-dedup | paper_trade_proposals |
| Risk/Approval | lifecycle (gate_audit) | atm_decision_log |
| Execution | execution-timing-health | paper_trades + paper_execution_quality |
| Stops | stop-proof + stop-trailing-control + stop-change-audit | paper_trades + lifecycle_events |
| Reconciliation | reconciliation-health | atm_position_reconciliation_runs/items |
| Journal | journal-learning-summary | paper_trades (computed) |
| Learning | journal-learning-summary | trade_lesson_memory |
| Backtest | paper-vs-backtest (future) | backtest tables |
| Data Quality | aggregated gaps from all sources | computed |
| Raw | all source payloads | JSON dump |
