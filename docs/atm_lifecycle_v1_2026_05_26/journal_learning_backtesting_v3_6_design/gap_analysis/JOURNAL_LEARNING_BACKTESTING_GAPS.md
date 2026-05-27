# Journal/Learning/Backtesting Gap Register

## P0 — Safety / Data Integrity
1. Historical strategy_lesson_rollup may include ghost/duplicate trade data
2. Closed trade count (30) includes rows closed by various mechanisms — not all have clean lifecycle traces

## P1 — Operator Actionability
3. No paper-vs-backtest comparison available
4. No missed-proposal impact calculation
5. TCA not feeding learning pipeline
6. Stop audit not feeding learning pipeline
7. No trade case-study view for deep analysis
8. No data quality dashboard for journal metrics

## P2 — UX
9. Journal/learning/backtest scattered across 5+ pages
10. Backtesting page not connected to real outcomes
11. Self-improvement page not actionable

## P3 — Cleanup
12. Backtest schema different from paper trade schema
13. Multiple overlapping journal/report endpoints
