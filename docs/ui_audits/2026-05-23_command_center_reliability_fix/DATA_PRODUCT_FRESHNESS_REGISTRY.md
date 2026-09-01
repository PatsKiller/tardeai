# Data Product Freshness Registry

Status:      HISTORICAL
as_of:       2026-05-24T11:44:41-04:00
Measured at: efcc51365 / not measured

Defines dashboard-critical data products, their expected cadence, staleness thresholds, and operator remediation.

| Product | Owner Script | Schedule | Max Stale (h) | Source | Downstream Pages | Alert Tier |
|---------|-------------|----------|---------------|--------|-----------------|------------|
| current_portfolio_snapshot | portfolio_price_cache.py | daily 7am ET | 24 | holdings.json | Header, Portfolio, Risk, Watchlist, Technical | P0 |
| performance_returns | portfolio_signals.py | daily 7am ET | 48 | performance_history.json | Returns, Attribution | P1 |
| tax_lots | (manual import) | manual | 168 | tax_lots.json | Tax, AI Analyst | P1 |
| dividend_calendar | dividend_tracker.py | daily 7am ET | 48 | dividend_calendar.json | Dividends, Rebalance, Retirement | P1 |
| rebalance_analysis | rebalance_analyzer.py | weekly | 168 | rebalance_analysis_results | Rebalance | P2 |
| ai_analyst_cache | portfolio_ai_analyst.py | daily 7am ET | 48 | ai_analysis_cache.json | AI Analyst | P1 |
| risk_snapshot | risk_manager.py | daily 7am ET | 24 | risk_management.json | Risk, Command | P0 |
| retirement_roadmap | retirement_planner.py | weekly | 168 | retirement_roadmap.json | Retirement | P2 |
| cio_decisions | cio_decision_engine.py | daily 7am ET | 48 | cio_decisions table | CIO | P1 |
| agent_calibration | agent_calibration_engine.py | weekly | 168 | agent_calibration table | Agent Calibration, CIO | P1 |
| topic_monitor | topic_ingestion.py | weekly (manual trigger) | 168 | topic_monitor table | Topic Monitor | P1 |
| incubator_universe | weekly_incubator_builder.py | weekly | 168 | incubator_candidates table | Incubator | P2 |
| paper_proposals | continuous_runner.py | */15 market hours | 4 | paper_trade_proposals table | Paper Proposals, ATM | P1 |
| paper_outcomes | agent_outcome_scorer.py | weekly | 168 | trade_thesis_outcomes table | Paper Outcomes | P2 |
| news_articles | news_ingestion.py | */30 | 6 | news_articles table | Intelligence, Research | P1 |
| screener_results | finviz_screener_runner.py | daily 6:25am ET | 24 | screener_runs table | Prospects, Incubator | P1 |
| watchlist_agent_jobs | process_watchlist_agent_jobs.py | */10-15 | 2 | watchlist_agent_jobs table | Agent Pipeline | P1 |
| weekly_learning | weekly_learning_digest.py | weekly Sunday | 168 | weekly_learning_digests table | Weekly Learning | P2 |
| broker_reconciliation | broker_reconciliation.py | daily | 48 | broker_reconciliation table | Broker Recon | P1 |
| morning_brief | aegis_surveillance.py | daily 8am ET | 24 | aegis_portfolio_briefs table | Morning Brief | P1 |

## Remediation Commands

| Product | Command |
|---------|---------|
| current_portfolio_snapshot | `.venv/bin/python scripts/portfolio_price_cache.py` |
| news_articles | `.venv/bin/python scripts/news_ingestion.py --priority` |
| screener_results | `.venv/bin/python scripts/finviz_screener_runner.py` |
| watchlist_agent_jobs | `.venv/bin/python scripts/process_watchlist_agent_jobs.py --limit 10` |
| topic_monitor | curl POST to `/api/v2/topics/run` |
| ai_analyst_cache | `.venv/bin/python scripts/portfolio_ai_analyst.py` |
| weekly_learning | `.venv/bin/python scripts/weekly_learning_digest.py` |
