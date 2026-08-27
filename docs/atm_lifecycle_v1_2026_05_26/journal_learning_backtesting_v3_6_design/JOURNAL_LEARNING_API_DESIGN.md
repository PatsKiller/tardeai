# Journal/Learning API Design

## GET /api/v2/lifecycle/journal-learning-summary
- closed trades with lifecycle linkage
- win/loss/R-multiple/strategy breakdown
- TCA quality per trade
- stop-change events per trade
- data quality gaps (missing traces, missing TCA)
- duplicate contamination check

## GET /api/v2/lifecycle/paper-vs-backtest
- per strategy: backtest expected vs paper actual
- win rate comparison
- R-multiple comparison
- missed proposal count
- data quality flag

## GET /api/v2/lifecycle/trade-case-study?paper_trade_id=N
- full lifecycle timeline for one trade
- proposal → approval → execution → stops → exit → TCA → learning
- all related lifecycle_events and lifecycle_trace_events

All read-only. Safety block in every response.
