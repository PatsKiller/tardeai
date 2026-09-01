# Governance & Approvals Route Audit

Status:      HISTORICAL
as_of:       2026-05-25T15:07:30-04:00
Measured at: efcc51365 / not measured

## All Governance/Approval/Proposal Routes Found

| Route Path | Source File | Status | Recommendation |
|---|---|---|---|
| `/governance` | `GovernanceHub.tsx` | Active (TabPage wrapper) | Keep -- redesign as "Governance Center" |
| `/governance?tab=paper` | `PaperGovernance.tsx` (tab in GovernanceHub) | Active tab | Keep as tab |
| `/governance?tab=learning` | `LearningGovernance.tsx` (tab in GovernanceHub) | Active tab | Keep as tab |
| `/governance?tab=approvals` | `Approvals.tsx` (tab in GovernanceHub) | Active tab | Keep as tab |
| `/paper-governance` | `Navigate to ../governance` | Redirect | Keep redirect |
| `/learning-governance` | `Navigate to /governance?tab=learning` | Redirect | Keep redirect |
| `/approvals` | `Navigate to ../governance` | Redirect | Keep redirect |
| `/live-governance` | `GovernanceHub` (direct mount) | Active duplicate | Keep (same component) |
| `/paper-proposals` | `PaperProposals.tsx` | Active (standalone page) | Keep separate -- redesign |
| `/proposal-alerts` | `ProposalAlerts.tsx` | Active (standalone page) | Keep separate -- redesign |
| `/paper-review` | `PaperReview.tsx` (TabPage wrapper) | Active | Keep separate -- redesign |
| `/paper-outcomes` | `Navigate to ../paper-review` | Redirect | Keep redirect |
| `/paper-trade-intelligence` | `PaperReview` (direct mount) | Active duplicate | Keep (same component) |
| `/proposals` | `Navigate to ../paper-proposals` | Redirect | Keep redirect |

## Architecture Summary

There are 3 distinct page groups in governance:

1. **GovernanceHub** -- a TabPage wrapper hosting 3 sub-pages:
   - PaperGovernance (paper validation gates, strategy scorecards)
   - LearningGovernance (hypotheses, experiments, recommendations, config proposals)
   - Approvals (decision tasks + approval queue + decision history)

2. **PaperProposals** -- standalone, the largest page (~1185 lines). Handles automated trade proposal review, enrichment, approval/rejection workflow.

3. **PaperReview** -- a TabPage wrapper hosting 2 sub-pages:
   - PaperOutcomes
   - PaperTradeIntelligence

4. **ProposalAlerts** -- standalone (~107 lines). Displays proposal alerts derived from the same `/api/v2/paper-proposals` endpoint.

## Files Requiring Redesign

| File | Lines | Complexity | Redesign Scope |
|---|---|---|---|
| GovernanceHub.tsx | 29 | Low (TabPage wrapper) | Title, subtitle, tab labels |
| PaperGovernance.tsx | 182 | Medium | StatusBadge, StateCard, ActionButton adoption |
| LearningGovernance.tsx | 189 | Medium | StatusBadge, StateCard, ActionButton adoption |
| Approvals.tsx | 494 | High | StatusBadge, SeverityBadge, ActionButton adoption |
| PaperProposals.tsx | 1185 | Very High | StatusBadge, SeverityBadge, StateCard, ActionButton adoption |
| ProposalAlerts.tsx | 107 | Low | StatusBadge, StateCard adoption |
| PaperReview.tsx | 20 | Low (TabPage wrapper) | Title, subtitle only |

## Decision: What Gets a REPLACEMENT.md

- GovernanceHub.tsx -- YES (rename + subtitle)
- PaperGovernance.tsx -- YES (primitive adoption)
- LearningGovernance.tsx -- YES (primitive adoption)
- Approvals.tsx -- YES (primitive adoption, largest governance tab)
- PaperProposals.tsx -- YES (primitive adoption, largest page overall)
- ProposalAlerts.tsx -- YES (primitive adoption)
- PaperReview.tsx -- YES (rename + subtitle)
