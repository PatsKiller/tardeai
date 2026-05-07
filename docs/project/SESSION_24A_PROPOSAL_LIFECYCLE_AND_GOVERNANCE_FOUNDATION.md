# Session 24A: Strategy-Aware Proposal Lifecycle + Governance Foundation

**Date:** 2026-05-07

## Why One-Day Expiry Was Wrong

All proposals previously got a 4-hour `timedelta(hours=4)` expiry regardless of strategy. A valid `swing_breakout` (3-21 day hold) or `income_add` (position-grade) proposal would expire before the setup matured.

## 20-Strategy Expiry Map

| Strategy | Hours | Max | Class | Overnight |
|----------|-------|-----|-------|-----------|
| momentum_scalp | 8 | 8 | intraday | No |
| gap_and_go | 10 | 10 | intraday | No |
| earnings_catalyst | 72 | 144 | short_swing | Yes |
| swing_breakout | 120 | 240 | short_swing | Yes |
| swing_trade | 168 | 336 | short_swing | Yes |
| sector_rotation | 336 | 672 | medium_swing | Yes |
| income_add | 240 | 480 | position | Yes |
| core_growth_compounder | 720 | 720 | position | Yes |
| defense_thesis | 720 | 720 | position | Yes |
| (+ 11 more position strategies) | 720 | 720 | position | Yes |

## Intraday vs Overnight Behavior

- **Intraday** (momentum_scalp, gap_and_go): Expire at EOD. Never carry overnight. No extension.
- **Overnight** (all others): Monitored across sessions. Extend if entry zone valid. Max expiry = 2x base (capped at 720h for long-term).

## Proposal Monitor

`scripts/proposal_monitor.py` — runs during AH (4:30 PM), evening (6 PM), pre-market (6 AM, 6:30 AM):
1. Gets current quote via multi-provider hierarchy
2. Computes price drift vs entry
3. Evaluates entry zone validity (strategy-specific thresholds)
4. Extends expiry if zone valid and within max window
5. Marks ENTRY_MISSED with manual_review_required if drifted too far
6. Writes lifecycle events
7. Never approves or submits

## Extension Safeguards

- Only extend overnight strategies
- Entry zone must still be valid (drift < strategy threshold)
- Cannot exceed max_expires_at
- Extension count tracked
- Delayed/display-only quotes labeled in extension reason

## Session 24 Governance Foundation

### TCA (paper_execution_quality)
Analyzes: intended entry vs fill, arrival price, spread at submit, slippage %, fill quality (EXCELLENT/GOOD/ACCEPTABLE/POOR/UNKNOWN)

### Broker Reconciliation (broker_reconciliation_runs/items)
Compares: Alpaca paper positions/orders vs local paper_trades. States: MATCHED, BROKER_ORDER_NO_LOCAL_TRADE, etc.

### Thesis Review (trade_thesis_outcomes)
Compares: expected entry/stop/target/R vs actual. Results: THESIS_CONFIRMED, THESIS_PARTIAL, THESIS_INVALIDATED, THESIS_ABANDONED

### Six-Month Governance (paper_performance_governance)
Per-strategy: trade count, win rate, expectancy, profit factor, drawdown. States: PAPER_ONLY -> WATCHLIST -> CANDIDATE_FOR_REVIEW -> LIVE_ELIGIBLE_REVIEW_REQUIRED. Live always blocked.

## Validation: 34/34 PASSED
