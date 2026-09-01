# Trade AI Command Center v2 -- Full Route Map

Status:      HISTORICAL
as_of:       2026-05-25T10:45:00-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-25 (Memorial Day)
Source: `apps/command-center-v2/src/App.tsx` + `components/Shell.tsx`
Baseline commit: `8e938dca`

---

## Primary Routes (47 active)

| # | Route Path | Component | Nav Group | Purpose |
|---|-----------|-----------|-----------|---------|
| 1 | `/v2/` (index) | Overview | -- (home) | Dashboard overview: portfolio value, journal P&L, risk, intel, recovery |
| 2 | `/v2/command` | Command | Command | Morning Command -- aggregated daily decision center |
| 3 | `/v2/morning-brief` | MorningBrief | Command | AI-powered Aegis morning brief with chat |
| 4 | `/v2/bot-morning-brief` | MorningBriefBot | -- (unlisted) | Alternate morning brief format |
| 5 | `/v2/inbox` | Inbox (hub) | Command | Consolidated: AlertsActions + Notifications + ActionCenter |
| 6 | `/v2/portfolio` | PortfolioCommand (hub) | Portfolio | Consolidated: Holdings + Health/Risk + Intelligence |
| 7 | `/v2/dividends` | Dividends | Portfolio | Dividend income tracker |
| 8 | `/v2/returns` | Returns | Portfolio | Performance/returns dashboard |
| 9 | `/v2/attribution` | Attribution | Portfolio | Return attribution analysis |
| 10 | `/v2/tax` | TaxLots | Tax & Rebalance | Tax lot viewer |
| 11 | `/v2/rebalance` | Rebalance | Tax & Rebalance | Rebalance planner |
| 12 | `/v2/retirement` | Retirement | Tax & Rebalance | Retirement planning (Roth, SSDI, IRMAA) |
| 13 | `/v2/trade-ai` | TradeAI | Admin | Trade AI Live -- screener signals, VIX, market regime |
| 14 | `/v2/prospects` | Prospects | Admin | Prospect discovery: scalp/swing/income candidates |
| 15 | `/v2/strategy-desk` | StrategyDesk | Admin | Strategy desk overview |
| 16 | `/v2/paper-status` | PaperStatus | Paper Trading | Open paper trades + LLM status |
| 17 | `/v2/paper-proposals` | PaperProposals | Paper Trading | Paper trade proposal pipeline |
| 18 | `/v2/proposal-alerts` | ProposalAlerts | Admin | Proposal alert config |
| 19 | `/v2/incubator` | Incubator | Paper Trading | Multi-strategy incubator |
| 20 | `/v2/execution-quality` | ExecutionQuality | Admin | TCA / execution quality metrics |
| 21 | `/v2/broker-reconciliation` | BrokerReconciliation | Admin | Broker recon checks |
| 22 | `/v2/paper-review` | PaperReview (hub) | Paper Trading | Consolidated: PaperOutcomes + PaperTradeIntelligence |
| 23 | `/v2/plan-vs-performance` | PlanVsPerformance | Admin | Strategy plan vs actual performance |
| 24 | `/v2/strategy-admin` | StrategyAdmin | Admin | Strategy config editor |
| 25 | `/v2/strategy-analytics` | StrategyAnalytics | Admin | Strategy analytics dashboard |
| 26 | `/v2/technical` | Technical | AI Analyst | Technical analysis / Portfolio Intelligence |
| 27 | `/v2/risk` | Risk | Risk & Alerts | Risk dashboard |
| 28 | `/v2/risk-regime` | RiskRegime | Risk & Alerts | VIX regime + strategy rotation |
| 29 | `/v2/research` | Research | Research | Ticker-level research (RAG-backed) |
| 30 | `/v2/watchlist` | Watchlist | AI Analyst | Watchlist with agent analysis |
| 31 | `/v2/watchlist/:symbol` | WatchlistSymbolPage | -- (deep link) | Per-symbol watchlist detail |
| 32 | `/v2/cio` | CIODashboard | AI Analyst | CIO-level decisions and strategy rotations |
| 33 | `/v2/recovery` | StoppedOutWatch | Risk & Alerts | Stopped-out recovery watch |
| 34 | `/v2/journal` | JournalHub (hub) | Reports | Consolidated: Journal + Analytics + Reports + Automated |
| 35 | `/v2/overnight` | OvernightDashboard | Research | Overnight intelligence brief |
| 36 | `/v2/intelligence` | IntelligenceHub (hub) | Research | Consolidated: Sources + Entities + Whiteboard + ContentHealth |
| 37 | `/v2/topic-monitor` | TopicMonitor | Research | Topic/theme monitoring |
| 38 | `/v2/research-topics` | ResearchTopics | Research | Research intelligence topics |
| 39 | `/v2/ai-analyst` | AIAnalyst | AI Analyst | AI advisory with reports |
| 40 | `/v2/agent-pipeline` | AgentPipeline | Pipeline & Health | Agent pipeline activity feed |
| 41 | `/v2/agent-calibration` | AgentCalibration | Admin | Agent weight calibration |
| 42 | `/v2/agent-collaboration` | AgentCollaboration | Pipeline & Health | Multi-agent collaboration view |
| 43 | `/v2/agent-dashboard/:agentId` | AgentDashboard | -- (deep link) | Per-agent detail dashboard |
| 44 | `/v2/pipeline` | PipelineHub (hub) | Pipeline & Health | Consolidated: PipelineHealthMaster + PipelineController |
| 45 | `/v2/weekly-learning` | WeeklyLearning | Admin | Weekly learning digest + thesis reviews |
| 46 | `/v2/backtesting` | Backtesting | Admin | Backtesting engine |
| 47 | `/v2/self-improvement` | SelfImprovement | Admin | Self-improvement command center |
| 48 | `/v2/automated-trade-mode` | AutomatedTradeMode | Paper Trading | ATM (automated trade mode) |
| 49 | `/v2/governance` | GovernanceHub (hub) | Admin | Consolidated: PaperGovernance + LearningGovernance + Approvals |
| 50 | `/v2/alerts` | AlertsDashboard | Risk & Alerts | Alert dashboard |
| 51 | `/v2/ops` | OpsHub (hub) | Admin | Consolidated: SystemHub + Ops + LLMQueue + Orchestration |
| 52 | `/v2/system-health` | SystemHealth | Pipeline & Health | System health + screener status |
| 53 | `/v2/reports` | Reports | Reports | Reports hub |
| 54 | `/v2/correlation` | Correlation | Admin | Correlation matrix |
| 55 | `/v2/forecast` | Forecast | Admin | ML/quant forecast |

## Legacy Redirects (17)

| Old Route | Redirects To | Type |
|-----------|-------------|------|
| `/v2/portfolio-monitor` | PortfolioCommand (same component) | render |
| `/v2/portfolio-intelligence` | PortfolioCommand (same component) | render |
| `/v2/journal-analytics` | `/journal?tab=analytics` | Navigate |
| `/v2/journal-reports` | `/journal?tab=reports` | Navigate |
| `/v2/paper-journal` | `/journal` | Navigate |
| `/v2/paper-outcomes` | `/paper-review` | Navigate |
| `/v2/paper-trade-intelligence` | PaperReview (same component) | render |
| `/v2/pipeline-health-master` | PipelineHub (same component) | render |
| `/v2/pipeline-controller` | PipelineHub (same component) | render |
| `/v2/alerts` (duplicate) | Inbox (same component) | render |
| `/v2/notifications` | Inbox (same component) | render |
| `/v2/actions` | Inbox (same component) | render |
| `/v2/paper-governance` | `/governance` | Navigate |
| `/v2/learning-governance` | `/governance?tab=learning` | Navigate |
| `/v2/approvals` | `/governance` | Navigate |
| `/v2/broker-recon` | `/broker-reconciliation` | Navigate |
| `/v2/system-hub` | `/ops` | Navigate |
| `/v2/hub` | OpsHub (same component) | render |
| `/v2/orchestration` | OpsHub (same component) | render |
| `/v2/intelligence-sources` | IntelligenceHub (same component) | render |
| `/v2/intelligence-entities` | IntelligenceHub (same component) | render |
| `/v2/intelligence-whiteboard` | IntelligenceHub (same component) | render |
| `/v2/content-health` | `/intelligence?tab=content-health` | Navigate |
| `/v2/live-governance` | GovernanceHub (same component) | render |
| `/v2/proposals` | `/paper-proposals` | Navigate |
| `/v2/strategy` | `/strategy-desk` | Navigate |

## Nav Groups (Shell.tsx NAV_GROUPS)

| Group | Items |
|-------|-------|
| **Command** (3) | Morning Command, Inbox, Daily Brief |
| **Portfolio** (4) | Holdings, Dividends, Returns, Attribution |
| **Risk & Alerts** (4) | Risk Dashboard, Alert Dashboard, Risk Regime, Recovery Watch |
| **AI Analyst** (4) | AI Advisory, Technical/PI, Watchlist, CIO Dashboard |
| **Research** (5) | Research Intelligence, Topic Monitor, Ticker Research, Intelligence Hub, Overnight Brief |
| **Pipeline & Health** (4) | System Health, Pipeline Stages, Agent Pipeline, Agent Collaboration |
| **Paper Trading** (5) | Proposals, Paper Review, Paper Status, ATM Mode, Incubator |
| **Tax & Rebalance** (3) | Tax & Lots, Rebalance, Retirement |
| **Reports** (3) | Reports Hub, Trade Journal, Journal Reports |
| **Admin** (17) | Governance, Strategy Admin, Analytics, Agent Calibration, Weekly Learning, Operations, Self-Improvement, Backtesting, Trade AI Live, Prospects, Strategy Desk, Correlation, Forecast, Broker Recon, Execution Quality, Plan vs Perf, Proposal Alerts, Approvals |

**Total nav items: 52**
**Total unique active routes: 55**
**Total legacy redirects: ~25**

## Hub/Consolidated Pages

| Hub | Sub-pages (tabs) |
|-----|-----------------|
| PortfolioCommand | Portfolio, PortfolioMonitor, PortfolioIntelligence |
| Inbox | AlertsActions, Notifications, ActionCenter |
| JournalHub | Journal, JournalAnalytics, JournalReports, AutomatedTradeJournal |
| IntelligenceHub | IntelligenceSources, IntelligenceEntities, IntelligenceWhiteboard, ContentHealth |
| PipelineHub | PipelineHealthMaster, PipelineController |
| GovernanceHub | PaperGovernance, LearningGovernance, Approvals |
| OpsHub | SystemHub, Ops, LLMQueue, Orchestration |
| PaperReview | PaperOutcomes, PaperTradeIntelligence |

## Notes
- `/v2/alerts` is defined TWICE: once as AlertsDashboard (line 187) and once as Inbox redirect (line 206). React Router will match the first one.
- `/v2/bot-morning-brief` is not in any nav group -- orphaned route.
- Admin group has 17 items -- the largest group; acts as a catch-all.
- `/v2/journal-reports` is in Reports nav but redirects to JournalHub with tab param.
