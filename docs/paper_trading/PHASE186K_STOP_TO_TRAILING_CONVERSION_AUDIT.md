# Phase 186K: Hard-Stop to Trailing-Stop Conversion Audit

Status:      HISTORICAL
as_of:       2026-06-02T01:02:56-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-02

## Results

| Metric | Value |
|--------|-------|
| Total closed paper trades | 24 |
| Total stop-out exits | 6 |
| Hard stop exits | 6 |
| Trailing stop exits | 0 |
| Converted hard→trailing | **0 (0%)** |
| Hard stop only | 95.8% (23/24) |
| No stop data | 1 |

## Stop Exit Detail

| Trade | Symbol | Strategy | Stop Type | PnL | R | MFE |
|-------|--------|----------|-----------|-----|---|-----|
| #16 | BLBD | earnings_catalyst | hard | -$14.80 | -0.05 | 0.0% |
| #22 | GCTS | momentum_scalp | hard | -$225.00 | -0.14 | 0.0% |
| #24 | FLYW | dividend_growth_compounder | hard | $27.36 | 0.21 | 1.0% |
| #29 | NVDA | dividend_growth_compounder | hard | -$4.90 | -0.66 | 0.4% |
| #38 | BLMN | swing_trade | hard | -$10.89 | 0.00 | 6.0% |
| #42 | ONDS | swing_breakout | hard | -$55.08 | 0.00 | 7.1% |

## Risk Action Summary

| Action | Count |
|--------|-------|
| trailing_stop_update | 7 |
| target_hit_close | 6 |
| time_stop_close | 4 |
| stop_hit_close | 3 |
| trailing_stop_switch | 1 (operator-initiated, NVDA) |
| operator_stop_out | 1 |

## Key Findings

1. **Zero systematic hard-to-trailing conversions**: The R-multiple trailing algorithm exists but no trade reached +1R to trigger breakeven move.
2. **One operator-initiated trailing switch**: NVDA #29 was manually switched to 5% trailing by operator via Telegram. It was still stopped out at -0.66R.
3. **7 trailing stop updates recorded**: These are R-multiple checks by paper_trade_monitor that computed new stop levels but the positions hadn't moved enough for actual stop movement.
4. **All stop exits were at loss or breakeven**: No trade was stopped out after the trailing algorithm moved the stop up. This means the trailing system was never truly tested.
5. **BLMN #38 and ONDS #42**: stop==entry (the old geometry defect). These had 6-7% MFE but the hard stop couldn't capture any profit because the initial stop was at entry.
6. **BLMN #38 insight**: MFE was 6.0% — a trailing stop at breakeven (+1R) would have locked ~$0 instead of losing $10.89. But stop==entry made it impossible.

## Algorithm Status

| Component | Status |
|-----------|--------|
| strategy_trailing_policy.py v2.3 | EXISTS — 4 families, R-multiple tiers |
| paper_trade_monitor.py integration | EXISTS — calls get_trailing_policy() |
| Actual trailing in production | NEVER TRIGGERED (0 trades reached +1R threshold) |
| After-hours trailing | DISABLED (all families set False) |
| Operator manual trailing | EXISTS via Telegram (1 use) |

## Conclusion

The trailing stop algorithm is **designed but unproven**. No trade has systematically been converted from hard stop to trailing stop by the algorithm. The sample is too small (24 trades) and too many stop exits occurred at negative R, meaning the algorithm never had a chance to activate. More paper trades at positive R are needed before trailing effectiveness can be evaluated.
