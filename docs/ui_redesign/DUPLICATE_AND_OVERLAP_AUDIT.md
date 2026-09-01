# Duplicate and Overlap Audit

Status:      HISTORICAL
as_of:       2026-05-25T10:45:00-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-25

---

## 1. Routes Using the Same Component

| Component | Routes that render it |
|-----------|-----------------------|
| PortfolioCommand | `/portfolio`, `/portfolio-monitor`, `/portfolio-intelligence` |
| PipelineHub | `/pipeline`, `/pipeline-health-master`, `/pipeline-controller` |
| OpsHub | `/ops`, `/hub`, `/orchestration` |
| IntelligenceHub | `/intelligence`, `/intelligence-sources`, `/intelligence-entities`, `/intelligence-whiteboard` |
| GovernanceHub | `/governance`, `/live-governance` |
| Inbox | `/inbox`, `/alerts` (2nd def), `/notifications`, `/actions` |
| PaperReview | `/paper-review`, `/paper-trade-intelligence` |

**Assessment:** These are intentional legacy redirects from the consolidation effort. No action needed except eventually removing legacy routes once no external links reference them.

## 2. Routes Hitting the Same API Endpoints

### High Overlap Endpoints:

| API Endpoint | Pages Using It |
|-------------|----------------|
| `/api/v2/overview` | Overview, Shell (header tape), MorningBrief, AlertsActions |
| `/api/v2/risk` | Risk, MorningBrief, AlertsActions |
| `/api/v2/portfolio/holdings` | Portfolio (via PortfolioCommand), Technical, Returns |
| `/api/v2/paper-performance-governance` | PaperGovernance, LiveGovernance, PaperOutcomes, ExecutionQuality, StrategyAdmin |
| `/api/v2/execution-quality` | ExecutionQuality, LiveGovernance, PaperOutcomes |
| `/api/v2/proposals` | Overview, MorningBrief, Retirement |
| `/api/v2/agent-health` | Overview, MorningBrief, AgentPipeline |
| `/api/v2/macro-context` | Overview, MorningBrief, Retirement |
| `/api/v2/notifications/recent` | Overview, Notifications (Inbox), StoppedOutWatch |
| `/api/v2/broker-reconciliation` | BrokerReconciliation, LiveGovernance |
| `/api/v2/automated-journal` | Overview, PaperOutcomes, PaperJournal |
| `/api/v2/paper-dashboard-summary` | PaperGovernance, PaperOutcomes |
| `/api/v2/ops/summary` | Overview, Ops (OpsHub) |
| `/api/v2/agents/summary` | Retirement, CIODashboard, AIAnalyst |
| `/api/v2/system-health` | SystemHealth, AgentPipeline |

**Assessment:** Data sharing across pages is expected in a dashboard app. The Overview page is the heaviest consumer (18 API calls). Consider a shared data context or cross-page cache if performance becomes an issue.

## 3. Nav Items Pointing to Similar Functionality

### CRITICAL: `/v2/alerts` Route Conflict
- **Line 187** in App.tsx: `<Route path="alerts" element={<AlertsDashboard />} />`
- **Line 206** in App.tsx: `<Route path="alerts" element={<Inbox />} />`
- React Router matches first definition, so `AlertsDashboard` wins.
- But the legacy redirect to Inbox is dead code.
- **Risk & Alerts** nav group links to `/alerts` (AlertsDashboard).
- **FIX:** Remove the duplicate route definition on line 206.

### OVERLAP: Governance vs Approvals
- `/v2/governance` (GovernanceHub) has an "Approvals" tab
- `/v2/approvals` in Admin nav redirects to `/governance`
- This is correctly consolidated -- the Admin nav item is a convenience link.
- **Verdict:** Working as intended.

### OVERLAP: Ops vs Pipeline vs System Health vs Agent Pipeline
These are 4 separate pages with distinct responsibilities:
- `/v2/ops` (OpsHub): System Hub + Ops Console + LLM Queue + Orchestration
- `/v2/pipeline` (PipelineHub): Pipeline Health Master + Pipeline Stage Controller
- `/v2/system-health`: System health + Finviz screener status
- `/v2/agent-pipeline`: Agent action feed with system health side panel

**Concern:** All 4 are in the "Pipeline & Health" nav group. Users may be confused about which to check first.
**Recommendation:** Consider:
1. Merge System Health into OpsHub as a tab
2. Move Agent Pipeline into PipelineHub as a tab
3. Result: 2 pages instead of 4

### OVERLAP: Trade AI vs Prospects
- `/v2/trade-ai`: Full screener run results with tickers, scores, signals
- `/v2/prospects`: Independent prospect screener (scalp/swing/income filters)
- Both show scored ticker lists with GO/WAIT/AVOID decisions
- Trade AI is the production screener; Prospects is a manual filter tool
- **Recommendation:** Consider merging Prospects as a tab in Trade AI

### CONCERN: Admin Group is a Dumping Ground
The Admin nav group has 17 items. Several belong elsewhere:
- Trade AI Live, Prospects, Strategy Desk -> Trading & Analysis group
- Correlation, Forecast -> Research or AI Analyst group
- Broker Recon, Execution Quality -> Paper Trading group
- Proposal Alerts -> Paper Trading group
- Approvals -> already redirects to Governance

## 4. Orphaned Pages (not in nav)

| Route | Component | Status |
|-------|-----------|--------|
| `/v2/bot-morning-brief` | MorningBriefBot | Not in any nav group |
| `/v2/watchlist/:symbol` | WatchlistSymbolPage | Deep link only (OK) |
| `/v2/agent-dashboard/:agentId` | AgentDashboard | Deep link only (OK) |

## 5. Legacy Page Files (not routed)

These `.tsx` files exist in `pages/` but are NOT imported in App.tsx:
- `ActionCenter.tsx` -- used by Inbox hub
- `AlertsActions.tsx` -- used by Inbox hub
- `Approvals.tsx` -- used by GovernanceHub
- `ContentHealth.tsx` -- used by IntelligenceHub
- `IntelligenceEntities.tsx` -- used by IntelligenceHub
- `IntelligenceSources.tsx` -- used by IntelligenceHub
- `IntelligenceWhiteboard.tsx` -- used by IntelligenceHub
- `Journal.tsx` -- used by JournalHub
- `JournalAnalytics.tsx` -- used by JournalHub
- `JournalReports.tsx` -- used by JournalHub
- `AutomatedTradeJournal.tsx` -- used by JournalHub
- `LearningGovernance.tsx` -- used by GovernanceHub
- `LiveGovernance.tsx` -- used by GovernanceHub
- `LLMQueue.tsx` -- used by OpsHub
- `Notifications.tsx` -- used by Inbox
- `Ops.tsx` -- used by OpsHub
- `Orchestration.tsx` -- used by OpsHub
- `PaperGovernance.tsx` -- used by GovernanceHub
- `PaperOutcomes.tsx` -- used by PaperReview
- `PaperTradeIntelligence.tsx` -- used by PaperReview
- `PipelineController.tsx` -- used by PipelineHub
- `PipelineHealthMaster.tsx` -- used by PipelineHub
- `Portfolio.tsx` -- used by PortfolioCommand
- `PortfolioMonitor.tsx` -- used by PortfolioCommand
- `PortfolioIntelligence.tsx` -- used by PortfolioCommand
- `SystemHub.tsx` -- used by OpsHub
- `PaperJournal.tsx` -- legacy, still has redirect

**Truly unused (dead code):**
- `Journal.tsx.bak_journal_maturity` -- backup file
- `JournalAnalytics.tsx.bak_journal_maturity` -- backup file
- `PortfolioIntelligence.tsx.bak_pi_dollars` -- backup file
- `PortfolioIntelligence.tsx.bak_pi_interactive` -- backup file

## 6. Summary of Key Findings

| Finding | Severity | Action |
|---------|----------|--------|
| `/alerts` route defined twice | BUG | Remove duplicate on line 206 |
| Admin group has 17 items | UX | Redistribute into proper groups |
| 4 overlapping Pipeline/Health pages | UX | Consider consolidating to 2 |
| Trade AI vs Prospects overlap | UX | Consider merging |
| Overview page makes 18 API calls | PERF | Monitor; consider shared cache |
| 4 .bak files in pages/ | CLEANUP | Delete backup files |
| bot-morning-brief orphaned | MINOR | Add to nav or remove |
