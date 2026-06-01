# Hermes Phase 30B — Expanded Librarian Dry-Run Report

**Date:** 2026-06-01
**Status:** COMPLETE — dry-run only, zero DB writes

## Views Used

| View | Rows Reviewed | Findings |
|------|--------------|----------|
| hermes_v_journal_learning_context | 0 (empty) | 1 (info — no data) |
| hermes_v_backtest_results_context | 25 | 13 |
| hermes_v_screener_context | 25 | 5 |
| hermes_v_catalyst_quality_context | 25 (subset) | 2 |

## Findings Summary

| Category | Count | Key Findings |
|----------|-------|-------------|
| Journal | 1 | JRN-ALL: Journal empty — thesis reviews not generated |
| Backtest | 13 | BT-5: 4 strategies with 0% win rate. BT-1: 5 strategies < 40% win rate. BT-3: 2 with profit_factor < 1.0 |
| Screener | 5 | MS-1: 3 underfilled runs. MS-3: 2 runs with zero GO candidates |
| Catalyst | 2 | CAT-2: 25 generic 'other' catalysts. CAT-1: 25 low-confidence catalysts |
| **Total** | **21** | |

## Research Backlog Candidates (11, capped at 10 for staging)

| Priority | Type | Finding |
|----------|------|---------|
| medium | journal_lesson_missing | Journal learning system empty |
| high | backtest_contradiction | swing_trade SHMD 0% win rate |
| high | backtest_contradiction | core_growth_compounder 0% win rate |
| high | backtest_contradiction | recovery_watch 0% win rate |
| high | backtest_contradiction | earnings_catalyst 0% win rate |
| high | backtest_contradiction | Combined strategies 27.59% win rate (n=29) |
| high | backtest_contradiction | swing_breakout 28.57% win rate (n=7) |
| high | backtest_contradiction | momentum_scalp 30.0% win rate (n=20) |
| high | backtest_contradiction | all_signals 33.9% win rate (n=59) |
| high | backtest_contradiction | Combined screener strategies 39.13% (n=46) |
| medium | strategy_underperformance | Combined profit_factor 0.3153 (n=29) |

## Key Insights

1. **Journal is NOT active** — zero thesis reviews exist. Trade learning loop is not generating post-trade analysis.
2. **Multiple strategies have sub-40% win rates** — swing_trade, core_growth_compounder, recovery_watch, earnings_catalyst all at 0% (tiny samples). The aggregate all_signals result is 33.9% across 59 trades.
3. **Momentum scalp has 30% win rate** across 20 trades — borderline but notable given it's the most active strategy.
4. **Screener runs occasionally underfilled** — 3 of 25 recent runs marked RUN_UNDERFILLED.
5. **Catalyst quality is weak** — many events typed as generic 'other' with low confidence (0.3).

## Safety

- [x] DB writes: ZERO
- [x] Source table writes: ZERO
- [x] Embeddings: ZERO
- [x] Promotions: ZERO
- [x] File output only
