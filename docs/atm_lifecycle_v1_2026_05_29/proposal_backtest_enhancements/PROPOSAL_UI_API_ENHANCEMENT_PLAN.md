# Proposal UI/API Enhancement Plan — 2026-05-29

## Goal
Make proposal records actionable and traceable without mutating trading state.

## Current State
- 141 proposals, all terminal (0 PENDING)
- 4 creation paths, 2 enrichment systems, 3 stale-detection systems
- 4 overlapping status dimensions
- UI derives action state client-side, diverging from DB

## Required Proposal Row Display

### Fields (per proposal row)
| Field | Source | Status |
|-------|--------|--------|
| proposal_id | paper_trade_proposals.id | Available |
| symbol | paper_trade_proposals.symbol | Available |
| strategy | paper_trade_proposals.strategy_id | Available |
| status | paper_trade_proposals.status | Available (case bug: 3 lowercase) |
| source/discovery source | paper_trade_proposals.auto_proposal_reason + source_signal_id | Partial — reason available, not always populated |
| enrichment status | paper_trade_proposals.enrichment_status | Available |
| enrichment attempts | paper_trade_proposals.enrichment_failures | Available |
| linked paper_trade_id | paper_trade_proposals.paper_trade_id | Available (20/141 linked) |
| linked backtest/replay row | proposal_backtest_snapshots.proposal_id | Indirect — no direct FK to strategy_backtest_trades |
| stale/duplicate/blocked reason | action_state + atm_expiry_reason + signal_decision | Partial — spread across fields |
| next action | Computed from enrichment_status + status + action_state | Not surfaced as single field |

### Required Actions (per proposal row)
| Action | API Endpoint | Status |
|--------|-------------|--------|
| View Lifecycle | /api/v2/paper-proposals/lifecycle-events | Available |
| View Source/Evidence | /api/v2/paper-proposals/research-packet | Available |
| View Backtest Replay | No direct link | **GAP** — no FK from proposal to strategy_backtest_trades |
| View Trade | paper_trade_id → /api/v2/paper-trades/{id} | Available when linked |

### Non-Actionable Conditions
Proposals should NOT appear actionable if:
| Condition | Detection | Status |
|-----------|-----------|--------|
| Missing enrichment | enrichment_status != 'COMPLETE' | Detectable |
| Blocked | action_state = 'BLOCKED' | Detectable |
| Duplicate | proposal_dedup_audit match | Batch only |
| Rejected | status = 'REJECTED' | Detectable |
| Expired | status IN ('EXPIRED','expired') | Detectable (case bug) |
| Linked trade exists | paper_trade_id IS NOT NULL | Detectable |

## Design Decisions

### Code Changes: DESIGN ONLY (not patched this session)
Given the complexity of the overlapping status dimensions and the case inconsistency bug, patches are deferred to avoid introducing subtle regressions in a parallel session.

### Recommended Patches (next session)

**Patch 1: Fix expired case inconsistency** (api_v2.py:7501)
```python
# Change: status='expired' → status='EXPIRED'
```
Risk: Low. Single line change. All downstream checks handle both cases already.

**Patch 2: Fix hygiene panel field** (api_v2.py:20497-20504)
```python
# Change: classify based on `status` instead of `signal_decision`
```
Risk: Low. Read-only display endpoint.

**Patch 3: Add run_type to backtesting Trades table** (Backtesting.tsx:432-447)
```tsx
// Add column: { key: 'run_type', label: 'Source Type' }
```
Risk: Low. Read-only display.

**Patch 4: Add next_action computed field to proposal list API**
```python
# In /api/v2/paper-proposals response:
# Compute next_action from enrichment_status + status + action_state
```
Risk: Low. Additive field.

### SHFS Surface
If SHFS (id=860) lacks enrichment, it should surface as:
- "Needs enrichment/manual classification"
- NOT a system failure
- NOT eligible for automated apply without evidence
- This is a backtest-only item (no proposal exists for SHFS)

## Files That Would Change
- `scripts/api_v2.py` — hygiene panel, expired case fix, proposal API next_action field
- `apps/command-center-v2/src/pages/Backtesting.tsx` — run_type column in Trades table
- `apps/command-center-v2/src/pages/PaperProposals.tsx` — next_action display

## Safety Note
All proposed changes are read-only UI/API display enhancements. No mutations to trading state, proposals, or broker connections.
