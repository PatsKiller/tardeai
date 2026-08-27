# v3.6 Journal / Learning / Backtesting Implementation Plan

## Current State
- 4 open trades, 30 closed trades
- 480 lifecycle traces, 480 trace events
- Journal endpoint returns 3 open + 14 closed via /api/v2/automated-journal
- TCA: 10 rows, timing fields null for historical
- Stop audit: 1 event (APPS repair)
- Learning: trade_lesson_memory and strategy_lesson_rollup exist
- Backtesting: page exists but not connected to paper trade outcomes

## Proposed v3.6

### 1. Journal-Learning Summary API
Read-only endpoint joining lifecycle traces → paper outcomes → TCA → stop audit.

### 2. Paper-vs-Backtest Comparison API
Compare strategy backtest expectations vs actual paper results for closed trades.

### 3. Trade Case Study API
Per-trade deep view: proposal → approval → execution → stops → exit → TCA → learning.

### 4. JournalLearningWorkspace Component
Unified view replacing scattered journal/learning/backtest pages.

### What v3.6 Will NOT Do
- No trading actions
- No broker writes
- No journal mutation
- No destructive backtests
- No stop changes
- No proposal expiration
