# Stop Management V2.3 — Strategy Trailing Tiers

**Phase:** STOP-V2.3
**Date:** 2026-05-22

## What Was Built

`strategy_trailing_policy.py` — strategy-aware trailing stop policy module:

| Family | Strategies | Breakeven At | Lock 0.5R | Lock 1.0R | Lock 2.0R | Time Stop |
|--------|-----------|-------------|-----------|-----------|-----------|-----------|
| **Momentum** | momentum_scalp, gap_and_go, earnings_catalyst | 1.0R | 1.5R | 2.0R | 3.0R | Intraday 15:45 |
| **Swing** | swing_trade, swing_breakout, fib_retracement | 1.0R | 1.5R | 2.0R | 3.0R | 21 days |
| **Income** | dividend_growth, reit_income, recovery_watch | 1.5R | 2.5R | 3.5R | 5.0R | Review at 90d |
| **Position** | core_growth, defense_thesis, sector_rotation | 2.0R | 3.0R | 4.0R | 6.0R | Review at 180d |
| **Unknown** | any unclassified | No auto-trail | — | — | — | Review at 30d |

Integrated into `unified_stop_supervisor.py` — each cycle reports trailing
recommendations per open position with strategy family, R-multiple, and
recommended action (hold / recommend_trail / recommend_deferred / recommend_review).

## What Was NOT Done

- No actual stop movement (dry-run recommendations only in V2.3)
- No broker orders created, canceled, or moved
- Stop movement activation deferred to operator approval
