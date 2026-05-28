# v3.7 Unified Trade Lifecycle Inspector Report

**Date:** 2026-05-28

## Files Changed

| File | Change |
|------|--------|
| `scripts/api_v2.py` | Added `GET /api/v2/lifecycle/trade-inspector` |
| `scripts/lib/trade_inspector.py` | NEW — read-only aggregate inspector helper |
| `apps/command-center-v2/src/components/UnifiedTradeInspector.tsx` | NEW — 10-tab inspector panel |
| `apps/command-center-v2/src/pages/ATMControlRoom.tsx` | Added inspector state + render |

## Endpoint

`GET /api/v2/lifecycle/trade-inspector?symbol=X` or `?paper_trade_id=N`

Aggregates: overview, signals, proposals, execution/TCA, stops/audit, reconciliation,
journal, learning, backtest, LLM review, data quality gaps, lifecycle events, trace.

## Tabs: 10

Overview, Source, Proposal, Execution, Stops, Journal, Learning, LLM Review, Data Quality, Raw

## Validation

| Query | Result |
|-------|--------|
| BLMN | #38 open, 4 signals, 5 proposals, 9 events, llm=not_configured |
| APPS | closed, exit=position_closed_in_alpaca, 1 stop audit event |
| AGNC | open, stop=$9.71 |

## LLM Review Hook: YES

Tab shows `not_configured` status. No model calls executed by endpoint. `model_calls_executed_by_endpoint: false`.

## Accounts & Trades

Inspector works for ALL accounts and trades (not just automated). Uses `paper_trades` table
which contains all account types (ALPACA_PAPER, TOS_PAPER, etc.). No broker-specific
hardcoding — queries by symbol/paper_trade_id/trace_id regardless of account.

## Build: Clean (438ms)

## Safety

- No orders placed / No broker writes / No DB trading writes
- No paper_trades changes / No proposal changes
- No journal/backtest mutations / No LLM calls
- ALPACA_MODE=paper, LLM_DISABLE=true

## Rollback

```bash
git revert HEAD
```
