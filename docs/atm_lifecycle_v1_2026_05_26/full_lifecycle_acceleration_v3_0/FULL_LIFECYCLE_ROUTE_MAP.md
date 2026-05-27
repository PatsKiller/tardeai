# Full Lifecycle Route Map

## Frontend Routes (82)

- /v2/*
- /v2/actions
- /v2/agent-calibration
- /v2/agent-collaboration
- /v2/agent-dashboard/:agentId
- /v2/agent-pipeline
- /v2/ai-analyst
- /v2/alerts
- /v2/approvals
- /v2/atm-control-room
- /v2/attribution
- /v2/automated-journal
- /v2/automated-trade-mode
- /v2/backtesting
- /v2/bot-morning-brief
- /v2/broker-recon
- /v2/broker-reconciliation
- /v2/cio
- /v2/command
- /v2/content-health
- /v2/correlation
- /v2/dividends
- /v2/execution-quality
- /v2/forecast
- /v2/governance
- /v2/hub
- /v2/inbox
- /v2/incubator
- /v2/intelligence
- /v2/intelligence-entities
- /v2/intelligence-sources
- /v2/intelligence-whiteboard
- /v2/journal
- /v2/journal-analytics
- /v2/journal-reports
- /v2/learning-governance
- /v2/live-governance
- /v2/morning-brief
- /v2/notifications
- /v2/ops
- /v2/orchestration
- /v2/overnight
- /v2/paper-governance
- /v2/paper-journal
- /v2/paper-outcomes
- /v2/paper-proposals
- /v2/paper-review
- /v2/paper-status
- /v2/paper-trade-intelligence
- /v2/pipeline
- /v2/pipeline-controller
- /v2/pipeline-health-master
- /v2/plan-vs-performance
- /v2/portfolio
- /v2/portfolio-intelligence
- /v2/portfolio-monitor
- /v2/proposal-alerts
- /v2/proposals
- /v2/prospects
- /v2/rebalance
- /v2/recovery
- /v2/reports
- /v2/research
- /v2/research-topics
- /v2/retirement
- /v2/returns
- /v2/risk
- /v2/risk-regime
- /v2/self-improvement
- /v2/strategy
- /v2/strategy-admin
- /v2/strategy-analytics
- /v2/strategy-desk
- /v2/system-health
- /v2/system-hub
- /v2/tax
- /v2/technical
- /v2/topic-monitor
- /v2/trade-ai
- /v2/watchlist
- /v2/watchlist/:symbol
- /v2/weekly-learning

## API Endpoints (444)

See api_payloads/ for captured samples of key lifecycle endpoints.

### Lifecycle-Critical Endpoints

| Stage | Endpoint | Purpose |
|-------|----------|---------|
| Prospect | /api/v2/trade-ai | Scored ticker candidates |
| Proposal | /api/v2/atm/proposal-hygiene | Classified proposal records |
| Approval | /api/v2/atm/status, /api/v2/atm/decisions | ATM gate state |
| Execution | /api/v2/execution-quality | TCA/slippage |
| Reconciliation | /api/v2/atm/reconciliation-health | DB vs journal match |
| Lifecycle | /api/v2/atm/lifecycle | Full pipeline summary |
| Journal | /api/v2/automated-journal | Broker-confirmed positions |
| System | /api/v2/system-health | Pipeline health |
