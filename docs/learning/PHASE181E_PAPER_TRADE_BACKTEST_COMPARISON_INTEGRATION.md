# Phase 181E: Paper Trade Backtest Comparison Integration

Status:      HISTORICAL
as_of:       2026-06-01T23:29:18-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-01
**Status**: DESIGNED — Not yet implemented

## Current State

- `strategy_backtest_trades` table: 8,998 rows of historical backtest data
- `paper_performance_governance` table: 161 rows with per-strategy governance metrics
- `paper_trades.backtest_quality`: **0% populated** — no linkage exists
- No script compares paper trade outcomes against backtest expectations

## Required Comparison

For each strategy-linked paper trade:

| Metric | Backtest (Expected) | Paper Trade (Actual) | Comparison |
|--------|--------------------|--------------------|------------|
| Win rate | From backtest runs | Actual outcome | Match/diverge |
| Profit factor | From backtest | Realized PF | Within range? |
| Average R | From backtest | Actual R | Consistent? |
| Stop behavior | Historical stops | Actual stop hit | Pattern match? |
| Hold time | Historical average | Actual hold | Within 2x? |
| Target hit rate | Historical | Actual | Consistent? |

## Implementation Plan

1. **Script**: `paper_trade_backtest_comparison.py` — run nightly after trades close
2. **For each closed trade with strategy_id**:
   - Query `paper_performance_governance` for strategy metrics
   - Query `strategy_backtest_trades` for recent backtest results
   - Compare actual outcome vs expected ranges
   - Write `backtest_quality` to `paper_trades` (ALIGNED / DIVERGENT / INSUFFICIENT_DATA)
3. **Scoring**:
   - ALIGNED: Outcome within 1 std dev of backtest expectation
   - DIVERGENT: Outcome outside 2 std dev — investigate
   - INSUFFICIENT_DATA: < 50 backtest trades for strategy
4. **Output**: Update `paper_trades.backtest_quality` and log to comparison table

### Dependencies

- `paper_performance_governance` populated (161 rows — OK)
- `strategy_backtest_trades` populated (8,998 rows — OK)
- Sufficient closed trades per strategy for comparison

### Safety

- Read-only on backtest data
- Only updates `paper_trades.backtest_quality` field
- No strategy config changes

### Promotion Criteria

A strategy should be:
- **Promoted** if paper results >= backtest expectation (ALIGNED with positive alpha)
- **Observed** if paper results within range but too few trades (< 50)
- **Paused** if paper results significantly worse than backtest (DIVERGENT, negative PF)
- **Adjusted** if stop/target behavior consistently diverges from backtest

### Next Steps

Implementation deferred to next session. This document serves as the design specification.
