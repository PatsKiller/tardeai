# Trade AI Command Center -- Architecture Blueprint v1

Status:      HISTORICAL
as_of:       2026-05-25T11:12:43-04:00
Measured at: efcc51365 / not measured

## Mental Model
- **Decide** -- Command, Agent Collaboration, Inbox, Daily Brief
- **Trade** -- Trade AI, Prospects, Strategy Desk, Incubator, ATM Mode
- **Monitor** -- Portfolio (Holdings, Dividends, Returns, Attribution)
- **Protect** -- Risk, Alerts, Risk Regime, Recovery Watch
- **Advise** -- AI Analyst, Technical, Watchlist, CIO Dashboard
- **Research** -- Research Topics, Topic Monitor, Intelligence Hub, Overnight Brief
- **Automate** -- Ops, Pipeline, System Health, Agent Pipeline
- **Execute** -- Paper Proposals, Paper Review, Paper Status, Execution Quality
- **Optimize** -- Tax, Rebalance, Retirement
- **Learn** -- Self-Improvement, Agent Calibration, Weekly Learning
- **Govern** -- Governance, Strategy Admin, low-frequency config
- **Report** -- Reports Hub, Trade Journal, Journal Analytics, Backtesting

## Navigation Architecture (proposed)

### Command
- Command Center (landing)
- Agent Collaboration
- Inbox
- Daily Brief

### Trading (NEW -- extracted from Admin)
- Trade AI (parent)
- Prospects (tab or adjacent)
- Strategy Desk
- Incubator
- ATM Mode

### Portfolio
- Holdings
- Dividends
- Returns
- Attribution

### Risk & Alerts
- Risk Dashboard
- Alert Dashboard
- Risk Regime
- Recovery Watch

### AI Analyst
- AI Advisory
- Technical / PI
- Watchlist
- CIO Dashboard

### Research
- Research Intelligence
- Topic Monitor
- Ticker Research
- Intelligence Hub
- Overnight Brief

### System & Pipeline
- Ops Center (operations overview)
- Pipeline Stages
- System Health
- Agent Pipeline

### Paper Trading
- Proposals
- Paper Review
- Paper Status
- Execution Quality

### Tax & Rebalance
- Tax & Lots
- Rebalance
- Retirement

### Learning & Improvement (NOT in Admin)
- Self-Improvement (preserve -- good page)
- Agent Calibration
- Weekly Learning

### Governance & Admin (reduced)
- Governance Hub
- Strategy Admin
- Forecast
- Correlation
- Broker Recon
- Plan vs Performance

### Reports
- Reports Hub
- Trade Journal
- Journal Analytics
- Backtesting

## Key Decisions

1. Trade AI and Prospects move OUT of Admin into Trading
2. Self-Improvement stays prominent in Learning & Improvement, NOT buried in Admin
3. Admin reduced from 17 items to ~6
4. Ops/Pipeline/SystemHealth/AgentPipeline clarified as System & Pipeline family
5. Governance focuses on policy/rules; paper analytics move to Paper Trading
6. Agent Collaboration stays in Command (decision operations)

## Route Changes

| Current | Proposed | Action |
|---------|----------|--------|
| /v2/trade-ai (Admin) | /v2/trade-ai (Trading) | Move nav group |
| /v2/prospects (Admin) | /v2/prospects (Trading) | Move nav group |
| /v2/strategy-desk (Admin) | /v2/strategy-desk (Trading) | Move nav group |
| /v2/self-improvement (Admin) | /v2/self-improvement (Learning) | Move nav group |
| /v2/agent-calibration (Admin) | /v2/agent-calibration (Learning) | Move nav group |
| /v2/weekly-learning (Admin) | /v2/weekly-learning (Learning) | Move nav group |
| /v2/backtesting (Admin) | /v2/backtesting (Reports) | Move nav group |
| /v2/alerts (duplicate) | Remove dead route | Bug fix |

## Implementation Phases

### Phase 0: Route Cleanup
- Remove duplicate /v2/alerts route
- Capture screenshots
- Update manifest/Drive sync

### Phase 1: Navigation Restructure
- Add Trading group
- Add Learning & Improvement group
- Reduce Admin
- Move pages between groups
- Keep all routes working (no URL changes)

### Phase 2: Hub Consolidation
- Trade AI + Prospects tab merge
- Agent Pipeline + Agent Collaboration merge consideration
- Pipeline + System Health relationship
- Ops as operations center

### Phase 3: Design System
- Standardize tokens (colors, spacing, typography)
- Replace hardcoded hex with CSS variables
- Consistent badge/chip/status patterns
- Consistent drawer/modal patterns

### Phase 4: Page Redesigns (priority order)
1. Agent Collaboration -- mission-control cockpit
2. Ops / Pipeline / System Health -- automation trust
3. Trade AI / Prospects -- market opportunity
4. Governance / Approvals -- policy control
5. Self-Improvement -- enhance only
