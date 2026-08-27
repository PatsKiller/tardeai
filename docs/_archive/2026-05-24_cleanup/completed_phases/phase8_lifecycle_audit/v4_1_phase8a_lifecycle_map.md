# Phase 8A Lifecycle Map

## End-to-End Flow

```
paper_trade_proposals (83 total)
  ↓ paper_trade_id FK (11 linked)
paper_trades (23 total, 9 closed)
  ↓ proposal_id FK (18 linked back)
  ↓ broker='alpaca_paper' (15 trades)
  ↓ status='closed' (9)
    → exit_reason (9/9 populated)
    → pnl (9/9 populated)
    → r_multiple (9/9 populated)
    → closed_at (9/9 populated)
  ↓
journal_trade_reviews (19 rows)
decision_outcomes (967 rows)
llm_feedback_observations (317 rows)
```

## Join Map

| From | To | Join Key | Status |
|------|-----|----------|--------|
| proposal → trade | `paper_trade_proposals.paper_trade_id` → `paper_trades.id` | WORKS (11 links) |
| trade → proposal | `paper_trades.proposal_id` → `paper_trade_proposals.id` | WORKS (18 links) |
| proposal → audit | `paper_proposal_approval_audit.proposal_id` | WORKS (1 row — Phase 6C new) |
| trade → broker | `paper_trades.broker` = 'alpaca_paper' | WORKS (15/23 trades) |
| trade → close | `paper_trades.status` = 'closed' + `exit_reason` + `pnl` | WORKS (9/9 complete) |

## What's Strong

- All 9 closed trades have exit_reason, pnl, r_multiple, closed_at
- 18/23 trades link back to their proposal
- 15/23 trades have Alpaca broker confirmation
- 19 journal reviews exist
- 317 feedback observations exist

## What's Missing/Weak

- Only 1 approval audit row (Phase 6C was built mid-session, most trades predate it)
- 5 trades have no proposal_id (created before proposal pipeline existed)
- 72 proposals never became trades (rejected/expired — correct behavior)
- Feedback observations don't link to specific paper_trade_id
- No simulator audit table (Phase 7 is stateless)
