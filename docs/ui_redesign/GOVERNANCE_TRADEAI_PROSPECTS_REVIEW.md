# Governance / Trade AI / Prospects Review

Status:      HISTORICAL
as_of:       2026-05-25T10:45:00-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-25

---

## Trade AI (`/v2/trade-ai`)

### Current State
- Full screener run dashboard with tickers, scores, signals
- Shows VIX, regime, market breadth, GO/WAIT/AVOID decisions
- Run history, critic verdicts, social sentiment
- Placed in **Admin** nav group

### Issues
1. **Misplaced in Admin group.** Trade AI is a core trading function, not an admin tool. It should be in a "Trading" or "Markets" nav group.
2. **Heavy page** with many data columns -- could benefit from collapsible sections.
3. The header tape links VIX/Regime/Setup State clicks to Trade AI, making it a primary landing page.

### Recommendations
- Move to a "Trading" or "Markets" nav group at a top-level position
- Consider splitting the run history into a collapsible section
- Add a "Run Now" button if trade-ai/run POST is available

---

## Prospects (`/v2/prospects`)

### Current State
- Independent prospect screener with type filters (scalp/swing/income/position/all)
- Price range defaults per type
- Source-colored badges, tier coloring, decision coloring
- Placed in **Admin** nav group

### Issues
1. **Misplaced in Admin group.** This is a trading discovery tool.
2. **Overlaps with Trade AI.** Both show scored tickers with GO/WAIT/AVOID.
3. **Different API?** Prospects uses its own `/api/v2/prospects` endpoint.
4. **Unclear relationship:** Is Prospects a filtered view of Trade AI data, or independent?

### Recommendations
- Option A: Merge into Trade AI as a "Prospect Filter" tab
- Option B: Keep separate but move to a "Trading" nav group alongside Trade AI
- Clarify the data lineage: do Prospects come from the same screener pipeline?

---

## Governance (`/v2/governance`)

### Current State
- GovernanceHub with 3 tabs:
  1. **Paper Validation** (PaperGovernance) -- paper trade governance metrics, catalog, screener membership, lifecycle
  2. **Learning Governance** (LearningGovernance) -- hypotheses, experiments, recommendations, config proposals
  3. **Approvals** (Approvals) -- pending approvals, history, states, tasks

### Issues
1. **Approvals tab in Governance AND as `/v2/approvals` in Admin nav.** The Admin nav "Approvals" redirects to `/governance`, but this is confusing -- user sees "Approvals" in Admin and also in Governance.
2. **Paper Validation governance overlaps with Paper Review.** PaperGovernance shows outcome analytics that also appear in PaperReview (PaperOutcomes).
3. Both PaperGovernance and ExecutionQuality pull `/api/v2/paper-performance-governance`.

### Shared API Endpoints
| Endpoint | Used By |
|----------|---------|
| `/api/v2/paper-performance-governance` | PaperGovernance, LiveGovernance, PaperOutcomes, ExecutionQuality, StrategyAdmin |
| `/api/v2/execution-quality` | ExecutionQuality, LiveGovernance, PaperOutcomes |
| `/api/v2/paper-dashboard-summary` | PaperGovernance, PaperOutcomes |
| `/api/v2/approvals/pending` | Approvals (Governance tab) |

### Recommendations
1. Remove "Approvals" from Admin nav (it already redirects to Governance)
2. Consider whether Paper Validation belongs in Governance or in Paper Trading
3. Governance should focus on: rules, policies, learning. Paper outcomes should live in Paper Review.

---

## Summary Table

| Page | Current Nav | Recommended Nav | Notes |
|------|------------|----------------|-------|
| Trade AI | Admin | Trading (new group) | Core feature, not admin |
| Prospects | Admin | Trading (new group) | Or merge into Trade AI |
| Governance | Admin | Admin (keep) | Remove duplicate Approvals link |
| Approvals | Admin | Remove (redundant) | Already a Governance tab |
| Strategy Desk | Admin | Trading (new group) | Core feature |
| Strategy Admin | Admin | Admin (keep) | Config tool = admin |
| Strategy Analytics | Admin | Admin or Trading | Analytics about strategies |
