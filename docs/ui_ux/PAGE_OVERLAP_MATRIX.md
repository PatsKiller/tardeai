# Page Overlap Matrix — Command Center v12

Status:      ACTIVE
as_of:       2026-05-24T18:56:51-04:00
Measured at: efcc51365 / not measured

## Overlap Groups

| Group | Pages | Decision | Action |
|-------|-------|----------|--------|
| System Health cluster | system-health, pipeline, agent-pipeline | Keep separate, cross-link | Add tabs to System Health for pipeline + agent views |
| Risk/Alert cluster | alerts, risk, command | Keep separate, cross-link | Command links to risk/alerts. Alert badge explained. |
| Research cluster | research-topics, topic-monitor | Merge | Single "Research Intelligence" with tabs |
| Portfolio decision | ai-analyst, technical, risk, rebalance, tax | Keep separate, cross-link | Add navigation links between pages |
| Paper trading | paper-proposals, paper-review, automated-trade-mode | Keep separate | Add workflow flow between pages |
| Learning cluster | weekly-learning, agent-calibration, cio | Keep separate | Weekly Learning stays manual-only, labeled |

## Navigation Consolidation

### Current: 20+ nav items
### Proposed: 11 primary nav items

| Nav Item | Routes | Type |
|----------|--------|------|
| Command | /v2/command | Hub |
| Portfolio | /v2/portfolio, /v2/dividends, /v2/returns, /v2/attribution | Section |
| Risk & Alerts | /v2/risk, /v2/alerts, /v2/risk-regime | Section |
| AI Analyst | /v2/ai-analyst | Page |
| Research | /v2/research-topics, /v2/topic-monitor, /v2/research | Section |
| Pipeline & Health | /v2/pipeline, /v2/system-health, /v2/agent-pipeline | Section |
| Paper Trading | /v2/paper-proposals, /v2/paper-review, /v2/paper-status, /v2/automated-trade-mode | Section |
| Tax & Rebalance | /v2/tax, /v2/rebalance, /v2/retirement | Section |
| Technical | /v2/technical | Page |
| Reports | /v2/reports, /v2/journal | Section |
| Admin | /v2/governance, /v2/strategy-admin, /v2/ops, /v2/self-improvement, /v2/agent-calibration, /v2/weekly-learning | Section |

### Moved to Admin (low-frequency)
- strategy-admin, strategy-analytics, strategy-desk
- agent-calibration, weekly-learning
- self-improvement, ops
- governance, backtesting
- correlation, forecast
- broker-reconciliation, execution-quality
