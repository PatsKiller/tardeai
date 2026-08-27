# Phase 6D Scope — Proposal Stale-Time Sweeper

**Date:** 2026-05-15

## 1. Purpose

Mark stale/expired/requires-refresh paper proposals before an operator attempts approval, keeping the approval screen clean.

Phase 6D does not approve, reject, create, or submit trades. It only marks stale proposal state and records audit evidence.

Approval remains blocked unless the proposal passes freshness, session policy, market revalidation, risk gate, and audit requirements.

## 2. Relationship to Phase 6A/6B/6C

Phase 6D adds a freshness gate BEFORE the existing session/revalidation/risk gates:

```
Approve → Audit → Freshness Gate → Session Gate → Revalidation → Risk Gate → Paper Trade → Alpaca
```

## 3. Stale Policy Defaults

| Strategy | Stale After |
|----------|-------------|
| momentum_scalp, gap_and_go, scalp | 60 min |
| screener, day_trade | 4 hours |
| swing, swing_trade, swing_breakout | 3 trading days (4320 min) |
| recovery_watch | 5 trading days (7200 min) |
| income, dividend, position | 10 trading days (14400 min) |
| unknown | 24 hours |

## 4-12. Standard safety gates, rollback via `git revert`, no live trading.
