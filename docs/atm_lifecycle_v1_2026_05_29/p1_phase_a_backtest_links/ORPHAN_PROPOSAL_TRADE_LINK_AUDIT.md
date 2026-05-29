# Orphan Proposal/Trade Link Audit — 2026-05-29

## Summary
- **33** paper_trades have `proposal_id` set
- **20** proposals have `paper_trade_id` set (pointing back to paper_trades)
- **13** paper_trades link to a proposal whose `paper_trade_id` points to a *different* trade

## Pattern
Every orphan follows the same pattern: a proposal created one trade (the "first" trade that the proposal links back to), then a second trade was created referencing the same proposal. The proposal only stores the first trade's ID.

## All 13 Orphan Links

| paper_trade_id | symbol | proposal_id | pt_status | proposal_paper_trade_id | proposal_status | Category |
|----------------|--------|-------------|-----------|-------------------------|-----------------|----------|
| 8 | INFU | 61 | cancelled | 7 | REJECTED | Re-entry after cancel |
| 11 | FLYW | 60 | cancelled | 10 | REJECTED | Re-entry after cancel |
| 12 | FLYW | 60 | closed | 10 | REJECTED | Re-entry after cancel |
| 16 | BLBD | 42 | closed | 15 | REJECTED | Re-entry after cancel |
| 18 | FLYW | 59 | cancelled | 17 | REJECTED | Re-entry after cancel |
| 22 | GCTS | 69 | closed | 20 | REJECTED | Re-entry after cancel |
| 23 | GCTS | 69 | cancelled | 20 | REJECTED | Re-entry after cancel |
| 27 | ASPN | 107 | closed | 26 | REJECTED | Re-entry after cancel |
| 31 | AGNC | 120 | open | 30 | REJECTED | Re-entry after cancel |
| 33 | CMCSA | 123 | open | 32 | REJECTED | Re-entry after cancel |
| 38 | BLMN | 130 | open | 37 | REJECTED | Re-entry after cancel |
| 40 | SNOW | 138 | open | 39 | APPROVED_FOR_PAPER_TEST | Re-entry after cancel |
| 42 | ONDS | 139 | closed | 41 | APPROVED_FOR_PAPER_TEST | Re-entry after cancel |

## Analysis

### Why Proposals Don't Link Back
The proposal stores only one `paper_trade_id`. When the ATM auto-approver or manual approval creates a trade from a proposal, it sets `proposal.paper_trade_id = new_trade.id`. If a second trade is later created from the same proposal (e.g., after a cancellation and re-entry), the second trade sets its own `proposal_id` to the same proposal, but the proposal's `paper_trade_id` still points to the first trade.

### Is This a Bug?
**Soft no** — it's a design limitation. The proposal has a 1:1 `paper_trade_id` field, but the reality is 1:N (one proposal can produce multiple trades via cancellation/re-entry). The `paper_trades.proposal_id` (N:1) relationship is correct — all trades correctly reference their source proposal.

### Categories
All 13 are **re-entry after cancel** pattern:
- Proposal created Trade A (proposal.paper_trade_id = A)
- Trade A was cancelled or closed
- Trade B was created from same proposal (trade B.proposal_id = proposal.id)
- Proposal still points to Trade A, not Trade B

### Should We Update Proposals?
**Not recommended** — updating `proposal.paper_trade_id` to point to the latest trade would break the audit trail of which trade was originally created. The correct fix would be to add a `paper_trade_proposals_trades` junction table (M:N), but that's a P3 schema change.

### Is This Safe to Leave?
**YES** — the orphan links don't affect:
- Automated trading (ATM reads proposal status, not paper_trade_id)
- Journal (reads paper_trades directly)
- Backtesting (reads strategy_backtest_trades)
- Classification (reads strategy_backtest_trades)

## Recommendation
- **Do NOT reconcile** — leave as-is, document the 1:N pattern
- **P3**: Consider adding a junction table or array column for multi-trade proposals
- **P2**: Consider updating proposal hygiene panel to show "N trades created" count

## Full Data
See: `orphan_proposal_trade_links.json`
