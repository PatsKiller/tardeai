# B-1E New Pages Menu Placement Matrix

## Current Menu (8 groups, 48 items)

| Group | Count | Pages |
|-------|-------|-------|
| Home | 4 | Overview, Command, Daily Brief, Inbox |
| Portfolio | 6 | Portfolio Command, Dividends, Returns, Attribution, Tax & Lots, Rebalance |
| Trading | 10 | Trade AI, Prospects, Strategy Desk, Paper Proposals, Paper Status, Paper Review, Plan vs Performance, Execution Quality, Broker Recon, Incubator |
| Strategy | 7 | Watchlist, CIO Dashboard, Recovery Watch, Risk, Risk Regime, Technical, Research |
| Retirement | 3 | Retirement, AI Analyst, Reports |
| Journal | 1 | Trade Journal |
| Intelligence | 6 | Overnight Brief, Intelligence Hub, Topic Monitor, Research Topics, Agent Pipeline, Agent Calibration |
| System | 11 | Alert Dashboard, Operations, Pipeline, Governance, System Health, Strategy Admin, Strategy Analytics, Bot Morning Brief, Weekly Learning, Self-Improvement, Backtesting |

## Orphan Pages (Route exists, no nav entry)

| Route | Page Component | Proposed Tab | Proposed Label | Priority |
|-------|---------------|-------------|----------------|----------|
| /approvals | Approvals.tsx | Trading | Approvals | Medium |
| /paper-journal | PaperJournal.tsx | Journal | Paper Journal | Medium |
| /paper-outcomes | PaperOutcomes.tsx | Journal | Paper Outcomes | Medium |
| /paper-trade-intelligence | PaperTradeIntelligence.tsx | Trading | Paper Intel | Low |
| /paper-governance | PaperGovernance.tsx | System | Paper Governance | Medium |
| /journal-reports | JournalReports.tsx | Journal | Journal Reports | Medium |
| /journal-analytics | JournalAnalytics.tsx | Journal | Journal Analytics | Low |
| /intelligence-sources | IntelligenceSources.tsx | Intelligence | Sources | Low |
| /intelligence-entities | IntelligenceEntities.tsx | Intelligence | Entities | Low |
| /intelligence-whiteboard | IntelligenceWhiteboard.tsx | Intelligence | Whiteboard | Low |
| /portfolio-intelligence | PortfolioIntelligence.tsx | Portfolio | Portfolio Intel | Low |
| /portfolio-monitor | PortfolioMonitor.tsx | Portfolio | Monitor | Low |
| /pipeline-health-master | PipelineHealthMaster.tsx | System | Pipeline Health | Low |
| /pipeline-controller | PipelineController.tsx | System | Pipeline Controller | Low |
| /content-health | ContentHealth.tsx | System | Content Health | Low |
| /live-governance | LiveGovernance.tsx | no_menu | Deferred — live not enabled | N/A |
| /learning-governance | LearningGovernance.tsx | System | Learning Governance | Low |
| /notifications | Notifications.tsx | no_menu | Integrated in header | N/A |
| /orchestration | Orchestration.tsx | System | Orchestration | Low |
| /correlation | Correlation.tsx | Strategy | Correlation | Low |
| /forecast | Forecast.tsx | Strategy | Forecast | Low |

## Recommended Nav Additions (High Priority)

### Trading Tab — add:
- Approvals (/approvals)

### Journal Tab — add:
- Paper Journal (/paper-journal)
- Paper Outcomes (/paper-outcomes)
- Journal Reports (/journal-reports)

### System Tab — add:
- Paper Governance (/paper-governance)

### No Menu (by design):
- /live-governance — live trading not enabled
- /notifications — header integration
- /hub, /strategy, /proposals — redirect routes

## Bucket 3 Status

12 LONG_CYCLE strategies already have freshness configs. No frontend migration needed.
These strategies are POSITION/compounder types. They use the existing Watchlist,
Portfolio, and Strategy pages. No new pages required for Bucket 3.
