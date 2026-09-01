# Governance & Approvals -- Design Notes

Status:      HISTORICAL
as_of:       2026-05-25T15:07:30-04:00
Measured at: efcc51365 / not measured

## Phase 4: Governance & Approvals Family

This phase redesigns 7 pages that together form the governance, approval, and trade proposal review system. These are the most critical decision-making pages in the Command Center.

---

## What Changed Per Page

### GovernanceHub.tsx (29 lines, TabPage wrapper)
- Title: "Governance" -> "Governance Center"
- Added subtitle via fragment wrapper: "Policy rules, approval gates, validation controls, and audit readiness"
- Tab label "Learning Governance" -> "Learning & Experiments"
- Tab label "Approvals" -> "Approvals & Tasks"
- No logic changes. Same 3 lazy-loaded child components.

### PaperReview.tsx (20 lines, TabPage wrapper)
- Title: "Paper Trade Review" -> "Paper Review & Learning"
- Added subtitle via fragment wrapper
- No logic changes. Same 2 lazy-loaded child components.

### ProposalAlerts.tsx (107 lines)
- Inline summary cards replaced with `StateCard` (4 cards: Ready, Blocked, Review, Pending)
- Inline `statusColor()` helper removed; table status pills now use `StatusBadge`
- Title: "Proposal Alerts" -> "Proposal Alert Board"
- Layout changed from flex row to grid for summary cards

### PaperGovernance.tsx (182 lines)
- Summary tiles replaced with `StateCard` components (6 cards in grid)
- Inline `pill('red')` for gate status replaced with `StatusBadge status="blocked"`
- Governance state pills in strategy scorecard table replaced with `StatusBadge`
- Run Governance Check button replaced with `ActionButton`
- LIVE TRADING DISABLED banner preserved exactly (critical safety notice)
- `kv()` helper preserved for grid displays

### LearningGovernance.tsx (189 lines)
- Inline `btn` style replaced with `ActionButton`
- Tab buttons use `ActionButton` with variant switching (primary/secondary)
- Refresh button uses `ActionButton`
- Inline `dot()` status dots replaced with `StatusBadge` in all 4 data tables
- Overview tiles use `StateCard` instead of `Card` with manual value rendering
- `SC` color map converted to StatusBadge status mapping
- Sample Size Banner preserved exactly

### Approvals.tsx (494 lines)
- Inline urgency pills replaced with `StatusBadge`
- Inline priority pills replaced with `SeverityBadge`
- "FAILED AUTO" badge uses `SeverityBadge severity="critical"`
- "STALE" badge uses `StatusBadge status="stale"`
- Approve/Reject buttons replaced with `ActionButton` (children pattern)
- Quick nav and supporting link buttons replaced with `ActionButton variant="ghost"`
- Decision history pills replaced with `StatusBadge`
- "Decided" indicators replaced with `StatusBadge status="complete"`
- Advisory banner preserved exactly
- All decision controls preserved

### PaperProposals.tsx (1185 lines)
- Operator verdict summary bar uses `StateCard` instead of inline tiles
- Header verdict pill uses `StatusBadge` with action state mapping
- Signal grade badges use `StatusBadge`
- Missing data pills use `StatusBadge status="blocked"`
- Staleness badge uses `StatusBadge status="stale"`
- LifecycleBadge helper now wraps `StatusBadge`
- All action buttons (Approve, Reject, Details, workflow steps, enrichment) use `ActionButton`
- ConfirmModal buttons use `ActionButton`
- Header action buttons (Refresh, Enrich All, Promote, Screener Config) use `ActionButton`
- MetricTile component preserved (custom hover behavior)
- Inline `pill()` function removed (replaced by StatusBadge throughout)
- Inline `btnStyle()` function removed (replaced by ActionButton throughout)
- All enrichment pipeline polling logic preserved
- All market revalidation logic preserved

---

## What Did NOT Change (across all pages)

### API Endpoints (zero changes)
- `/api/v2/paper-proposals` (30000ms poll) -- PaperProposals, ProposalAlerts
- `/api/v2/pipeline-run-health` -- PaperProposals
- `/api/v2/paper-proposals/approve` (POST) -- PaperProposals
- `/api/v2/paper-proposals/reject` (POST) -- PaperProposals
- `/api/v2/paper-proposals/refresh-data` (POST) -- PaperProposals
- `/api/v2/paper-proposals/check-execution-readiness` (POST) -- PaperProposals
- `/api/v2/paper-proposals/run-ai-review` (POST) -- PaperProposals
- `/api/v2/paper-proposals/enrich-all` (POST) -- PaperProposals
- `/api/v2/paper-proposals/enrich-status` (GET) -- PaperProposals
- `/api/v2/paper-proposals/promote-from-incubator` (POST) -- PaperProposals
- `/api/v2/paper-proposals/run-research` (POST) -- PaperProposals
- `/api/v2/paper-proposals/run-backtest` (POST) -- PaperProposals
- `/api/v2/paper-proposals/run-indicators` (POST) -- PaperProposals
- `/api/v2/paper-performance-governance` (60000ms poll) -- PaperGovernance
- `/api/v2/paper-performance-governance/run` (POST) -- PaperGovernance
- `/api/v2/paper-dashboard-summary` (60000ms poll) -- PaperGovernance
- `/api/v2/ticker-catalog/summary` (60000ms poll) -- PaperGovernance
- `/api/v2/screener-membership/summary` (60000ms poll) -- PaperGovernance
- `/api/v2/incubator-lifecycle/summary` (60000ms poll) -- PaperGovernance
- `/api/v2/learning/status` -- LearningGovernance
- `/api/v2/learning/hypotheses` -- LearningGovernance
- `/api/v2/learning/experiments` -- LearningGovernance
- `/api/v2/learning/recommendations` -- LearningGovernance
- `/api/v2/learning/config-proposals` -- LearningGovernance
- `/api/v2/approvals/pending` -- Approvals
- `/api/v2/approvals/history` -- Approvals
- `/api/v2/approvals/states` (30000ms poll) -- Approvals
- `/api/v2/tasks` (30000ms poll) -- Approvals
- `/api/v2/approvals/decision` (POST) -- Approvals

### Approval Behavior (zero changes)
- Approval gating logic preserved exactly
- RSI gate blocking preserved
- Execution gate blocking preserved
- Market revalidation on approval preserved
- Note/rationale requirement preserved
- CAUTIOUS_PAPER_TEST confirm modal flow preserved
- Decision history tracking preserved
- handleDecision callback preserved exactly

### Safety Constraints
- LIVE TRADING DISABLED banner preserved
- No new approval actions added
- No existing approval gates bypassed or removed
- No trading execution added
- Advisory-only banner preserved in Approvals

---

## Shared Primitives Used

| Primitive | Prop Pattern | Pages Using It |
|---|---|---|
| `StatusBadge` | `status=`, `label?=`, `size?=` | All 7 pages |
| `SeverityBadge` | `severity=`, `label?=` | Approvals |
| `ActionButton` | `children` (NOT label=!), `variant?=`, `size?=`, `loading?=`, `disabled?=`, `onClick?=` | PaperGovernance, LearningGovernance, Approvals, PaperProposals |
| `StateCard` | `title=` (NOT label=!), `value?=`, `status?=`, `compact?=` | ProposalAlerts, PaperGovernance, LearningGovernance, PaperProposals |
| `AgentChip` | `name=` (NOT agent=!) | Not used in this phase (agent reviews display agent name as text) |

---

## How Pages Relate After Redesign

```
/governance -> GovernanceHub ("Governance Center")
  tab=paper -> PaperGovernance (paper validation gates)
  tab=learning -> LearningGovernance (hypotheses/experiments)
  tab=approvals -> Approvals (decision queue + history)

/paper-proposals -> PaperProposals (proposal review + enrichment)
/proposal-alerts -> ProposalAlerts (proposal alert board)

/paper-review -> PaperReview ("Paper Review & Learning")
  tab=outcomes -> PaperOutcomes
  tab=intelligence -> PaperTradeIntelligence

Redirects (unchanged):
/paper-governance -> /governance
/learning-governance -> /governance?tab=learning
/approvals -> /governance
/proposals -> /paper-proposals
/paper-outcomes -> /paper-review
```

## Known Risks
- PaperProposals.tsx replacement is the largest file (~1100 lines) -- verify all existing functionality preserved
- PaperGovernance and LearningGovernance are tab children of GovernanceHub -- test together
- ProposalAlerts shares the same API as PaperProposals -- no data conflicts expected
- Approvals.tsx has complex decision flow -- verify approve/reject/notes all work after apply
