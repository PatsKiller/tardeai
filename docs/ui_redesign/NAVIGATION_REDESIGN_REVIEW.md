# Navigation Redesign Review

Status:      HISTORICAL
as_of:       2026-05-25T10:45:00-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-25

---

## Current Navigation Structure

The nav is a horizontal bar of dropdown groups. Each group expands on click.
Mobile: hamburger drawer with all groups stacked vertically.

### Current Groups (10 groups, 52 items)

| Group | Items | Assessment |
|-------|-------|-----------|
| Command (3) | Morning Command, Inbox, Daily Brief | Good -- tight, purposeful |
| Portfolio (4) | Holdings, Dividends, Returns, Attribution | Good -- clear financial group |
| Risk & Alerts (4) | Risk Dashboard, Alert Dashboard, Risk Regime, Recovery Watch | Good |
| AI Analyst (4) | AI Advisory, Technical/PI, Watchlist, CIO Dashboard | Good |
| Research (5) | Research Intelligence, Topic Monitor, Ticker Research, Intelligence Hub, Overnight Brief | Good |
| Pipeline & Health (4) | System Health, Pipeline Stages, Agent Pipeline, Agent Collaboration | Overlaps with Ops |
| Paper Trading (5) | Proposals, Paper Review, Paper Status, ATM Mode, Incubator | Good |
| Tax & Rebalance (3) | Tax & Lots, Rebalance, Retirement | Good |
| Reports (3) | Reports Hub, Trade Journal, Journal Reports | Journal Reports is a redirect |
| **Admin (17)** | Everything else | **TOO LARGE -- catch-all** |

---

## Key Issues

### 1. Admin Group is a Dumping Ground (17 items)
The Admin group contains:
- Trading tools (Trade AI Live, Prospects, Strategy Desk)
- Analytics (Analytics, Correlation, Forecast)
- Paper trading tools (Broker Recon, Execution Quality, Proposal Alerts, Plan vs Perf)
- Governance tools (Governance, Approvals)
- Agent tools (Agent Calibration, Weekly Learning)
- System tools (Operations, Self-Improvement, Backtesting)

A 17-item dropdown is unusable on both desktop and mobile.

### 2. Pipeline & Health vs Ops Confusion
Both groups contain system monitoring pages:
- Pipeline & Health: System Health, Pipeline Stages, Agent Pipeline, Agent Collaboration
- Admin > Operations: OpsHub (System Hub, Ops Console, LLM Queue, Orchestration)

### 3. Journal Reports Redirect
"Journal Reports" in Reports group redirects to `/journal?tab=reports`, which is the same as Trade Journal with a tab selected. Redundant nav item.

### 4. No "Trading" Group
Trade AI, Prospects, and Strategy Desk are core trading pages but live in Admin.

---

## Proposed Navigation (10 groups, ~48 items)

| Group | Items | Notes |
|-------|-------|-------|
| **Command** (3) | Morning Command, Inbox, Daily Brief | Unchanged |
| **Portfolio** (4) | Holdings, Dividends, Returns, Attribution | Unchanged |
| **Trading** (5) | Trade AI, Prospects, Strategy Desk, Incubator, ATM Mode | NEW group: extracted from Admin + Paper Trading |
| **Paper Trading** (4) | Proposals, Paper Status, Paper Review, Execution Quality | Slimmed: moved Incubator/ATM to Trading, added Execution Quality |
| **Risk & Alerts** (4) | Risk Dashboard, Alert Dashboard, Risk Regime, Recovery Watch | Unchanged |
| **AI Analyst** (4) | AI Advisory, Technical/PI, Watchlist, CIO Dashboard | Unchanged |
| **Research** (5) | Research Intelligence, Topic Monitor, Ticker Research, Intelligence Hub, Overnight Brief | Unchanged |
| **System** (5) | System Health, Pipeline, Agent Pipeline, Operations, Self-Improvement | Merged Pipeline & Health + Ops |
| **Reports** (3) | Reports Hub, Trade Journal, Backtesting | Replaced Journal Reports redirect with Backtesting |
| **Admin** (6) | Governance, Strategy Admin, Agent Calibration, Weekly Learning, Correlation, Forecast | Reduced from 17 to 6 |

### Items Removed from Nav
- "Approvals" -- already in Governance tab
- "Journal Reports" -- redundant redirect
- "Proposal Alerts" -- rarely used, accessible from Paper Proposals
- "Broker Recon" -- accessible from Execution Quality or Paper Review
- "Plan vs Perf" -- accessible from Strategy Analytics
- "Analytics" (Strategy Analytics) -- accessible from Strategy Admin

---

## Header Tape Assessment

Current tape metrics (left to right):
1. Brand ("Command Center")
2. Portfolio value (clickable -> /portfolio)
3. Today change (clickable -> /returns)
4. VIX (clickable -> /trade-ai)
5. Regime (clickable -> /trade-ai)
6. Last Run (clickable -> /trade-ai)
7. Setup State (clickable -> /trade-ai)
8. Journal P&L (clickable -> /journal-analytics)
9. Win Rate (clickable -> /journal-analytics)
10. Live dot
11. Person button
12. Approvals button (conditional)

**Notes:**
- 4 of 8 metrics click to Trade AI -- strong signal that Trade AI is a primary page
- Journal P&L and Win Rate link to `/journal-analytics` which is a redirect
- At 1400px, metrics 7-9 hide
- On mobile, only Portfolio and Today show

**Recommendations:**
- Fix Journal P&L link to point to `/journal?tab=analytics`
- Consider adding ATM status indicator when ATM is active
- Add a small "market open/closed" indicator

---

## Mobile Drawer Assessment

The mobile drawer renders all 52 nav items in groups with section headers.
Touch targets are 44px minimum -- meets accessibility requirements.

**Issues:**
- 52 items requires significant scrolling
- Admin group (17 items) dominates the drawer
- No search/filter in drawer

**Recommendations:**
- Reduce to ~42 items via proposed restructuring
- Add "Favorites" or "Recent" section at top of drawer
- Consider collapsible groups in drawer (currently all expanded)
