# JOURNAL-UX-1B — Closed Trade Telegram Summary Design

**Status:** Design only (not implemented)

## Message Format

After market close, send to proposal decisions channel:

```
Closed Trade Review -- 2026-05-19
Closed: 10 | P&L: $101 | Avg R: 0.09R
3W / 4L / 3F

Best: INFU $68 (CLEAN_WIN)
Review: FLYW -$15 (DATA_OR_BROKER_REVIEW)

Lesson: BLBD instant stop -- check entry spread
Action: Check BLBD spread at entry time

Review queue: 8 items
```

## Rules

- Route to TRADEAI_PROPOSAL_ALERT_CHAT_ID
- No approval buttons
- No orders
- No strategy mutation
- human_review_only
- Deferred to JOURNAL-UX-2
