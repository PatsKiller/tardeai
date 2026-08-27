# Journal/Backtest Source of Truth

| Object | Source Table | Owner Script | API |
|--------|------------|-------------|-----|
| Paper trade | paper_trades | alpaca_paper_adapter.py | /api/v2/automated-journal |
| Closed trade | paper_trades (exit_*) | paper_trade_closer.py | /api/v2/automated-journal |
| Journal entry | computed from paper_trades | portfolio_server.py | /api/v2/automated-journal |
| Execution quality | paper_execution_quality | paper_execution_quality_analyzer.py | /api/v2/execution-quality |
| TCA timing | paper_trades.order_submitted_at/filled_at | v3.3/v3.4 | /api/v2/atm/execution-timing-health |
| Stop-change audit | lifecycle_events stage=stop_change | v3.5 | /api/v2/atm/stop-change-audit |
| Lifecycle trace | lifecycle_trace | lifecycle_trace.py | /api/v2/lifecycle/trace-summary |
| Proposal | paper_trade_proposals | auto_proposal_generator.py | /api/v2/atm/proposal-hygiene |
| Missed proposal | paper_trade_proposals (no trade) | computed | (new v3.6) |
| Backtest run | backtest tables | enterprise_backtester.py | (backtest page) |
| Learning item | trade_lesson_memory | trade_learning_engine.py | /api/v2/journal/* |
| Strategy perf | strategy_lesson_rollup | strategy_weekly_review.py | /api/v2/journal/* |
