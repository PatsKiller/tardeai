# Source of Truth Matrix

| Object | Source of Truth | Owner Script | API |
|--------|---------------|-------------|-----|
| Prospect/candidate | strategy_signals | trade_ai_orchestrator.py | /api/v2/trade-ai |
| Signal score | strategy_signals.score | trade_ai_orchestrator.py | /api/v2/trade-ai |
| Proposal | paper_trade_proposals | auto_proposal_generator.py | /api/v2/paper-proposals |
| Approval decision | atm_decision_log | atm_auto_approver.py | /api/v2/atm/decisions |
| Paper order/fill | paper_trades | alpaca_paper_adapter.py | /api/v2/atm/lifecycle |
| Open position (broker) | Alpaca API via automated-journal | portfolio_server.py | /api/v2/automated-journal |
| Open position (DB) | paper_trades WHERE open | lifecycle_event_writer.py | /api/v2/atm/lifecycle |
| Stop price | paper_trades.stop_loss | unified_stop_supervisor.py | /api/v2/atm/lifecycle |
| Trailing tier | strategy_trailing_policy.py (code) | unified_stop_supervisor.py | computed |
| Exit event | paper_trades.exit_* | paper_trade_closer.py | /api/v2/automated-journal |
| Reconciliation | atm_position_reconciliation_runs | atm_position_reconciler.py | /api/v2/atm/reconciliation-health |
| Execution quality | paper_execution_quality | paper_execution_quality_analyzer.py | /api/v2/execution-quality |
| Journal entry | (computed) | portfolio_server.py | /api/v2/automated-journal |
| Lesson/learning | trade_lesson_memory | trade_learning_engine.py | /api/v2/journal/* |
| Lifecycle trace | lifecycle_events | lifecycle_event_writer.py | /api/v2/atm/lifecycle |
