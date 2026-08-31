# Page Family Consolidation Review

Status:      HISTORICAL
as_of:       2026-05-25T10:45:00-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-25

---

## Already Consolidated (Hub Pattern)

These hubs are working well -- each uses TabPage to group related sub-pages:

| Hub | Tabs | Status |
|-----|------|--------|
| PortfolioCommand | Holdings, Health & Risk, Intelligence | Good |
| Inbox | Actions & Alerts, Notification Log, Task Queue | Good |
| JournalHub | Entries, Analytics, Reports, Automated Journal | Good |
| IntelligenceHub | Sources, Entities, Whiteboard, Content Health | Good |
| PipelineHub | Health Overview, Stage Controller | Good |
| GovernanceHub | Paper Validation, Learning Governance, Approvals | Good |
| OpsHub | System Hub, Ops Console, LLM Queue, Orchestration | Good |
| PaperReview | Outcomes, TCA & Intelligence | Good |

---

## Candidates for Consolidation

### Family 1: Trading & Screening
**Current:** 3 separate pages
- Trade AI (`/trade-ai`) -- screener results
- Prospects (`/prospects`) -- prospect discovery  
- Strategy Desk (`/strategy-desk`) -- strategy overview

**Proposal:** Create "Trading Hub" with 3 tabs

### Family 2: System Monitoring
**Current:** 4 separate pages
- System Health (`/system-health`)
- Pipeline Stages (`/pipeline`)
- Agent Pipeline (`/agent-pipeline`)
- Agent Collaboration (`/agent-collaboration`)

**Proposal:** Merge System Health into PipelineHub; merge Agent Pipeline + Agent Collaboration into "Agent Ops Hub"

### Family 3: Strategy Configuration
**Current:** 3 separate pages
- Strategy Admin (`/strategy-admin`)
- Strategy Analytics (`/strategy-analytics`)
- Agent Calibration (`/agent-calibration`)

**Proposal:** Create "Strategy Admin Hub" with 3 tabs

### Family 4: Paper Trading Lifecycle
**Current:** 5+ pages
- Paper Proposals (`/paper-proposals`)
- Paper Status (`/paper-status`)
- Paper Review (`/paper-review`)
- Incubator (`/incubator`)
- ATM Mode (`/automated-trade-mode`)

**Assessment:** These represent different lifecycle stages. Consolidation not recommended -- each has distinct operator workflow.

### Family 5: Analysis & Intelligence
**Current:** Scattered
- Technical (`/technical`)
- Correlation (`/correlation`)
- Forecast (`/forecast`)
- Research (`/research`)

**Proposal:** Create "Analysis Hub" with 4 tabs, or group under Research nav

### Family 6: Risk
**Current:** 3 separate pages
- Risk Dashboard (`/risk`)
- Risk Regime (`/risk-regime`)
- Recovery Watch (`/recovery`)

**Assessment:** Risk Regime and Risk Dashboard could be tabs. Recovery Watch is sufficiently distinct.

---

## Consolidation Impact Matrix

| Action | Pages Before | Pages After | Routes Removed | Nav Items Saved |
|--------|-------------|-------------|----------------|-----------------|
| Trading Hub | 3 | 1 | 2 | 2 |
| System + Pipeline merge | 4 | 2 | 2 | 2 |
| Strategy Admin Hub | 3 | 1 | 2 | 2 |
| Analysis Hub | 4 | 1 | 3 | 3 |
| Risk merge | 2 | 1 | 1 | 1 |
| **Total** | **16** | **6** | **10** | **10** |

Net effect: 55 routes -> ~45 routes; 52 nav items -> ~42 nav items.

---

## Principles for Consolidation

1. **Use the TabPage pattern** -- already proven across 8 hubs
2. **Keep deep links working** -- legacy route redirects with query params
3. **Don't merge pages with different refresh rates** -- e.g., ATM (15s polling) shouldn't share a tab with Governance (60s)
4. **Admin group cleanup** is the highest priority UX win
5. **Preserve operator muscle memory** -- don't rename things unnecessarily
