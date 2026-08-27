# Orphan Link Reconciliation Plan — 2026-05-29

## Decision: DO NOT RECONCILE

### Reason
The 13 "orphan" links are not bugs — they are a natural consequence of the 1:N relationship between proposals and trades. Each proposal can produce multiple trades (via cancel/re-entry), but the proposal only stores the first trade's ID in `paper_trade_id`.

Updating `proposal.paper_trade_id` to point to the latest trade would:
1. Break audit trail of the original trade creation
2. Not solve the fundamental 1:N problem
3. Create confusion about which trade was the "primary" trade

### What Would Be Required for Full Fix
- **P3 schema change**: Add `paper_trade_proposals_trades` junction table
- **OR**: Change `paper_trade_id` to an array column `paper_trade_ids`
- Neither is appropriate for a P1 quick fix

### Current Impact
**None** — the orphan pattern does not affect:
- Automated trading execution
- Journal P&L calculations
- Backtesting results
- Classification completeness
- Proposal hygiene panel (uses proposal status, not paper_trade_id)

### Operator Approval
Not required — no DB changes proposed.
